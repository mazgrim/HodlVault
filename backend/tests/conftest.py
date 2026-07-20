"""
Fixtures condivise: DB SQLite in-memory (StaticPool: stessa connessione per
tutta la sessione di test) e TestClient con auth bypassata via dependency
override. Il TestClient NON entra nel lifespan (niente scheduler/migrazioni):
le tabelle sono create direttamente da Base.metadata.create_all.
"""
import os

# Prima di importare l'app: engine reale puntato a un in-memory usa-e-getta,
# così l'import di app.database non tocca il filesystem.
os.environ["DATABASE_URL"] = "sqlite://"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.auth import get_current_user, require_write
from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def user(db):
    u = models.User(username="tester", email="tester@example.com", hashed_password="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture()
def portfolio(db, user):
    p = models.Portfolio(user_id=user.id, name="Test PF")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture()
def client(db, user):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[require_write] = lambda: user
    c = TestClient(app)  # senza context manager: lifespan (scheduler) non parte
    try:
        yield c
    finally:
        app.dependency_overrides.clear()
