from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(OrmModel):
    id: str
    email: EmailStr
    full_name: str
    role: str
    organization_id: str


class AuthTokens(BaseModel):
    access_token: str
    refresh_token: str


class AuthResponse(AuthTokens):
    user: UserOut


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=2)
    organization_name: str = Field(min_length=2)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2)
    client_name: str | None = None
    client_phone: str | None = None
    kts_user_id: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    client_name: str | None = None
    client_phone: str | None = None
    status: str | None = None


class ProjectSummary(OrmModel):
    id: str
    name: str
    client_name: str | None = None
    client_phone: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class Pagination(BaseModel):
    page: int
    per_page: int
    total: int
    total_pages: int


class PaginatedProjects(BaseModel):
    data: list[dict[str, Any]]
    pagination: Pagination


class BriefPayload(BaseModel):
    brief_json: dict[str, Any]
    status: str = "draft"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


class ChatResponse(BaseModel):
    session_id: str
    status: str
    response: str
    brief_json: dict[str, Any] | None
    needs_follow_up: bool
    follow_up_topics: list[str] = Field(default_factory=list)
    source: str = "heuristic"
    assistant_payload: dict[str, Any] = Field(default_factory=dict)
    conflicts: list[dict[str, str]] = Field(default_factory=list)
    clarification_state: dict[str, Any] = Field(default_factory=dict)
    brief_contract_state: str = "draft"
    brief_contract_label: str = "Đang làm rõ"
    brief_can_lock: bool = False


class GenerateRequest(BaseModel):
    num_options: int = Field(default=3, ge=1, le=5)


class SelectOptionRequest(BaseModel):
    comment: str | None = None


class AnnotationCreate(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    floor_index: int = 0
    comment: str = Field(min_length=1)


class AnnotationUpdate(BaseModel):
    comment: str | None = None
    is_resolved: bool | None = None


class ReviewAction(BaseModel):
    comment: str | None = None
    reason: str | None = None


class ShareLinkResponse(BaseModel):
    token: str
    url: str
    expires_at: datetime


class FeedbackCreate(BaseModel):
    content: str = Field(min_length=1)


class ExportPackageRequest(BaseModel):
    deliverable_preset: str = Field(default="technical_neutral", min_length=1)
    preview_status: str = Field(default="review", pattern="^(review|degraded_preview)$")


class ExportPackageIssueRequest(BaseModel):
    note: str | None = None


class ExportPackageOut(BaseModel):
    id: str
    version_id: str
    revision_label: str
    status: str
    deliverable_preset: str
    quality_status: str
    quality_report_json: dict[str, Any] = Field(default_factory=dict)
    manifest_url: str | None = None
    export_urls: dict[str, str] = Field(default_factory=dict)
    files_manifest: list[dict[str, Any]] = Field(default_factory=list)
    issue_date: str | None = None
    issued_at: datetime | None = None
    issued_by: str | None = None
    created_by: str | None = None
    is_current: bool = False
    created_at: datetime
    updated_at: datetime


class ExportResponse(BaseModel):
    export_urls: dict[str, str]
    package: ExportPackageOut


class DerivationResponse(BaseModel):
    model_url: str
    render_urls: list[str]


class UploadPresignRequest(BaseModel):
    filename: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    folder: str = Field(default="projects", min_length=1)
    expires_in: int = Field(default=900, ge=60, le=3600)


class UploadPresignResponse(BaseModel):
    object_key: str
    upload_url: str
    download_url: str
    expires_in: int
