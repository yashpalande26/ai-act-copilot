"""Which database a test may connect to.

backend/.env points DATABASE_URL at the live Supabase database, and
app.db.session loads it on import, so without a guard a plain `pytest` would
run every DB-backed test against production (and pay its egress). The
autouse fixture in conftest.py calls skip_reason() on every session open and
skips the test unless the host is local or the opt-in is set explicitly.

Only the host is ever reported, never the full URL (it carries the password).
"""

from sqlalchemy.engine import make_url

LOCAL_DB_HOSTS = frozenset({"localhost", "127.0.0.1"})
REMOTE_DB_OPT_IN = "ALLOW_REMOTE_DB_TESTS"


def skip_reason(database_url: str | None, opt_in: str | None) -> str | None:
    """None when a test may connect to database_url; otherwise why it skips."""
    if not database_url:
        return "DATABASE_URL not configured"
    host = make_url(database_url).host
    if host in LOCAL_DB_HOSTS or opt_in == "1":
        return None
    return (
        f"DATABASE_URL host {host!r} is not local; "
        f"set {REMOTE_DB_OPT_IN}=1 to run DB tests against it"
    )
