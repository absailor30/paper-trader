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


_engine = create_engine(settings.database_url)
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
