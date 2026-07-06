import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from .data_dir import get_database_url

# Docker imposta DATABASE_URL esplicitamente → resta invariato. Altrimenti il
# percorso è risolto da data_dir (dev: ./data, desktop: portable/AppData/XDG).
DATABASE_URL = os.getenv("DATABASE_URL") or get_database_url()

# SQLite: allow same thread=False for FastAPI
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
