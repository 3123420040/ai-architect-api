from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Organization, User
from app.schemas import AuthResponse, LoginRequest, RefreshRequest, RegisterRequest, UserOut
from app.security import create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from app.services.audit import log_action


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> AuthResponse:
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

    organization = Organization(name=payload.organization_name)
    db.add(organization)
    db.flush()

    user = User(
        organization_id=organization.id,
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role="architect",
    )
    db.add(user)
    db.flush()
    log_action(db, "auth.register", user_id=user.id, details={"organization_id": organization.id})
    db.commit()

    return AuthResponse(
        user=UserOut.model_validate(user),
        access_token=create_access_token(user.id, user.role),
        refresh_token=create_refresh_token(user.id, user.role),
    )


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    log_action(db, "auth.login", user_id=user.id)
    db.commit()

    return AuthResponse(
        user=UserOut.model_validate(user),
        access_token=create_access_token(user.id, user.role),
        refresh_token=create_refresh_token(user.id, user.role),
    )


@router.post("/refresh")
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> dict:
    try:
        token = decode_token(payload.refresh_token, expected_type="refresh")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token") from exc

    user = db.get(User, token["sub"])
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return {"access_token": create_access_token(user.id, user.role)}
