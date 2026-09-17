# AI Act Copilot

A copilot that classifies whether an AI system is high-risk under the EU AI Act and explains why, grounded in official sources with citations.

## Setup

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
```

**Always activate `.venv` before running project commands** (`source .venv/bin/activate`, from the repo root). Every command below — `pytest`, `ruff`, `alembic`, `uvicorn`, the ingestion scripts — assumes it's running against `.venv`, not your system Python.

If you forget to activate it, `pytest`/`python`/`pip` can silently resolve to a *different* Python on your `PATH` (a system install, pyenv, conda, etc.) that has none of this project's dependencies installed — you'll see `ModuleNotFoundError` for packages that `pip list` (inside `.venv`) clearly shows as installed. Check which interpreter is actually running with `which pytest` / `which python`; both should point inside `.../ai-act-copilot/.venv/bin/`. If they don't, activate the venv (or run `.venv/bin/pytest`, `.venv/bin/python -m pytest` explicitly).

Run the tests:
```
cd backend
pytest
```
