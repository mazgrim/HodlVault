"""Brute-force protection for the login endpoint.

Counts recent *failed* login attempts (by IP and by the identifier tried) and
locks further attempts once they exceed a threshold within a sliding window.
This is what keeps an internet-exposed instance from being walked over by bots.

All thresholds are env-overridable so a private deployment can loosen them.
"""

import os
from datetime import datetime, timedelta

from fastapi import Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from . import models

# Max failed attempts (per IP or per identifier) inside the window before locking.
MAX_FAILED_ATTEMPTS = int(os.getenv("LOGIN_MAX_ATTEMPTS", 5))
# Sliding window / lockout duration, in minutes.
LOCKOUT_MINUTES = int(os.getenv("LOGIN_LOCKOUT_MINUTES", 15))
# How long to keep attempt rows for the audit log before pruning.
ATTEMPT_RETENTION_DAYS = int(os.getenv("LOGIN_ATTEMPT_RETENTION_DAYS", 90))


def client_ip(request: Request) -> str:
    """Best-effort real client IP. Behind nginx / the Vite proxy the socket peer
    is the proxy, so prefer the forwarded headers (first hop)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else "unknown"


def _window_start() -> datetime:
    return datetime.utcnow() - timedelta(minutes=LOCKOUT_MINUTES)


def failed_count(db: Session, ip: str | None, identifier: str | None) -> int:
    """Failed attempts in the current window matching this IP *or* identifier."""
    conds = []
    if ip:
        conds.append(models.LoginAttempt.ip_address == ip)
    if identifier:
        conds.append(models.LoginAttempt.identifier == identifier)
    if not conds:
        return 0
    return (
        db.query(models.LoginAttempt)
        .filter(
            models.LoginAttempt.success == False,  # noqa: E712
            models.LoginAttempt.created_at >= _window_start(),
            or_(*conds),
        )
        .count()
    )


def is_locked(db: Session, ip: str | None, identifier: str | None) -> bool:
    return failed_count(db, ip, identifier) >= MAX_FAILED_ATTEMPTS


def record_attempt(
    db: Session,
    *,
    identifier: str | None,
    ip: str | None,
    user_agent: str | None,
    success: bool,
    blocked: bool = False,
) -> None:
    db.add(
        models.LoginAttempt(
            identifier=((identifier or "").strip()[:128] or None),
            ip_address=((ip or "").strip()[:64] or None),
            user_agent=((user_agent or "").strip()[:256] or None),
            success=success,
            blocked=blocked,
        )
    )
    db.commit()


def prune_old(db: Session) -> None:
    """Drop attempt rows older than the retention window. Cheap; runs on success."""
    cutoff = datetime.utcnow() - timedelta(days=ATTEMPT_RETENTION_DAYS)
    db.query(models.LoginAttempt).filter(
        models.LoginAttempt.created_at < cutoff
    ).delete(synchronize_session=False)
    db.commit()
