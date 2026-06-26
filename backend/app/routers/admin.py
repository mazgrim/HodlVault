from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..auth import require_admin, hash_password

router = APIRouter()


@router.get("/users", response_model=List[schemas.UserOut])
def list_users(
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_admin),
):
    return db.query(models.User).order_by(models.User.created_at).all()


@router.patch("/users/{user_id}", response_model=schemas.UserOut)
def update_user(
    user_id: int,
    payload: schemas.AdminUserUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Non puoi modificare te stesso")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.is_admin is not None:
        user.is_admin = payload.is_admin
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Non puoi eliminare te stesso")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    db.delete(user)
    db.commit()


@router.get("/password-requests", response_model=List[schemas.PasswordResetRequestOut])
def list_password_requests(
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_admin),
):
    """Pending in-app 'forgot password' requests, oldest first."""
    reqs = (
        db.query(models.PasswordResetRequest)
        .filter(models.PasswordResetRequest.resolved == False)  # noqa: E712
        .order_by(models.PasswordResetRequest.created_at)
        .all()
    )
    return [
        schemas.PasswordResetRequestOut(
            id=r.id, user_id=r.user_id,
            username=r.user.username if r.user else "?",
            email=r.user.email if r.user else "?",
            created_at=r.created_at,
        )
        for r in reqs
    ]


@router.post("/users/{user_id}/reset-password", status_code=204)
def admin_reset_password(
    user_id: int,
    payload: schemas.AdminPasswordReset,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_admin),
):
    """Admin sets a temporary password for a user and clears their pending requests."""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    user.hashed_password = hash_password(payload.new_password)
    db.query(models.PasswordResetRequest).filter(
        models.PasswordResetRequest.user_id == user_id,
        models.PasswordResetRequest.resolved == False,  # noqa: E712
    ).update({"resolved": True, "resolved_at": datetime.utcnow()})
    db.commit()
