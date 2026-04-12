from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class Organization(TimestampMixin, Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    plan: Mapped[str] = mapped_column(String(50), default="free")
    generation_budget_total: Mapped[int] = mapped_column(Integer, default=100)
    generation_budget_used: Mapped[int] = mapped_column(Integer, default=0)

    users: Mapped[list["User"]] = relationship(back_populates="organization")
    projects: Mapped[list["Project"]] = relationship(back_populates="organization")


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="user")
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    organization: Mapped["Organization"] = relationship(back_populates="users")


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    client_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    kts_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(50), default="new", index=True)
    brief_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    brief_status: Mapped[str] = mapped_column(String(50), default="draft")
    style_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="projects")
    versions: Mapped[list["DesignVersion"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    packages: Mapped[list["ExportPackage"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    chat_messages: Mapped[list["ChatMessage"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class DesignVersion(TimestampMixin, Base):
    __tablename__ = "design_versions"
    __table_args__ = (UniqueConstraint("project_id", "version_number", name="uq_project_version_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    parent_version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("design_versions.id"), nullable=True, index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(50), default="draft", index=True)
    option_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    option_description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    brief_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    geometry_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    floor_plan_urls: Mapped[list] = mapped_column(JSON, default=list)
    resolved_style_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    render_urls: Mapped[list] = mapped_column(JSON, default=list)
    model_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    export_urls: Mapped[dict] = mapped_column(JSON, default=dict)
    generation_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="versions")
    packages: Mapped[list["ExportPackage"]] = relationship(back_populates="version", cascade="all, delete-orphan")
    annotations: Mapped[list["Annotation"]] = relationship(back_populates="version", cascade="all, delete-orphan")
    feedback_items: Mapped[list["Feedback"]] = relationship(back_populates="version", cascade="all, delete-orphan")


class ExportPackage(TimestampMixin, Base):
    __tablename__ = "export_packages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[str] = mapped_column(String(36), ForeignKey("design_versions.id", ondelete="CASCADE"), index=True)
    revision_label: Mapped[str] = mapped_column(String(10), default="A")
    status: Mapped[str] = mapped_column(String(50), default="draft", index=True)
    deliverable_preset: Mapped[str] = mapped_column(String(50), default="technical_neutral")
    quality_status: Mapped[str] = mapped_column(String(20), default="pending")
    quality_report_json: Mapped[dict] = mapped_column(JSON, default=dict)
    manifest_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    export_urls: Mapped[dict] = mapped_column(JSON, default=dict)
    files_manifest: Mapped[list] = mapped_column(JSON, default=list)
    issue_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    project: Mapped["Project"] = relationship(back_populates="packages")
    version: Mapped["DesignVersion"] = relationship(back_populates="packages")


class Annotation(TimestampMixin, Base):
    __tablename__ = "annotations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    version_id: Mapped[str] = mapped_column(String(36), ForeignKey("design_versions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    x: Mapped[float]
    y: Mapped[float]
    floor_index: Mapped[int] = mapped_column(Integer, default=0)
    comment: Mapped[str] = mapped_column(Text)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)

    version: Mapped["DesignVersion"] = relationship(back_populates="annotations")


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    version_id: Mapped[str] = mapped_column(String(36), ForeignKey("design_versions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    structured_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    version: Mapped["DesignVersion"] = relationship(back_populates="feedback_items")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    message_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)

    project: Mapped["Project"] = relationship(back_populates="chat_messages")


class ShareLink(Base):
    __tablename__ = "share_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"))
    token: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class HandoffBundle(Base):
    __tablename__ = "handoff_bundles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"))
    version_id: Mapped[str] = mapped_column(String(36), ForeignKey("design_versions.id"))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    files_manifest: Mapped[list] = mapped_column(JSON, default=list)
    readiness_label: Mapped[str] = mapped_column(String(50), default="handoff_ready")
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text)
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id"), nullable=True)
    version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("design_versions.id"), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id"), nullable=True)
    version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("design_versions.id"), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
