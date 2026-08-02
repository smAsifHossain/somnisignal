from __future__ import annotations

import os
import queue
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from app.config import Settings
from app.model import ModelBundle, aggregate_night
from app.schemas import JobResponse, JobState, ScreeningResult
from app.signal_processing import InputValidationError, analyze_ecg_file


@dataclass
class _Job:
    job_id: str
    created_at: datetime
    expires_at: datetime
    source: str
    sample_rate_hz: int | None = None
    ecg_channel: str | None = None
    upload_path: Path | None = None
    demo_record_id: str | None = None
    enforce_release_gate: bool = True
    status: JobState = JobState.queued
    result: ScreeningResult | None = None
    error: str | None = None
    cancelled: bool = False


class BusyError(RuntimeError):
    pass


class JobManager:
    def __init__(self, settings: Settings, model: ModelBundle, demo_inputs: Path):
        self.settings = settings
        self.model = model
        self.demo_inputs = np.load(demo_inputs, allow_pickle=False)
        self._jobs: dict[str, _Job] = {}
        self._active_job_id: str | None = None
        self._lock = threading.RLock()
        self._queue: queue.Queue[str] = queue.Queue(maxsize=1)
        settings.job_dir.mkdir(parents=True, exist_ok=True)
        self._worker = threading.Thread(target=self._run, daemon=True, name="screening-worker")
        self._worker.start()
        self._stop = threading.Event()
        self._sweeper = threading.Thread(
            target=self._sweep, daemon=True, name="screening-expiry"
        )
        self._sweeper.start()

    def close(self) -> None:
        self._stop.set()
        self._sweeper.join(timeout=2)

    def _sweep(self) -> None:
        while not self._stop.wait(timeout=30):
            with self._lock:
                self._cleanup_expired()

    def _cleanup_expired(self) -> None:
        now = datetime.now(UTC)
        expired = [job_id for job_id, job in self._jobs.items() if job.expires_at <= now]
        for job_id in expired:
            job = self._jobs.pop(job_id)
            job.cancelled = True
            if job.upload_path:
                job.upload_path.unlink(missing_ok=True)
            if self._active_job_id == job_id and job.status != JobState.running:
                self._active_job_id = None

    def _reserve(self, source: str, *, enforce_release_gate: bool) -> _Job:
        with self._lock:
            self._cleanup_expired()
            if self._active_job_id is not None:
                raise BusyError("The screening service is processing another recording.")
            now = datetime.now(UTC)
            job = _Job(
                job_id=uuid.uuid4().hex,
                created_at=now,
                expires_at=now + timedelta(seconds=self.settings.job_ttl_seconds),
                source=source,
                enforce_release_gate=enforce_release_gate,
            )
            self._jobs[job.job_id] = job
            self._active_job_id = job.job_id
            return job

    def submit_upload(
        self,
        path: Path,
        sample_rate_hz: int | None,
        ecg_channel: str | None = None,
        enforce_release_gate: bool = True,
    ) -> _Job:
        job = self._reserve("upload", enforce_release_gate=enforce_release_gate)
        job.upload_path = path
        job.sample_rate_hz = sample_rate_hz
        job.ecg_channel = ecg_channel
        self._queue.put_nowait(job.job_id)
        return job

    def submit_demo(self, record_id: str, *, enforce_release_gate: bool = True) -> _Job:
        if record_id not in self.demo_inputs.files:
            raise KeyError(record_id)
        job = self._reserve("demo", enforce_release_gate=enforce_release_gate)
        job.demo_record_id = record_id
        self._queue.put_nowait(job.job_id)
        return job

    def get(self, job_id: str) -> JobResponse | None:
        with self._lock:
            self._cleanup_expired()
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return JobResponse(
                job_id=job.job_id,
                status=job.status,
                created_at=job.created_at,
                expires_at=job.expires_at,
                result=job.result,
                error=job.error,
            )

    def delete(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.pop(job_id, None)
            if job is None:
                return False
            job.cancelled = True
            if job.upload_path:
                job.upload_path.unlink(missing_ok=True)
            if self._active_job_id == job_id and job.status != JobState.running:
                self._active_job_id = None
            return True

    def _run(self) -> None:
        while True:
            job_id = self._queue.get()
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None or job.cancelled:
                    self._active_job_id = None
                    self._queue.task_done()
                    continue
                job.status = JobState.running

            try:
                if job.source == "demo":
                    model_inputs = np.asarray(
                        self.demo_inputs[job.demo_record_id], dtype=float
                    )
                    probabilities = self.model.predict_probabilities(model_inputs)
                    result = aggregate_night(
                        probabilities,
                        threshold=self.model.threshold,
                        model_version=self.model.version,
                        release_gate_passed=(
                            self.model.release_gate_passed
                            if job.enforce_release_gate
                            else True
                        ),
                    )
                else:
                    analysis = analyze_ecg_file(
                        job.upload_path,
                        sample_rate_hz=job.sample_rate_hz,
                        ecg_channel=job.ecg_channel,
                        minimum_hours=self.settings.minimum_duration_hours,
                        maximum_hours=self.settings.maximum_duration_hours,
                        model_input_kind=self.model.input_kind,
                    )
                    job.upload_path.unlink(missing_ok=True)
                    job.upload_path = None
                    if analysis.model_inputs.size:
                        probabilities = self.model.predict_probabilities(
                            analysis.model_inputs
                        )
                    else:
                        probabilities = np.array([], dtype=float)
                    result = aggregate_night(
                        probabilities,
                        threshold=self.model.threshold,
                        model_version=self.model.version,
                        signal_quality=analysis.quality,
                        reasons=analysis.reasons,
                        release_gate_passed=(
                            self.model.release_gate_passed
                            if job.enforce_release_gate
                            else True
                        ),
                    )
                with self._lock:
                    if not job.cancelled and job.job_id in self._jobs:
                        job.result = result
                        job.status = JobState.completed
            except (InputValidationError, ValueError):
                with self._lock:
                    if not job.cancelled and job.job_id in self._jobs:
                        job.status = JobState.failed
                        job.error = "The recording could not be analyzed."
            except Exception:
                with self._lock:
                    if not job.cancelled and job.job_id in self._jobs:
                        job.status = JobState.failed
                        job.error = "Screening failed safely. Please try a validated demo record."
            finally:
                if job.upload_path:
                    try:
                        os.remove(job.upload_path)
                    except FileNotFoundError:
                        pass
                with self._lock:
                    if self._active_job_id == job_id:
                        self._active_job_id = None
                self._queue.task_done()
