from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import require_roles
from app.schemas import UploadPresignRequest, UploadPresignResponse
from app.services.uploads import UploadsNotConfiguredError, create_presigned_upload


router = APIRouter(
    prefix="/uploads",
    tags=["uploads"],
    dependencies=[Depends(require_roles("architect", "admin"))],
)


@router.post("/presign", response_model=UploadPresignResponse, status_code=status.HTTP_201_CREATED)
def create_upload_presign(payload: UploadPresignRequest) -> UploadPresignResponse:
    try:
        result = create_presigned_upload(
            folder=payload.folder,
            filename=payload.filename,
            content_type=payload.content_type,
            expires_in=payload.expires_in,
        )
    except UploadsNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return UploadPresignResponse(**result)
