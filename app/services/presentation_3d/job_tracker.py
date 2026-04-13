from __future__ import annotations

from datetime import datetime, timezone

from app.models import Presentation3DBundle, Presentation3DJob


def mark_job_running(job: Presentation3DJob, *, stage: str, progress_percent: int) -> None:
    job.status = "running"
    job.stage = stage
    job.progress_percent = progress_percent
    if job.started_at is None:
        job.started_at = datetime.now(timezone.utc)


def mark_job_stage(job: Presentation3DJob, *, stage: str, progress_percent: int, bundle: Presentation3DBundle | None = None) -> None:
    mark_job_running(job, stage=stage, progress_percent=progress_percent)
    if bundle:
        bundle.status = "running"


def mark_job_failed(job: Presentation3DJob, *, error_code: str, error_message: str, bundle: Presentation3DBundle) -> None:
    job.status = "failed"
    job.error_code = error_code
    job.error_message = error_message[:1000]
    job.finished_at = datetime.now(timezone.utc)
    bundle.status = "failed"
    bundle.delivery_status = "blocked"


def mark_job_succeeded(job: Presentation3DJob, *, bundle: Presentation3DBundle, stage: str = "approval_ready") -> None:
    job.status = "succeeded"
    job.stage = stage
    job.progress_percent = 100
    job.finished_at = datetime.now(timezone.utc)
    if bundle.status != "failed":
        bundle.status = "awaiting_approval"
