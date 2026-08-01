from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    api_token: str
    public_uploads_enabled: bool
    regulatory_review_complete: bool
    local_ui_enabled: bool
    model_path: Path
    model_metadata_path: Path
    demo_inputs_path: Path
    job_dir: Path
    max_upload_bytes: int = 25 * 1024 * 1024
    job_ttl_seconds: int = 15 * 60
    minimum_duration_hours: float = 6.0
    maximum_duration_hours: float = 12.0
    minimum_sample_rate_hz: int = 80
    maximum_sample_rate_hz: int = 250

    @property
    def public_release_allowed(self) -> bool:
        return self.public_uploads_enabled and self.regulatory_review_complete


def _as_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_settings() -> Settings:
    artifact_dir = Path(os.getenv("ARTIFACT_DIR", "/app/artifacts"))
    cnn_dir = artifact_dir / "candidates"
    return Settings(
        api_token=os.getenv("ML_API_TOKEN", ""),
        public_uploads_enabled=_as_bool("PUBLIC_UPLOADS_ENABLED"),
        regulatory_review_complete=_as_bool("REGULATORY_REVIEW_COMPLETE"),
        local_ui_enabled=_as_bool("LOCAL_UI_ENABLED"),
        model_path=Path(os.getenv("MODEL_PATH", str(cnn_dir / "rr_cnn.onnx"))),
        model_metadata_path=Path(
            os.getenv("MODEL_METADATA_PATH", str(cnn_dir / "rr_cnn_metadata.json"))
        ),
        demo_inputs_path=Path(
            os.getenv("DEMO_INPUTS_PATH", str(cnn_dir / "demo_rr_sequences.npz"))
        ),
        job_dir=Path(os.getenv("JOB_DIR", "/tmp/ml-jobs")),
    )
