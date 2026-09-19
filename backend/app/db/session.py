import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

_engine = None
_session_factory = None


def _get_session_factory():
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine(os.environ["DATABASE_URL"])
        _session_factory = sessionmaker(bind=_engine)
    return _session_factory


def SessionLocal():
    return _get_session_factory()()
