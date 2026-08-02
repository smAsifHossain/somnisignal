from __future__ import annotations

import argparse
import json
from pathlib import Path


def _read(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts"))
    args = parser.parse_args()

    feature = _read(args.artifact_dir / "model_metadata.json")
    apdet = _read(args.artifact_dir / "apdet_baseline_metrics.json")
    cnn = _read(args.artifact_dir / "candidates" / "rr_cnn_metadata.json")
    candidates: list[dict] = []
    if feature:
        candidates.append(
            {
                "name": feature.get("selected_model", "feature_model"),
                "artifact": "model.joblib",
                "metrics": feature.get("metrics", {}),
                "release_gate_passed": bool(feature.get("release_gate_passed")),
                "status": "superseded_baseline",
            }
        )
    if apdet:
        candidates.append(
            {
                "name": apdet.get("implementation", "apdet_style"),
                "artifact": None,
                "metrics": {
                    key: apdet.get(key)
                    for key in ("sensitivity", "specificity", "balanced_accuracy")
                },
                "release_gate_passed": bool(apdet.get("release_gate_passed")),
                "status": "research_comparator",
            }
        )
    if cnn:
        validation = cnn.get("validation", {})
        is_release_run = (
            validation.get("repeats") == 3
            and validation.get("folds") == 5
            and cnn.get("qrs_source") == "WFDB GQRS detection"
        )
        candidates.append(
            {
                "name": "compact_rr_cnn",
                "artifact": "candidates/rr_cnn.onnx",
                "metrics": cnn.get("metrics", {}),
                "release_gate_passed": bool(
                    cnn.get("release_gate_passed") and is_release_run
                ),
                "status": (
                    "deployed_research_demo"
                    if cnn.get("deployed") and is_release_run
                    else "release_candidate" if is_release_run else "smoke_only"
                ),
            }
        )

    eligible = [item for item in candidates if item["release_gate_passed"]]
    selected = None
    if eligible:
        selected = max(
            eligible,
            key=lambda item: float(item["metrics"].get("balanced_accuracy", 0.0)),
        )["name"]
    research_candidates = [
        item
        for item in candidates
        if item["name"] == "compact_rr_cnn"
        and item["status"] == "deployed_research_demo"
    ]
    research_selected = research_candidates[0]["name"] if research_candidates else None
    report = {
        "selected_for_research_demo": research_selected,
        "selected_for_clinical_release": selected,
        "deployment_changed": bool(research_selected),
        "reason": (
            "A candidate passed every release metric; independent external validation is still required."
            if selected
            else (
                "The compact RR-CNN passed the primary A/C performance thresholds and is deployed for research analysis; clinical deployment remains gated."
                if research_selected
                else "No candidate passed every locked release metric; clinical outcomes remain gated."
            )
        ),
        "candidates": candidates,
    }
    output = args.artifact_dir / "model_comparison.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
