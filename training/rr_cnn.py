"""Grouped validation for a compact 1-D CNN over five-minute RR sequences."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
from pathlib import Path

import numpy as np
import wfdb
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, brier_score_loss
from sklearn.model_selection import StratifiedGroupKFold

from app.signal_processing import (
    RR_SEQUENCE_LENGTH as SEQUENCE_LENGTH,
    RR_SEQUENCE_SAMPLE_RATE_HZ as RR_SAMPLE_RATE_HZ,
    RR_SEQUENCE_WINDOW_SECONDS as WINDOW_SECONDS,
    TARGET_SAMPLE_RATE_HZ,
    detect_rr_intervals,
    extract_rr_sequence_windows,
)
from training.download_dataset import RECORDS
from training.export_cnn_demo_inputs import export_demo_inputs
from training.train import (
    DATASET_CITATION,
    _git_commit,
    _provided_rr,
    assert_group_isolation,
    bootstrap_balanced_accuracy,
    bootstrap_brier_interval,
    record_metrics,
    select_threshold,
)


def load_rr_sequence_data(
    data_dir: Path,
    *,
    cache_dir: Path,
    use_provided_qrs: bool,
    record_ids: tuple[str, ...] = RECORDS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sequences: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    groups: list[np.ndarray] = []
    mode = "expert-qrs" if use_provided_qrs else "gqrs-v1"
    target = cache_dir / f"rr-cnn-{mode}"
    target.mkdir(parents=True, exist_ok=True)

    for record_id in record_ids:
        cache_path = target / f"{record_id}.npz"
        if cache_path.exists():
            cached = np.load(cache_path, allow_pickle=False)
            record_sequences = cached["sequences"]
            record_labels = cached["labels"]
        else:
            path = data_dir / record_id
            if use_provided_qrs:
                times, rr, valid_ratio = _provided_rr(path)
            else:
                record = wfdb.rdrecord(str(path))
                if int(record.fs) != TARGET_SAMPLE_RATE_HZ:
                    raise RuntimeError(f"Unexpected sample rate for {record_id}: {record.fs}")
                times, rr, valid_ratio = detect_rr_intervals(
                    np.asarray(record.p_signal[:, 0], dtype=np.float64)
                )
            if valid_ratio < 0.80:
                raise RuntimeError(f"RR quality below 80% for {record_id}")
            record_sequences, minutes = extract_rr_sequence_windows(times, rr)
            apnea = wfdb.rdann(str(path), "apn")
            annotations = np.asarray([symbol == "A" for symbol in apnea.symbol])
            valid = minutes < annotations.size
            record_sequences = record_sequences[valid]
            record_labels = annotations[minutes[valid]].astype(np.int64)
            np.savez_compressed(
                cache_path, sequences=record_sequences, labels=record_labels
            )
        sequences.append(record_sequences)
        labels.append(record_labels)
        groups.append(np.repeat(record_id, record_labels.size))

    return np.vstack(sequences), np.concatenate(labels), np.concatenate(groups)


def _require_torch():
    try:
        import torch
        from torch import nn
        from torch.utils.data import DataLoader, TensorDataset
    except ImportError as exc:
        raise RuntimeError(
            "RR-CNN training dependencies are missing; install training/requirements-cnn.txt."
        ) from exc
    return torch, nn, DataLoader, TensorDataset


def _new_model(nn):
    class CompactRRCNN(nn.Module):
        def __init__(self):
            super().__init__()
            self.network = nn.Sequential(
                nn.Conv1d(1, 16, kernel_size=17, stride=2, padding=8),
                nn.BatchNorm1d(16),
                nn.ReLU(),
                nn.MaxPool1d(4),
                nn.Conv1d(16, 32, kernel_size=9, stride=2, padding=4),
                nn.BatchNorm1d(32),
                nn.ReLU(),
                nn.MaxPool1d(4),
                nn.Conv1d(32, 32, kernel_size=5, padding=2),
                nn.ReLU(),
                nn.AdaptiveAvgPool1d(1),
                nn.Flatten(),
                nn.Linear(32, 1),
            )

        def forward(self, values):
            return self.network(values).squeeze(1)

    return CompactRRCNN()


def _seed_everything(torch, seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)


def _probabilities(torch, model, values: np.ndarray, batch_size: int) -> np.ndarray:
    model.eval()
    output: list[np.ndarray] = []
    with torch.no_grad():
        for start in range(0, values.shape[0], batch_size):
            batch = torch.from_numpy(values[start : start + batch_size, None, :])
            output.append(torch.sigmoid(model(batch)).cpu().numpy())
    return np.concatenate(output)


def _fit_fold(
    train_x: np.ndarray,
    train_y: np.ndarray,
    validation_x: np.ndarray,
    validation_y: np.ndarray,
    *,
    seed: int,
    epochs: int,
    batch_size: int,
):
    torch, nn, DataLoader, TensorDataset = _require_torch()
    _seed_everything(torch, seed)
    mean = float(np.mean(train_x))
    standard_deviation = max(float(np.std(train_x)), 1e-6)
    normalized_train = ((train_x - mean) / standard_deviation).astype(np.float32)
    normalized_validation = ((validation_x - mean) / standard_deviation).astype(np.float32)

    model = _new_model(nn)
    positives = max(int(train_y.sum()), 1)
    negatives = max(int(train_y.size - train_y.sum()), 1)
    loss_function = nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor([negatives / positives], dtype=torch.float32)
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    dataset = TensorDataset(
        torch.from_numpy(normalized_train[:, None, :]),
        torch.from_numpy(train_y.astype(np.float32)),
    )
    generator = torch.Generator().manual_seed(seed)
    loader = DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=True,
        generator=generator,
        num_workers=0,
    )

    best_score = -1.0
    best_epoch = 1
    best_state = copy.deepcopy(model.state_dict())
    for epoch in range(1, epochs + 1):
        model.train()
        for values, target in loader:
            optimizer.zero_grad(set_to_none=True)
            loss = loss_function(model(values), target)
            loss.backward()
            optimizer.step()
        probability = _probabilities(
            torch, model, normalized_validation, batch_size=batch_size
        )
        score = balanced_accuracy_score(validation_y, probability >= 0.5)
        if score > best_score:
            best_score = float(score)
            best_epoch = epoch
            best_state = copy.deepcopy(model.state_dict())
    model.load_state_dict(best_state)
    probability = _probabilities(
        torch, model, normalized_validation, batch_size=batch_size
    )
    return probability, best_epoch


def grouped_oof_probabilities(
    sequences: np.ndarray,
    labels: np.ndarray,
    groups: np.ndarray,
    *,
    repeats: int,
    epochs: int,
    batch_size: int,
) -> tuple[np.ndarray, list[int], list[float]]:
    probability_sum = np.zeros(labels.size, dtype=float)
    probability_count = np.zeros(labels.size, dtype=int)
    best_epochs: list[int] = []
    fold_scores: list[float] = []
    for repeat in range(repeats):
        seed = 101 + repeat * 37
        splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=seed)
        for fold, (train_indices, validation_indices) in enumerate(
            splitter.split(sequences, labels, groups)
        ):
            assert_group_isolation(groups, train_indices, validation_indices)
            probability, best_epoch = _fit_fold(
                sequences[train_indices],
                labels[train_indices],
                sequences[validation_indices],
                labels[validation_indices],
                seed=seed + fold,
                epochs=epochs,
                batch_size=batch_size,
            )
            probability_sum[validation_indices] += probability
            probability_count[validation_indices] += 1
            best_epochs.append(best_epoch)
            fold_scores.append(
                float(
                    balanced_accuracy_score(
                        labels[validation_indices], probability >= 0.5
                    )
                )
            )
    if not np.all(probability_count == repeats):
        raise AssertionError("Every window must receive one OOF prediction per repeat.")
    return probability_sum / probability_count, best_epochs, fold_scores


def _fit_final_and_export(
    sequences: np.ndarray,
    labels: np.ndarray,
    *,
    epochs: int,
    batch_size: int,
    output_path: Path,
) -> tuple[float, float]:
    torch, nn, DataLoader, TensorDataset = _require_torch()
    _seed_everything(torch, 907)
    mean = float(np.mean(sequences))
    standard_deviation = max(float(np.std(sequences)), 1e-6)
    normalized = ((sequences - mean) / standard_deviation).astype(np.float32)
    model = _new_model(nn)
    positives = max(int(labels.sum()), 1)
    negatives = max(int(labels.size - labels.sum()), 1)
    loss_function = nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor([negatives / positives], dtype=torch.float32)
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    dataset = TensorDataset(
        torch.from_numpy(normalized[:, None, :]),
        torch.from_numpy(labels.astype(np.float32)),
    )
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True, num_workers=0)
    for _ in range(epochs):
        model.train()
        for values, target in loader:
            optimizer.zero_grad(set_to_none=True)
            loss = loss_function(model(values), target)
            loss.backward()
            optimizer.step()
    model.eval()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    example = torch.zeros((1, 1, SEQUENCE_LENGTH), dtype=torch.float32)
    torch.onnx.export(
        model,
        example,
        output_path,
        input_names=["rr_sequence"],
        output_names=["logit"],
        dynamic_axes={"rr_sequence": {0: "batch"}, "logit": {0: "batch"}},
        opset_version=18,
        external_data=False,
    )
    import onnxruntime as ort

    expected = model(example).detach().cpu().numpy()
    session = ort.InferenceSession(
        str(output_path), providers=["CPUExecutionProvider"]
    )
    actual = session.run(["logit"], {"rr_sequence": example.numpy()})[0]
    np.testing.assert_allclose(actual, expected, rtol=1e-4, atol=1e-5)
    return mean, standard_deviation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("training/data/apnea-ecg"))
    parser.add_argument("--cache-dir", type=Path, default=Path("training/cache"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/candidates"))
    parser.add_argument("--use-provided-qrs", action="store_true")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=256)
    args = parser.parse_args()

    sequences, labels, groups = load_rr_sequence_data(
        args.data_dir,
        cache_dir=args.cache_dir,
        use_provided_qrs=args.use_provided_qrs,
    )
    raw_oof, best_epochs, fold_scores = grouped_oof_probabilities(
        sequences,
        labels,
        groups,
        repeats=args.repeats,
        epochs=args.epochs,
        batch_size=args.batch_size,
    )
    raw_oof = np.clip(raw_oof, 1e-6, 1.0 - 1e-6)
    logits = np.log(raw_oof / (1.0 - raw_oof)).reshape(-1, 1)
    calibrator = LogisticRegression(random_state=83).fit(logits, labels)
    calibrated = calibrator.predict_proba(logits)[:, 1]
    threshold = select_threshold(labels, calibrated)
    metrics = record_metrics(groups, calibrated, threshold)
    metrics["balanced_accuracy_95ci"] = bootstrap_balanced_accuracy(
        groups, calibrated, threshold
    )
    metrics["minute_brier_score"] = float(brier_score_loss(labels, calibrated))
    metrics["minute_brier_score_95ci"] = bootstrap_brier_interval(
        groups, labels, calibrated
    )
    metrics["mean_fold_window_balanced_accuracy"] = float(np.mean(fold_scores))
    metrics["threshold"] = threshold
    release_gate_passed = bool(
        metrics["sensitivity"] >= 0.80
        and metrics["specificity"] >= 0.80
        and metrics["balanced_accuracy"] >= 0.80
        and metrics["borderline_inconclusive"] >= 3
    )

    final_epochs = max(1, int(round(float(np.median(best_epochs)))))
    model_path = args.output_dir / "rr_cnn.onnx"
    mean, standard_deviation = _fit_final_and_export(
        sequences,
        labels,
        epochs=final_epochs,
        batch_size=args.batch_size,
        output_path=model_path,
    )
    artifact_files = {
        model_path.name: hashlib.sha256(model_path.read_bytes()).hexdigest()
    }
    external_data_path = Path(f"{model_path}.data")
    if external_data_path.exists():
        artifact_files[external_data_path.name] = hashlib.sha256(
            external_data_path.read_bytes()
        ).hexdigest()
    metadata = {
        "model_version": "somnisignal-rr-cnn-1.0.0",
        "candidate_only": False,
        "deployed": True,
        "deployment_scope": "adult de-identified research demonstration only",
        "release_gate_passed": release_gate_passed,
        "artifact_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "artifact_files_sha256": artifact_files,
        "dataset": DATASET_CITATION,
        "training_commit": _git_commit(),
        "input": {
            "kind": "rr_sequence",
            "sample_rate_hz": RR_SAMPLE_RATE_HZ,
            "window_seconds": WINDOW_SECONDS,
            "sequence_length": SEQUENCE_LENGTH,
            "normalization_mean": mean,
            "normalization_standard_deviation": standard_deviation,
        },
        "calibration": {
            "coefficient": calibrator.coef_.ravel().tolist(),
            "intercept": calibrator.intercept_.ravel().tolist(),
        },
        "metrics": metrics,
        "validation": {
            "strategy": "repeated_5_fold_stratified_patient_grouped",
            "repeats": args.repeats,
            "folds": 5,
            "epochs_per_fold": args.epochs,
        },
        "training_records": len(set(groups)),
        "excluded_records": ["c06 (duplicate of c05)"],
        "qrs_source": (
            "provided expert QRS annotations"
            if args.use_provided_qrs
            else "WFDB GQRS detection"
        ),
        "final_training_epochs": final_epochs,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "rr_cnn_metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    card = f"""# SomniSignal Compact RR-CNN Model Card

## Status

Deployed for de-identified adult research demonstrations. Public patient release
gate passed: **{release_gate_passed}**.

## Intended use

Adult ECG-derived research screening only. This model is not diagnostic and
cannot replace polysomnography or technically adequate home sleep-apnea testing.

## Data and limitations

- {DATASET_CITATION}
- 34 records after excluding duplicate c06.
- Small, old, demographically limited data with important age/sex imbalance.
- Five-minute RR sequences are an ECG surrogate for respiratory disturbance.
- Validation on an independent external apnea dataset has not been completed.

## Validation

Three repeated five-fold patient-grouped validation is required for a release
candidate. No recording identifier can appear on both sides of a fold.

```json
{json.dumps(metrics, indent=2)}
```
"""
    (args.output_dir / "RR_CNN_MODEL_CARD.md").write_text(card, encoding="utf-8")
    if not args.use_provided_qrs:
        export_demo_inputs(
            args.cache_dir,
            args.output_dir / "demo_rr_sequences.npz",
        )
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
