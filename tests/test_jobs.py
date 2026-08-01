from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import numpy as np
import pytest

from app.config import Settings
from app.jobs import BusyError, JobManager


class BlockingModel:
    threshold = 0.5
    version = "test"

    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()

    def predict_probabilities(self, features: np.ndarray) -> np.ndarray:
        self.started.set()
        self.release.wait(timeout=2)
        return np.zeros(features.shape[0])


def settings(tmp_path: Path) -> Settings:
    return Settings(
        api_token="x" * 32,
        public_uploads_enabled=False,
        regulatory_review_complete=False,
        local_ui_enabled=False,
        model_path=tmp_path / "unused",
        model_metadata_path=tmp_path / "unused.json",
        demo_inputs_path=tmp_path / "demos.npz",
        job_dir=tmp_path / "jobs",
    )


def test_only_one_active_job_and_ttl_expiry(tmp_path: Path) -> None:
    demos = tmp_path / "demos.npz"
    np.savez_compressed(demos, a01=np.zeros((120, 13)))
    model = BlockingModel()
    manager = JobManager(settings(tmp_path), model, demos)
    try:
        first = manager.submit_demo("a01")
        assert model.started.wait(timeout=1)
        with pytest.raises(BusyError):
            manager.submit_demo("a01")
        model.release.set()
        with manager._lock:
            manager._jobs[first.job_id].expires_at = datetime.now(UTC) - timedelta(seconds=1)
        assert manager.get(first.job_id) is None
    finally:
        model.release.set()
        manager.close()
