"""The DB-test guard: local hosts connect, anything else skips unless opted
in. Literal URLs throughout; none of these tests opens a connection."""

import pytest

from tests._db_guard import skip_reason


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://aiact:aiact@localhost:5432/aiact_local",
        "postgresql://aiact:aiact@127.0.0.1:5432/aiact_local",
        "postgresql+psycopg://aiact:aiact@localhost/aiact",
    ],
)
def test_local_host_may_connect(url):
    assert skip_reason(url, None) is None


def test_remote_host_skips_and_reports_host_only():
    reason = skip_reason("postgresql://user:s3cret@db.example.com:5432/postgres", None)
    assert reason == (
        "DATABASE_URL host 'db.example.com' is not local; "
        "set ALLOW_REMOTE_DB_TESTS=1 to run DB tests against it"
    )
    assert "s3cret" not in reason


def test_remote_host_with_opt_in_may_connect():
    assert skip_reason("postgresql://u:p@db.example.com:5432/postgres", "1") is None


@pytest.mark.parametrize("opt_in", [None, "", "0", "true", "yes"])
def test_only_exactly_1_opts_in(opt_in):
    assert skip_reason("postgresql://u:p@db.example.com/postgres", opt_in) is not None


def test_missing_url_skips():
    assert skip_reason(None, None) == "DATABASE_URL not configured"
    assert skip_reason("", "1") == "DATABASE_URL not configured"


def test_localhost_lookalike_is_remote():
    assert skip_reason("postgresql://u:p@localhost.evil.com/x", None) is not None


def test_session_open_skips_on_remote_host(monkeypatch):
    """The autouse fixture is wired into the real SessionLocal: opening a
    session against a remote host raises pytest's skip before any engine is
    created."""
    from app.db import session as db_session

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@example.invalid:5432/x")
    monkeypatch.delenv("ALLOW_REMOTE_DB_TESTS", raising=False)
    with pytest.raises(pytest.skip.Exception, match="'example.invalid' is not local"):
        db_session.SessionLocal()
