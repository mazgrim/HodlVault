from collections import Counter
from datetime import datetime, timedelta
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas, security
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


# ── Access log / brute-force lockout ──────────────────────────────────────────

@router.get("/login-attempts", response_model=List[schemas.LoginAttemptOut])
def list_login_attempts(
    limit: int = Query(100, ge=1, le=500),
    only_failed: bool = False,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_admin),
):
    """Recent login attempts (newest first) for the admin access log."""
    q = db.query(models.LoginAttempt)
    if only_failed:
        q = q.filter(models.LoginAttempt.success == False)  # noqa: E712
    return q.order_by(models.LoginAttempt.created_at.desc()).limit(limit).all()


@router.get("/security/status", response_model=schemas.SecurityStatus)
def security_status(
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_admin),
):
    """Currently active lockouts (IPs / accounts over the failure threshold in the
    sliding window) plus the configured thresholds."""
    window_start = datetime.utcnow() - timedelta(minutes=security.LOCKOUT_MINUTES)
    failed = (
        db.query(models.LoginAttempt)
        .filter(
            models.LoginAttempt.success == False,  # noqa: E712
            models.LoginAttempt.created_at >= window_start,
        )
        .all()
    )
    by_ip = Counter(a.ip_address for a in failed if a.ip_address)
    by_id = Counter(a.identifier for a in failed if a.identifier)

    locked: List[schemas.LockoutEntry] = []
    for ip, n in by_ip.items():
        if n >= security.MAX_FAILED_ATTEMPTS:
            locked.append(schemas.LockoutEntry(type="ip", value=ip, fail_count=n))
    for ident, n in by_id.items():
        if n >= security.MAX_FAILED_ATTEMPTS:
            locked.append(schemas.LockoutEntry(type="identifier", value=ident, fail_count=n))
    locked.sort(key=lambda e: e.fail_count, reverse=True)

    return schemas.SecurityStatus(
        max_attempts=security.MAX_FAILED_ATTEMPTS,
        lockout_minutes=security.LOCKOUT_MINUTES,
        locked=locked,
    )


@router.post("/security/clear-lockout", status_code=204)
def clear_lockout(
    payload: schemas.ClearLockout,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_admin),
):
    """Lift a lockout by deleting the recent failed attempts for an IP and/or an
    identifier. Lets the admin unblock a legitimate user who locked themselves out."""
    conds = []
    if payload.ip_address:
        conds.append(models.LoginAttempt.ip_address == payload.ip_address.strip())
    if payload.identifier:
        conds.append(models.LoginAttempt.identifier == payload.identifier.strip())
    if not conds:
        raise HTTPException(status_code=400, detail="Specificare ip_address o identifier")
    db.query(models.LoginAttempt).filter(
        models.LoginAttempt.success == False,  # noqa: E712
        or_(*conds),
    ).delete(synchronize_session=False)
    db.commit()
