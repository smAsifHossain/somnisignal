# SomniSignal: laptop-hosted sleep-apnea ECG research prototype

An adult-only, non-diagnostic screening demonstration built with FastAPI, a
compact RR-CNN, Docker, a static GitHub Pages frontend, and a Cloudflare Worker
proxy. The laptop API is bound only to `127.0.0.1:8000` and public patient uploads
are disabled unless both the model and external review gates pass.

SomniSignal was developed by
[S M Asif Hossain](https://www.linkedin.com/in/smasifhossain) and is released
under the [MIT License](LICENSE).

> This software cannot diagnose or rule out sleep apnea. A qualified clinician
> may recommend polysomnography (PSG) or a technically adequate home sleep-apnea
> test (HSAT).

## Start manually on this laptop

Run this one line in Windows PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\smasi\Documents\Converting PC to ML Server\scripts\start-ml-server.ps1"
```

The launcher starts WSL, Docker, one CPU-only container, and—once configured—the
authenticated Cloudflare Tunnel. It checks <http://localhost:8000/health> and
creates a random bearer token in the git-ignored `.env` file on first use. Nothing
is registered to start at Windows sign-in.

Useful local URLs:

- Webapp: <http://localhost:8000/>
- API overview: <http://localhost:8000/api>
- Health: <http://localhost:8000/health>
- OpenAPI docs: <http://localhost:8000/docs>

### Test a local file safely

The localhost webapp includes a **local test file upload** panel. It accepts only
synthetic or public, de-identified test data and does not unlock the public patient
upload endpoint. Supported inputs are:

- `.csv` or `.csv.gz` with exactly one `ecg_mv` column; sampling rate required.
- `.npy` containing one numeric ECG vector in millivolts; sampling rate required.
- `.edf` or `.bdf`; sampling rate and V/mV/uV units are read from the file.
- `.zip` containing one WFDB `.hea` file and its root-level `.dat` signal files.

For multi-channel EDF/BDF or WFDB files, SomniSignal selects a uniquely labelled
ECG/EKG channel. The optional channel field accepts an exact channel label or a
zero-based channel index when automatic selection is ambiguous.

A ready-to-use six-hour synthetic ECG can be generated with:

```bash
python3 scripts/create-synthetic-ecg.py --force
```

Then select `sample-data/synthetic-ecg-6h-100hz.csv.gz` in the webapp and keep the
sampling rate at `100 Hz`.

Stop the service and tunnel:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\smasi\Documents\Converting PC to ML Server\scripts\stop-ml-server.ps1"
```

## Model and safety state

The production API loads the CPU-only compact RR-CNN from
`artifacts/candidates/rr_cnn.onnx`. It analyzes five-minute RR sequences sampled
at 4 Hz and applies the stored Platt calibration. The older logistic-regression
artifact is retained only as a reproducibility baseline.

The CNN is deployed for adult, de-identified research demonstrations. Its
patient-facing release gate remains false, so it cannot unlock public patient
uploads.

Real uploads require all three conditions:

1. Trained metadata has `release_gate_passed=true`.
2. `.env` has `PUBLIC_UPLOADS_ENABLED=true`.
3. `.env` has `REGULATORY_REVIEW_COMPLETE=true`.

Do not change the last two flags until every item in
[`RELEASE_GATES.md`](RELEASE_GATES.md) is independently verified.

## API

All `/v1/*` endpoints require `Authorization: Bearer <ML_API_TOKEN>`.

- `POST /v1/demo-predictions` — start an allowlisted public demo.
- `POST /v1/research-predictions` — analyze a confirmed adult,
  de-identified research/test record; intended only for the protected Worker.
- `POST /v1/predictions` — gated multipart `.csv.gz` upload.
- `GET /v1/predictions/{job_id}` — poll queued/running/completed/failed state.
- `DELETE /v1/predictions/{job_id}` — cancel and delete temporary state.

All inputs must resolve to one ECG waveform in millivolts. No names, dates,
timestamps, or identifiers are allowed. Accepted recordings are 6–12 hours at
80–250 Hz and uploads are capped at 25 MB. Only one inference job runs at a time;
results expire after 15 minutes.

Example demo request:

```powershell
$token = ((Get-Content .env | Select-String '^ML_API_TOKEN=').Line -split '=',2)[1]
$headers = @{ Authorization = "Bearer $token" }
$body = @{ record_id='c01'; adult_confirmed=$true; research_consent=$true } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/v1/demo-predictions -Headers $headers -ContentType application/json -Body $body
```

## Train with PhysioNet

The dataset downloader fetches the 35 learning records and excludes duplicate
`c06`. Each recording is a patient group; an assertion fails training if a record
ever appears on both sides of a fold.

```bash
docker build -f Dockerfile.train -t sleep-apnea-trainer .
docker run --rm -v "$PWD/training/data:/workspace/training/data" sleep-apnea-trainer training.download_dataset --include-qrs
docker run --rm -v "$PWD/training/data:/workspace/training/data" -v "$PWD/artifacts:/workspace/artifacts" sleep-apnea-trainer training.train
```

The feature-baseline training command detects QRS complexes with WFDB GQRS. Add
`--use-provided-qrs` only for a separately labeled sensitivity analysis. Training
exports `model.joblib`, `model_metadata.json`, demo features, and a generated model
card. The metadata records the artifact hash, exact features, selected model,
threshold, grouped validation metrics, calibration Brier score with bootstrap CI,
dataset citation, and training commit.

### Evaluate the historical RR baseline and compact CNN

The historical comparator is a SciPy reproduction of PhysioNet's published
Hilbert/RR `apdet` stages. It remains a research comparator and is never promoted
solely from its historical reported accuracy:

```bash
docker run --rm \
  -v "$PWD/training/data:/workspace/training/data:ro" \
  -v "$PWD/artifacts:/workspace/artifacts" \
  sleep-apnea-trainer training.evaluate_apdet
```

The deployed compact CNN consumes five-minute RR sequences at 4 Hz. PyTorch is
confined to the training image; the final model is exported to ONNX and production
uses only ONNX Runtime. The default
command performs three repeated five-fold patient-grouped validation runs using
WFDB GQRS-derived intervals:

```bash
docker build -f Dockerfile.cnn -t sleep-apnea-rr-cnn .
docker run --rm --cpus 2 --memory 2g \
  -v "$PWD/training/data:/workspace/training/data:ro" \
  -v "$PWD/training/cache:/workspace/training/cache" \
  -v "$PWD/artifacts:/workspace/artifacts" \
  sleep-apnea-rr-cnn training.rr_cnn
```

Outputs remain under `artifacts/candidates/`. The API loads the finalized CNN for
de-identified research demonstrations. Patient-facing uploads remain blocked until
the complete modeling, external-review, privacy, security, and regulatory gates
pass.

## Test

```bash
docker build -f Dockerfile.test -t sleep-apnea-tests .
docker run --rm sleep-apnea-tests
```

### Laptop benchmark result

The finalized service processed the 8.71-hour PhysioNet `a03` WFDB archive through
the live upload and polling flow in under 60 seconds. The running container used
491.2 MiB after inference under the 768 MiB limit. This is a deployment smoke
benchmark, not a peak-memory measurement or the still-required exact ten-hour
release benchmark.

## Browser and proxy

- `frontend/` is dependency-free static HTML/CSS/JS deployed by
  `.github/workflows/pages.yml`.
- The same frontend is baked into the laptop image at `/ui/`; a loopback-only,
  same-origin demo adapter lets the local webapp run allowlisted public records
  without exposing the private bearer token. It rejects non-local hosts/origins.
- `worker/` is the Cloudflare Worker. It exposes only health, de-identified
  research uploads, and random-ID job polling/deletion. It restricts CORS,
  verifies the Turnstile hostname/action, applies a rolling three-per-hour
  Durable Object limit, strips identifying headers, and adds the private bearer
  token.
- The Worker reaches the laptop through a private Workers VPC binding to the
  authenticated Cloudflare Tunnel; the origin has no public hostname.

Never expose port 8000 directly or put `ML_API_TOKEN` in frontend code. If the
laptop is offline, the proxy returns a generic temporary-offline response and never
uses a cached or fabricated prediction.

## Source and clinical context

- [PhysioNet Apnea-ECG Database](https://physionet.org/content/apnea-ecg/1.0.0/)
- [AASM diagnostic testing guideline](https://aasm.org/resources/clinicalguidelines/diagnostic-testing-osa.pdf)
- [FDA examples of regulated device software](https://www.fda.gov/medical-devices/device-software-functions-including-mobile-medical-applications/examples-device-software-functions-fda-regulates)
- [FTC Mobile Health Apps Interactive Tool](https://www.ftc.gov/business-guidance/resources/mobile-health-apps-interactive-tool)
