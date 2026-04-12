from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import Organization, User


router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("/me")
def get_my_organization(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    organization = db.get(Organization, current_user.organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    return {
        "id": organization.id,
        "name": organization.name,
        "plan": organization.plan,
        "generation_budget_total": organization.generation_budget_total,
        "generation_budget_used": organization.generation_budget_used,
        "current_user_role": current_user.role,
    }
