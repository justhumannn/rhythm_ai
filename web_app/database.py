from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

APP_ENV = os.environ.get("RHYTHM_ENV", "local").casefold()
LOCAL_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{DATA_DIR / 'rhythm_web.sqlite'}",
)
if APP_ENV == "local":
    DATABASE_URL = LOCAL_DATABASE_URL
else:
    DATABASE_URL = os.environ.get("SUPABASE_DATABASE_URL", "")
    if not DATABASE_URL:
        raise RuntimeError(
            "SUPABASE_DATABASE_URL is required when RHYTHM_ENV is not local"
        )

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql+psycopg://",
        1,
    )
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://",
        "postgresql+psycopg://",
        1,
    )

engine_options = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}
else:
    engine_options.update(
        {
            "pool_size": int(os.environ.get("DATABASE_POOL_SIZE", "5")),
            "max_overflow": int(os.environ.get("DATABASE_MAX_OVERFLOW", "2")),
            "pool_recycle": int(os.environ.get("DATABASE_POOL_RECYCLE", "300")),
        }
    )

engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
