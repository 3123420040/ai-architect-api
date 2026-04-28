from __future__ import annotations

from fastapi import APIRouter
from starlette.responses import StreamingResponse

from app.services.storage import asset_stream_response


router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("/{token}")
def get_asset(token: str) -> StreamingResponse:
    return asset_stream_response(token)
