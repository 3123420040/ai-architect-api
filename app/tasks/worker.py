from __future__ import annotations

from celery import Celery

from app.core.config import settings


celery_app = Celery(
    "kts-blackbirdzzzz-art",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
)


@celery_app.task(name="system.ping")
def ping_task(payload: dict | None = None) -> dict:
    return {
        "status": "completed",
        "payload": payload or {},
        "worker": "kts-blackbirdzzzz-art",
    }


def queue_ping(payload: dict | None = None):
    return ping_task.delay(payload or {})


from app.tasks import presentation_3d as _presentation_3d_tasks  # noqa: E402,F401
from app.tasks import professional_deliverables as _professional_deliverables_tasks  # noqa: E402,F401
