import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session
from jose import JWTError

from ..database import get_db
from .. import models, schemas
from ..auth import (
    verify_password, hash_password,
    create_access_token, create_refresh_token, decode_token,
    get_current_user, require_write,
)

router = APIRouter()


def _find_user_by_identifier(identifier: str, db: Session):
    """Resolve a user by exact username, then by case-insensitive email."""
    ident = (identifier or "").strip()
    if not ident:
        return None
    user = db.query(models.User).filter(models.User.username == ident).first()
    if not user:
        user = db.query(models.User).filter(func.lower(models.User.email) == ident.lower()).first()
    return user


@router.post("/register", response_model=schemas.UserOut, status_code=201)
def register(user_in: schemas.UserCreate, db: Session = Depends(get_db)):
    registration_open = os.getenv("REGISTRATION_OPEN", "true").lower() == "true"
    existing_users = db.query(models.User).count()

    if not registration_open and existing_users > 0:
        raise HTTPException(status_code=403, detail="Registrazione disabilitata. Contatta l'amministratore.")

    if db.query(models.User).filter(models.User.username == user_in.username).first():
        raise HTTPException(status_code=400, detail="Username già in uso")
    if db.query(models.User).filter(models.User.email == user_in.email).first():
        raise HTTPException(status_code=400, detail="Email già in uso")

    is_first = existing_users == 0
    user = models.User(
        username=user_in.username,
        email=user_in.email,
        hashed_password=hash_password(user_in.password),
        is_admin=is_first,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=schemas.Token)
def login(creds: schemas.UserLogin, db: Session = Depends(get_db)):
    # Accept either the username or the email in the same field.
    user = _find_user_by_identifier(creds.username, db)
    if not user or not verify_password(creds.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Credenziali non valide")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabilitato")

    return schemas.Token(
        access_token=create_access_token({"sub": str(user.id)}),
        refresh_token=create_refresh_token({"sub": str(user.id)}),
    )


@router.post("/refresh", response_model=schemas.Token)
def refresh(body: schemas.TokenRefresh, db: Session = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token)
        if payload.get("type") != "refresh":
            raise JWTError()
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Refresh token non valido")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    return schemas.Token(
        access_token=create_access_token({"sub": str(user.id)}),
        refresh_token=create_refresh_token({"sub": str(user.id)}),
    )


@router.get("/me", response_model=schemas.UserOut)
def me(current_user: models.User = Depends(get_current_user)):
    return current_user


@router.post("/change-password", status_code=204)
def change_password(
    body: schemas.PasswordChange,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_write),
):
    if not verify_password(body.old_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Password attuale non corretta")
    current_user.hashed_password = hash_password(body.new_password)
    # Clear any pending reset requests for this user.
    db.query(models.PasswordResetRequest).filter(
        models.PasswordResetRequest.user_id == current_user.id,
        models.PasswordResetRequest.resolved == False,  # noqa: E712
    ).update({"resolved": True, "resolved_at": datetime.utcnow()})
    db.commit()


@router.post("/forgot-password", status_code=202)
def forgot_password(body: schemas.ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Public: records an in-app reset request the admin can see. Always returns a
    generic message so it never reveals whether an account exists."""
    user = _find_user_by_identifier(body.identifier, db)
    if user and user.username != "demo":
        # Avoid flooding: only one pending request per user.
        existing = db.query(models.PasswordResetRequest).filter(
            models.PasswordResetRequest.user_id == user.id,
            models.PasswordResetRequest.resolved == False,  # noqa: E712
        ).first()
        if not existing:
            db.add(models.PasswordResetRequest(user_id=user.id))
            db.commit()
    return {"detail": "Se l'account esiste, l'amministratore riceverà la richiesta di reset."}
