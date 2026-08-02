from __future__ import annotations

import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.ecg_inputs import (
    InputValidationError,
    SAMPLING_RATE_REQUIRED_SUFFIXES,
    detect_upload_suffix,
)
from app.jobs import BusyError, JobManager
from app.middleware import RequestSizeLimitMiddleware
from app.model import ModelBundle, load_model
from app.schemas import (
    DemoPredictionRequest,
    HealthResponse,
    JobAccepted,
    JobResponse,
    JobState,
)
from app.security import require_api_token


def _load_runtime(settings: Settings) -> tuple[ModelBundle | None, JobManager | None]:
    if len(settings.api_token) < 32:
        return None, None
    try:
        model = load_model(settings.model_path, settings.model_metadata_path)
        manager = JobManager(settings, model, settings.demo_inputs_path)
        return model, manager
    except (FileNotFoundError, KeyError, RuntimeError, ValueError):
        return None, None


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    model, manager = _load_runtime(settings)
    app.state.settings = settings
    app.state.model = model
    app.state.jobs = manager
    yield
    if manager is not None:
        manager.close()


app = FastAPI(
    title="SomniSignal Research Screening API",
    description=(
        "Adult-only experimental ECG screening. This service does not diagnose sleep apnea "
        "and cannot replace polysomnography or home sleep-apnea testing."
    ),
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(RequestSizeLimitMiddleware, max_bytes=25 * 1024 * 1024 + 128 * 1024)
frontend_directory = Path(__file__).resolve().parents[2] / "frontend"
if frontend_directory.exists():
    app.mount("/ui", StaticFiles(directory=frontend_directory, html=True), name="ui")


@app.middleware("http")
async def add_private_api_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/health" or path == "/api" or path.startswith(("/v1/", "/local/v1/")):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _manager(request: Request) -> JobManager:
    manager = request.app.state.jobs
    if manager is None:
        raise HTTPException(status_code=503, detail="The screening model is unavailable.")
    return manager


def _accepted(job, settings: Settings) -> JobAccepted:
    return JobAccepted(
        job_id=job.job_id,
        status=JobState.queued,
        status_url=f"/v1/predictions/{job.job_id}",
        expires_in_seconds=settings.job_ttl_seconds,
    )


def _validate_upload_request(
    *,
    ecg_file: UploadFile,
    sampling_rate_hz: int | None,
    adult_confirmed: bool,
    research_consent: bool,
    settings: Settings,
) -> None:
    if not adult_confirmed or not research_consent:
        raise HTTPException(
            status_code=422,
            detail="Adult confirmation and research consent are required.",
        )
    try:
        suffix = detect_upload_suffix(ecg_file.filename or "")
    except InputValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if suffix in SAMPLING_RATE_REQUIRED_SUFFIXES and sampling_rate_hz is None:
        raise HTTPException(
            status_code=422,
            detail="Sampling rate is required for CSV and NPY uploads.",
        )
    if sampling_rate_hz is not None and not (
        settings.minimum_sample_rate_hz
        <= sampling_rate_hz
        <= settings.maximum_sample_rate_hz
    ):
        raise HTTPException(
            status_code=422, detail="Sampling rate must be between 80 and 250 Hz."
        )


async def _store_and_submit_upload(
    *,
    ecg_file: UploadFile,
    sampling_rate_hz: int | None,
    ecg_channel: str | None,
    settings: Settings,
    manager: JobManager,
    enforce_release_gate: bool = True,
):
    settings.job_dir.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    suffix = detect_upload_suffix(ecg_file.filename or "")
    try:
        with tempfile.NamedTemporaryFile(
            prefix="ecg-", suffix=suffix, dir=settings.job_dir, delete=False
        ) as destination:
            temporary_path = Path(destination.name)
            total = 0
            while chunk := await ecg_file.read(1024 * 1024):
                total += len(chunk)
                if total > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413, detail="Upload exceeds the 25 MB limit."
                    )
                destination.write(chunk)
        if total == 0:
            raise HTTPException(status_code=422, detail="Upload is empty.")
        job = manager.submit_upload(
            temporary_path,
            sample_rate_hz=sampling_rate_hz,
            ecg_channel=ecg_channel,
            enforce_release_gate=enforce_release_gate,
        )
        temporary_path = None
        return job
    except BusyError as exc:
        raise HTTPException(
            status_code=429,
            detail="The screening service is processing another recording.",
            headers={"Retry-After": "30"},
        ) from exc
    finally:
        await ecg_file.close()
        if temporary_path:
            temporary_path.unlink(missing_ok=True)


@app.get("/", response_model=None)
def root() -> RedirectResponse | dict[str, str]:
    if frontend_directory.exists():
        return RedirectResponse(url="/ui/", status_code=307)
    return {
        "service": "SomniSignal Research Screening API",
        "purpose": "adult research screening only; not diagnosis",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/api")
def api_overview() -> dict[str, str]:
    return {
        "service": "SomniSignal Research Screening API",
        "purpose": "adult research screening only; not diagnosis",
        "docs": "/docs",
        "health": "/health",
    }


def _require_local_ui(request: Request) -> None:
    settings: Settings = request.app.state.settings
    allowed_origins = {"http://localhost:8000", "http://127.0.0.1:8000"}
    allowed_hosts = {"localhost:8000", "127.0.0.1:8000"}
    host = request.headers.get("host", "").lower()
    origin = request.headers.get("origin")
    if not settings.local_ui_enabled or host not in allowed_hosts:
        raise HTTPException(status_code=404, detail="Not found.")

    if origin is not None:
        if origin not in allowed_origins:
            raise HTTPException(status_code=404, detail="Not found.")
        return

    # Browsers normally omit Origin on same-origin GET polling requests. Accept
    # those read-only requests while rejecting cross-site browser traffic.
    if request.method not in {"GET", "HEAD"}:
        raise HTTPException(status_code=404, detail="Not found.")
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site and fetch_site not in {"same-origin", "none"}:
        raise HTTPException(status_code=404, detail="Not found.")
    referer = request.headers.get("referer")
    if referer and not any(
        referer == allowed or referer.startswith(f"{allowed}/")
        for allowed in allowed_origins
    ):
        raise HTTPException(status_code=404, detail="Not found.")


@app.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    model = request.app.state.model
    settings = request.app.state.settings
    return HealthResponse(
        status="healthy" if model is not None else "degraded",
        model_ready=model is not None,
        model_version=model.version if model else None,
        model_release_gate_passed=model.release_gate_passed if model else False,
        public_uploads_enabled=bool(
            model and model.release_gate_passed and settings.public_release_allowed
        ),
        research_demo_uploads_enabled=bool(
            model and settings.research_demo_uploads_enabled
        ),
    )


@app.post(
    "/v1/predictions",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_api_token)],
)
async def create_prediction(
    request: Request,
    ecg_file: UploadFile = File(...),
    sampling_rate_hz: int | None = Form(None),
    ecg_channel: str | None = Form(None),
    adult_confirmed: bool = Form(...),
    research_consent: bool = Form(...),
) -> JobAccepted:
    settings: Settings = request.app.state.settings
    model: ModelBundle | None = request.app.state.model
    manager = _manager(request)

    if not model.release_gate_passed or not settings.public_release_allowed:
        raise HTTPException(
            status_code=403,
            detail="Public uploads are disabled pending model, privacy, and regulatory review.",
        )
    _validate_upload_request(
        ecg_file=ecg_file,
        sampling_rate_hz=sampling_rate_hz,
        adult_confirmed=adult_confirmed,
        research_consent=research_consent,
        settings=settings,
    )
    job = await _store_and_submit_upload(
        ecg_file=ecg_file,
        sampling_rate_hz=sampling_rate_hz,
        ecg_channel=ecg_channel,
        settings=settings,
        manager=manager,
    )
    return _accepted(job, settings)


@app.post(
    "/v1/research-predictions",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_api_token)],
)
async def create_research_prediction(
    request: Request,
    ecg_file: UploadFile = File(...),
    sampling_rate_hz: int | None = Form(None),
    ecg_channel: str | None = Form(None),
    adult_confirmed: bool = Form(...),
    research_consent: bool = Form(...),
    non_patient_test_data_confirmed: bool = Form(...),
) -> JobAccepted:
    """Analyze only an adult, de-identified public research/test ECG.

    This route is deliberately separate from the gated patient-upload route. It
    is reachable only through the authenticated proxy and never claims clinical
    or patient-facing release status.
    """
    settings: Settings = request.app.state.settings
    if not settings.research_demo_uploads_enabled:
        raise HTTPException(
            status_code=403,
            detail="Research-data uploads are disabled.",
        )
    if not non_patient_test_data_confirmed:
        raise HTTPException(
            status_code=422,
            detail="Confirm that this file is a de-identified research or test record.",
        )
    _validate_upload_request(
        ecg_file=ecg_file,
        sampling_rate_hz=sampling_rate_hz,
        adult_confirmed=adult_confirmed,
        research_consent=research_consent,
        settings=settings,
    )
    job = await _store_and_submit_upload(
        ecg_file=ecg_file,
        sampling_rate_hz=sampling_rate_hz,
        ecg_channel=ecg_channel,
        settings=settings,
        manager=_manager(request),
        enforce_release_gate=False,
    )
    return _accepted(job, settings)


@app.post(
    "/local/v1/test-predictions",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_local_test_prediction(
    request: Request,
    ecg_file: UploadFile = File(...),
    sampling_rate_hz: int | None = Form(None),
    ecg_channel: str | None = Form(None),
    adult_confirmed: bool = Form(...),
    research_consent: bool = Form(...),
    non_patient_test_data_confirmed: bool = Form(...),
) -> JobAccepted:
    _require_local_ui(request)
    if not non_patient_test_data_confirmed:
        raise HTTPException(
            status_code=422,
            detail="Confirm that this file contains only synthetic or public test data.",
        )
    settings: Settings = request.app.state.settings
    _validate_upload_request(
        ecg_file=ecg_file,
        sampling_rate_hz=sampling_rate_hz,
        adult_confirmed=adult_confirmed,
        research_consent=research_consent,
        settings=settings,
    )
    job = await _store_and_submit_upload(
        ecg_file=ecg_file,
        sampling_rate_hz=sampling_rate_hz,
        ecg_channel=ecg_channel,
        settings=settings,
        manager=_manager(request),
        enforce_release_gate=False,
    )
    return _accepted(job, settings)


@app.post(
    "/v1/demo-predictions",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_api_token)],
)
def create_demo_prediction(
    payload: DemoPredictionRequest,
    request: Request,
) -> JobAccepted:
    if not payload.adult_confirmed or not payload.research_consent:
        raise HTTPException(status_code=422, detail="Adult confirmation and research consent are required.")
    try:
        job = _manager(request).submit_demo(payload.record_id)
    except BusyError as exc:
        raise HTTPException(
            status_code=429,
            detail="The screening service is processing another recording.",
            headers={"Retry-After": "30"},
        ) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Demo record not found.") from exc
    return _accepted(job, request.app.state.settings)


@app.post(
    "/local/v1/demo-predictions",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_local_demo_prediction(
    payload: DemoPredictionRequest,
    request: Request,
) -> JobAccepted:
    _require_local_ui(request)
    if not payload.adult_confirmed or not payload.research_consent:
        raise HTTPException(
            status_code=422,
            detail="Adult confirmation and research consent are required.",
        )
    try:
        job = _manager(request).submit_demo(
            payload.record_id, enforce_release_gate=False
        )
    except BusyError as exc:
        raise HTTPException(
            status_code=429,
            detail="The screening service is processing another recording.",
            headers={"Retry-After": "30"},
        ) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Demo record not found.") from exc
    return _accepted(job, request.app.state.settings)


@app.get(
    "/v1/predictions/{job_id}",
    response_model=JobResponse,
    dependencies=[Depends(require_api_token)],
)
def get_prediction(job_id: str, request: Request) -> JobResponse:
    if len(job_id) != 32 or any(character not in "0123456789abcdef" for character in job_id):
        raise HTTPException(status_code=404, detail="Screening job not found.")
    job = _manager(request).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Screening job not found or expired.")
    return job


@app.get("/local/v1/predictions/{job_id}", response_model=JobResponse)
def get_local_prediction(job_id: str, request: Request) -> JobResponse:
    _require_local_ui(request)
    if len(job_id) != 32 or any(
        character not in "0123456789abcdef" for character in job_id
    ):
        raise HTTPException(status_code=404, detail="Screening job not found.")
    job = _manager(request).get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404, detail="Screening job not found or expired."
        )
    return job


@app.delete(
    "/local/v1/predictions/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_local_prediction(job_id: str, request: Request) -> Response:
    _require_local_ui(request)
    if len(job_id) != 32 or any(
        character not in "0123456789abcdef" for character in job_id
    ):
        raise HTTPException(status_code=404, detail="Screening job not found.")
    if not _manager(request).delete(job_id):
        raise HTTPException(
            status_code=404, detail="Screening job not found or expired."
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.delete(
    "/v1/predictions/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_api_token)],
)
def delete_prediction(job_id: str, request: Request) -> Response:
    if not _manager(request).delete(job_id):
        raise HTTPException(status_code=404, detail="Screening job not found or expired.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
