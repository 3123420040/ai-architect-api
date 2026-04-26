from __future__ import annotations

from pathlib import Path

from app.services.professional_deliverables.demo import generate_golden_bundle
from app.tasks.worker import celery_app


@celery_app.task(name="professional_deliverables.sprint1_golden_bundle")
def run_sprint1_golden_bundle_task(output_root: str | None = None, require_dwg: bool = True) -> dict:
    result = generate_golden_bundle(Path(output_root) if output_root else None, require_dwg=require_dwg)
    return result.as_dict()

