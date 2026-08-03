<div align="center">

# SomniSignal

**Sleep-apnea risk prediction from an overnight ECG, served from a personal laptop.**

SomniSignal turns an adult single-lead ECG into an elevated-risk,
low-risk, or inconclusive research prediction. The interface is public, the model
runs locally, and the laptop is never exposed through an open inbound port.

<p>
  <a href="https://smasifhossain.github.io/somnisignal/"><img alt="SomniSignal live application" src="https://img.shields.io/badge/Live%20app-Open-6366f1?style=flat&amp;logo=googlechrome&amp;logoColor=white&amp;labelColor=111827"></a>
  <a href="pyproject.toml"><img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-3776ab?style=flat&amp;logo=python&amp;logoColor=white&amp;labelColor=111827"></a>
  <a href="backend/app/main.py"><img alt="FastAPI application" src="https://img.shields.io/badge/API-FastAPI-009688?style=flat&amp;logo=fastapi&amp;logoColor=white&amp;labelColor=111827"></a>
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/License-MIT-16a34a?style=flat&amp;logo=opensourceinitiative&amp;logoColor=white&amp;labelColor=111827"></a>
</p>

[Live application](https://smasifhossain.github.io/somnisignal/) | [Model card](docs/MODEL_CARD.md) | [Security design](SECURITY.md) | [Release gates](docs/RELEASE_GATES.md)

If SomniSignal is useful to you, consider [starring the repository](https://github.com/smAsifHossain/somnisignal). It helps others discover and support the project.

### Video walkthrough

<a href="https://www.youtube.com/watch?v=NCTUHNkg-OI">
  <img src="https://img.youtube.com/vi/NCTUHNkg-OI/maxresdefault.jpg" alt="Watch the SomniSignal video walkthrough" width="720">
</a>

[Watch the SomniSignal walkthrough on YouTube](https://www.youtube.com/watch?v=NCTUHNkg-OI)

</div>

---

## What SomniSignal does

SomniSignal is an adult-only research prototype for evaluating sleep-apnea-associated
patterns in overnight ECG recordings. It detects heartbeats, derives RR intervals,
builds overlapping five-minute sequences, and runs a compact one-dimensional CNN
on the resulting cardiac rhythm data. Minute-level estimates are calibrated and
combined into one nightly prediction.

The project was built to show that a useful ML service can run on modest hardware.
GitHub Pages hosts the interface, a Cloudflare Worker protects the public boundary,
and an authenticated Cloudflare Tunnel reaches a CPU-only FastAPI container on the
laptop. No public IP address or inbound router configuration is required.

SomniSignal does not diagnose sleep apnea and cannot rule it out. Clinical diagnosis
requires evaluation by a qualified professional, usually with polysomnography or a
technically adequate home sleep-apnea test.

## Main features

- Compact RR-CNN inference through ONNX Runtime on two CPU cores.
- CSV, compressed CSV, NPY, EDF, BDF, and zipped WFDB input normalization.
- Automatic ECG-channel selection with an explicit channel override when needed.
- Asynchronous jobs with live progress, cancellation, and 15-minute result expiry.
- One-job concurrency, a 25 MB upload limit, and immediate raw-file deletion.
- Light and dark interface themes with no accounts, analytics, or result history.
- Private laptop origin reached only through an authenticated Cloudflare tunnel.
- Grouped model validation that keeps every recording in a single fold.

## How a recording is analyzed

1. **Validate the signal.** The service checks format, duration, sample rate,
   finite values, clipping, flat segments, and ECG-channel availability.
2. **Detect heartbeats.** WFDB GQRS locates QRS complexes and converts them into
   RR intervals. Values outside 300 to 2,000 ms are rejected.
3. **Build model inputs.** Valid intervals are interpolated at 4 Hz and divided
   into five-minute windows advanced once per minute.
4. **Run the CNN.** The ONNX model produces minute-level estimates and applies
   the stored Platt calibration.
5. **Produce the nightly prediction.** The service reports risk direction,
   estimated apnea-like minutes, signal quality, and the model version.

The nightly rules are intentionally simple and documented:

| Prediction | Rule |
| --- | --- |
| Elevated risk | At least 100 flagged minutes and at least 10 flagged minutes within one rolling hour |
| Low risk | Fewer than 5 flagged minutes |
| Inconclusive | Intermediate burden or a failed signal-quality check |

The displayed risk score is the model's mean calibrated minute score. It is not the
probability that a person has a clinical diagnosis.

## Model

The deployed model is `somnisignal-rr-cnn-1.0.0`, a compact one-dimensional CNN
trained on RR sequences and exported to ONNX. PyTorch is used only for training;
the production image uses ONNX Runtime on CPU.

Training uses the PhysioNet Apnea-ECG Database learning set. Duplicate record `c06`
is excluded, leaving 34 recording-level groups. Three repeated five-fold grouped
validation runs produced the following July 2026 results:

| Metric | Result |
| --- | ---: |
| Apnea/control record sensitivity | 0.850 |
| Apnea/control record specificity | 0.889 |
| Record-level balanced accuracy | 0.869 |
| Balanced accuracy bootstrap interval | 0.717 to 0.975 |
| Calibrated minute Brier score | 0.124 |
| Brier score bootstrap interval | 0.094 to 0.152 |

These figures are grouped internal validation, not independent external validation.
The dataset is small, old, and demographically limited. Full methodology, artifact
hashes, and limitations are documented in the [model card](docs/MODEL_CARD.md).

## Supported recordings

SomniSignal expects one documented adult single-lead ECG lasting 6 to 12 hours,
sampled from 80 to 250 Hz. At least 99.5 percent of samples must be finite, and at
least 80 percent of derived RR intervals must pass validation.

| Format | Requirements |
| --- | --- |
| `.csv` or `.csv.gz` | One column named `ecg_mv`; sampling rate entered separately |
| `.npy` | One numeric ECG vector in millivolts; sampling rate entered separately |
| `.edf` or `.bdf` | Signal rate and physical units read from the file |
| `.zip` | One WFDB header and its root-level signal files |

For multi-channel EDF, BDF, or WFDB records, the service selects a uniquely labelled
ECG or EKG channel. A label or zero-based index can be supplied when automatic
selection is ambiguous.

Consumer wearable exports, pediatric recordings, partial-night snippets, and files
without a documented ECG channel are outside the supported input contract.

## Architecture

```text
Browser
  |
  | GitHub Pages
  v
Static frontend
  |
  | restricted CORS, Turnstile, rate limit
  v
Cloudflare Worker
  |
  | private Workers VPC binding
  v
Authenticated Cloudflare Tunnel
  |
  | loopback-only origin
  v
FastAPI container on the laptop
  |
  v
WFDB processing -> RR-CNN ONNX inference -> nightly prediction
```

The Worker removes identifying request headers, validates the browser origin, limits
uploads to three per hashed IP per hour, and adds the private API token. FastAPI is
bound to `127.0.0.1:8000`; port 8000 must never be exposed directly to the internet.

## Run on the configured laptop

SomniSignal starts only when requested. Nothing is installed as an automatic Windows
startup task.

From Windows PowerShell in the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-ml-server.ps1
```

The launcher starts Ubuntu in WSL, Docker, the API container, and the authenticated
tunnel. On first use it creates a random bearer token in the ignored `.env` file.

Local endpoints:

| Service | Address |
| --- | --- |
| Web application | `http://localhost:8000/` |
| API overview | `http://localhost:8000/api` |
| Health check | `http://localhost:8000/health` |
| OpenAPI documentation | `http://localhost:8000/docs` |

Stop the container and tunnel with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-ml-server.ps1
```

Docker Compose can also be run directly from the repository root:

```bash
docker compose --env-file .env -f deploy/compose.yaml up --build -d
```

## Test with a research record

Use an adult ECG record that you are authorized to analyze. Remove names, record
numbers, timestamps, and other identifying fields before upload. The web interface
accepts a file, sampling rate when required, and an optional ECG channel. It shows
progress while the asynchronous job is queued and processed.

A six-hour synthetic file can be created with:

```bash
python scripts/create-synthetic-ecg.py --force
```

The generated file is written to `sample-data/synthetic-ecg-6h-100hz.csv.gz`.
Instructions for preparing PhysioNet test records are in
[`sample-data/README.md`](sample-data/README.md).

## API

The laptop API requires `Authorization: Bearer <token>` on every `/v1` route. The
token belongs only in `.env` and the Worker secret store. It must never be added to
frontend code.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/v1/research-predictions` | Submit an authorized adult ECG record for research analysis |
| `POST` | `/v1/demo-predictions` | Start an allowlisted PhysioNet demonstration |
| `POST` | `/v1/predictions` | Reserved endpoint outside the public research deployment |
| `GET` | `/v1/predictions/{job_id}` | Poll queued, running, completed, or failed state |
| `DELETE` | `/v1/predictions/{job_id}` | Cancel a job and delete its temporary state |

The browser-facing Worker exposes only the research flow, health status, polling,
and deletion. When the laptop is offline it returns a temporary-offline response;
it never substitutes a cached prediction.

## Training

Download the 35 annotated learning records and exclude duplicate `c06`:

```bash
docker build -f deploy/docker/train.Dockerfile -t somnisignal-trainer .
docker run --rm -v "$PWD/training/data:/workspace/training/data" somnisignal-trainer training.download_dataset --include-qrs
```

Train the feature-based reference model:

```bash
docker run --rm \
  -v "$PWD/training/data:/workspace/training/data" \
  -v "$PWD/artifacts:/workspace/artifacts" \
  somnisignal-trainer training.train
```

Train and export the RR-CNN candidate:

```bash
docker build -f deploy/docker/cnn.Dockerfile -t somnisignal-cnn .
docker run --rm --cpus 2 --memory 2g \
  -v "$PWD/training/data:/workspace/training/data:ro" \
  -v "$PWD/training/cache:/workspace/training/cache" \
  -v "$PWD/artifacts:/workspace/artifacts" \
  somnisignal-cnn training.rr_cnn
```

Training asserts that no recording identifier appears on both sides of a validation
fold. Exported metadata records features, thresholds, grouped metrics, calibration,
dataset citation, training commit, and SHA-256 hashes.

## Tests

The Docker test image installs the `test` dependency group declared in
`pyproject.toml` and creates a deterministic development artifact before running
the suite.

```bash
docker build -f deploy/docker/test.Dockerfile -t somnisignal-tests .
docker run --rm somnisignal-tests
```

For a local Python environment:

```bash
python -m venv .venv
python -m pip install -e ".[test]"
python -m pytest
```

The tests cover signal parsing, QRS and RR processing, nightly aggregation, model
loading, grouped-fold isolation, job expiry and cancellation, authentication,
consent, concurrency, upload validation, and API behavior.

## Repository layout

```text
.github/workflows/    GitHub Pages deployment
artifacts/            Versioned model files, metadata, and evaluation outputs
backend/app/          FastAPI service, inference, jobs, validation, and security
deploy/               Docker Compose and image definitions
docs/                 Model card and release criteria
frontend/             Dependency-free GitHub Pages interface
sample-data/          Local test-record documentation and generated test files
scripts/              Manual Windows launcher and setup utilities
tests/                API, model, signal, job, and training tests
training/             Dataset tools, baselines, CNN training, export, and benchmark code
worker/               Cloudflare Worker proxy and rate limiter
pyproject.toml         Python package metadata and dependency groups
```

The root is reserved for repository-wide files such as the README, license,
security policy, environment example, and Python project definition. Deployment
files and model documentation live with their related code.

## Privacy and release status

Raw uploads are processed in temporary storage and deleted after preprocessing,
failure, timeout, or cancellation. Results remain in memory for 15 minutes. The
application does not provide accounts, history, advertising, or third-party
analytics, and application logs exclude filenames, ECG values, tokens, request
bodies, IP addresses, and individual predictions.

The public interface asks users to confirm that they have permission to analyze the
ECG data and have removed identifying fields. Diagnostic and clinical deployment
remain outside the current scope until the remaining privacy, regulatory, clinical,
security, and independent-review requirements in
[the release gates](docs/RELEASE_GATES.md) are completed.

## Known limitations

- Adult use only; the training cohort does not support pediatric predictions.
- ECG-derived rhythm variation is a surrogate for respiratory disturbance.
- The PhysioNet cohort is small, old, and demographically limited.
- Arrhythmias, medication, autonomic state, hardware, and noise can affect results.
- Lower risk does not rule out obstructive or central sleep apnea.
- The reported validation is not an independent clinical validation.

## Data and clinical references

- [PhysioNet Apnea-ECG Database](https://physionet.org/content/apnea-ecg/1.0.0/)
- [AASM clinical guideline for diagnostic testing](https://aasm.org/resources/clinicalguidelines/diagnostic-testing-osa.pdf)
- [FDA examples of regulated device software](https://www.fda.gov/medical-devices/device-software-functions-including-mobile-medical-applications/examples-device-software-functions-fda-regulates)
- [FTC Mobile Health Apps Interactive Tool](https://www.ftc.gov/business-guidance/resources/mobile-health-apps-interactive-tool)

## Author

Developed by [S M Asif Hossain](https://www.linkedin.com/in/smasifhossain).

## License

SomniSignal is available under the [MIT License](LICENSE).
