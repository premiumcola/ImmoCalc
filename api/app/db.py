"""Datenbank-Engine und Session-Dependency — von allen Routern geteilt."""
import os
from typing import Iterator

from sqlmodel import Session, create_engine

DB_PATH = os.environ.get("DB_PATH", "/data/immocalc.db")
os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
