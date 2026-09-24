"""
Single persistence path for portfolio state, backed by SQLAlchemy so the
exact same code runs against Postgres in production and SQLite in local
dev/tests — no separate "prod backend" vs "fallback backend" to drift out
of sync with each other.
"""
import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Column, DateTime, String, create_engine, select
from sqlalchemy.orm import declarative_base, sessionmaker

from paper_trader.config import settings

Base = declarative_base()


class PortfolioState(Base):
    __tablename__ = "portfolio_state"

    key = Column(String, primary_key=True)
    data = Column(JSON, nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def _with_psycopg2_driver(url: str) -> str:
    # SQLAlchemy 2.1+ defaults bare postgresql:// URLs to the psycopg (v3)
    # dialect, not psycopg2 -- but this project only installs
    # psycopg2-binary, so an unpinned SQLAlchemy upgrade broke every
    # Postgres-backed job with "ModuleNotFoundError: No module named
    # 'psycopg'" (first seen 2026-09-24, stocks-intraday-stops.yml). Pin
    # the driver in the URL itself so this can't silently break again.
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    return url


_engine = create_engine(_with_psycopg2_driver(settings.database_url))
Base.metadata.create_all(_engine)
_Session = sessionmaker(bind=_engine)


def save_state(key: str, state: dict) -> None:
    with _Session() as session:
        row = session.get(PortfolioState, key)
        if row is None:
            row = PortfolioState(key=key, data=state)
            session.add(row)
        else:
            row.data = state
            row.updated_at = datetime.now(timezone.utc)
        session.commit()


def load_state(key: str) -> Optional[dict]:
    with _Session() as session:
        row = session.get(PortfolioState, key)
        return row.data if row is not None else None
