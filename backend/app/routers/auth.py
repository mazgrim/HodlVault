import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func
from sqlalchemy.orm import Session
from jose import JWTError

from ..database import get_db
from .. import models, schemas, security
from ..auth import (
    verify_password, hash_password,
    create_access_token, create_refresh_token, decode_token,
    get_current_user, require_write, desktop_mode,
)

router = APIRouter()

DESKTOP_USER = os.getenv("DESKTOP_USER", "local")


@router.get("/config", response_model=schemas.AuthConfig)
def auth_config():
    """Config pubblica: consente al frontend di sapere se è in modalità desktop
    (auto-login) e se la registrazione è aperta, prima di autenticarsi."""
    return schemas.AuthConfig(
        desktop_mode=desktop_mode(),
        registration_open=os.getenv("REGISTRATION_OPEN", "true").lower() == "true",
    )


@router.post("/desktop-login", response_model=schemas.Token)
def desktop_login(db: Session = Depends(get_db)):
    """
    Login passwordless per l'app desktop single-user. **Disponibile solo con
    DESKTOP_MODE attivo** (impostato dal launcher): fuori da quel contesto
    risponde 404, così un'istanza web non offre mai accesso senza password.

    Usa (creandolo al primo avvio) l'utente locale unico.
    """
    if not desktop_mode():
        raise HTTPException(status_code=404, detail="Not found")

    user = db.query(models.User).filter(models.User.username == DESKTOP_USER).first()
    if user is None:
        # Se esiste già un altro utente (DB importato/migrato), riusa il primo;
        # altrimenti crea l'utente locale proprietario.
        user = db.query(models.User).order_by(models.User.id).first()
    if user is None:
        import secrets
        user = models.User(
            username=DESKTOP_USER,
            email=f"{DESKTOP_USER}@localhost",
            hashed_password=hash_password(secrets.token_urlsafe(24)),
            is_admin=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    return schemas.Token(
        access_token=create_access_token({"sub": str(user.id)}),
        refresh_token=create_refresh_token({"sub": str(user.id)}),
    )


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
def login(creds: schemas.UserLogin, request: Request, db: Session = Depends(get_db)):
    ip = security.client_ip(request)
    ua = request.headers.get("user-agent", "")
    identifier = (creds.username or "").strip()

    # Brute-force lockout: too many recent failures from this IP or against this
    # account → reject without even checking the password. Protects an
    # internet-exposed instance from bots. The block is recorded so the lockout
    # stays effective while an attacker keeps hammering and the admin sees it.
    if security.is_locked(db, ip, identifier):
        security.record_attempt(db, identifier=identifier, ip=ip, user_agent=ua,
                                success=False, blocked=True)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Troppi tentativi di accesso falliti. Attendi "
                f"{security.LOCKOUT_MINUTES} minuti senza riprovare, oppure "
                f"contatta l'amministratore."
            ),
        )

    # Accept either the username or the email in the same field.
    user = _find_user_by_identifier(identifier, db)
    if not user or not verify_password(creds.password, user.hashed_password):
        security.record_attempt(db, identifier=identifier, ip=ip, user_agent=ua, success=False)
        raise HTTPException(status_code=401, detail="Credenziali non valide")
    if not user.is_active:
        security.record_attempt(db, identifier=identifier, ip=ip, user_agent=ua, success=False)
        raise HTTPException(status_code=403, detail="Account disabilitato")

    security.record_attempt(db, identifier=identifier, ip=ip, user_agent=ua, success=True)
    security.prune_old(db)
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
