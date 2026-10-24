# SalesGenie AI — Development and Repository Setup

**Status:** Core Milestone 1 application implemented; local SQLite/API/UI and live-provider validation passed; reported team approvals recorded  
**Prepared:** 24 October 2026  
**Selected baseline:** Python + FastAPI + Streamlit + SQLAlchemy + Alembic; SQLite for local development, PostgreSQL for production; local Ollama for AI analysis

> The supplied GitHub repository was previously found to contain only a one-line README, and this workspace has no Git metadata. The implementation in this workspace is therefore the working source baseline. The requester confirms that team members approved the SRS/API contract; individual approval references are not present. No changes have been pushed to GitHub.

## 1. Prerequisites

- Python 3.10 or newer (training-guide minimum); Python 3.11 is used by CI. This workspace was verified with Python 3.13.5.
- Git.
- Docker Desktop when running PostgreSQL locally.
- Ollama for local company analysis; no hosted AI API key is required.

## 2. Repository and branch workflow

The supplied repository was inspected; its only file is `README.md` (`# sales-genie-ai`). The current project workspace is not a Git checkout. Before publishing this implementation, the project lead should coordinate with the repository owner, import/reconcile this source baseline, and agree on the branch/PR policy. Do not initialize or push a repository without that coordination.

```powershell
git clone https://github.com/230701224/sales-genie-ai.git
Set-Location .\sales-genie-ai
git fetch origin
git branch --all
```

Proposed branch policy:

- `main`: reviewed, demoable baseline; protect it from direct pushes.
- `develop`: shared integration branch, if the team agrees to use it.
- `feature/<ticket>-<short-name>`: short-lived task branches.
- Submit changes through pull requests; require at least one teammate review and passing tests before merging.
- Do not commit `.env`, local databases containing real data, virtual environments, caches, or credentials.

Before creating `develop`, check `git branch --all` and coordinate with repository owners to avoid creating a conflicting branch or overwriting existing work.

## 3. Windows virtual environment

From the current project root in PowerShell:

```powershell
python --version
git --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, use the team's approved execution policy or invoke the environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The repository provides a root `requirements.txt`, `.env.example`, and `.gitignore`. Version ranges are declared in the manifest; the team should lock and approve exact versions before deployment.

## 4. Environment configuration

Copy the example file locally and fill only local values:

```powershell
Copy-Item .env.example .env
```

The checked-in `.env.example` contains local-safe placeholders:

```dotenv
DATABASE_URL=sqlite:///./salesgenie.db
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.2:latest
API_BASE_URL=http://127.0.0.1:8000
```

Install and start Ollama for Windows, then download the configured model:

```powershell
ollama pull llama3.2:latest
```

Ollama serves its local API at `http://127.0.0.1:11434` by default. Set
`OLLAMA_BASE_URL` and `OLLAMA_MODEL` if the server or model differs. Use a
PostgreSQL `DATABASE_URL` for production configuration and local parity tests
when required. Keep actual passwords and any credentials out of documentation,
terminal recordings, screenshots, and commits.

## 5. Local services

The existing guides/screenshots indicate a FastAPI backend on port `8000` and a Streamlit UI on port `8501`. Apply the migration and load repeatable synthetic data first:

```powershell
python -m alembic upgrade head
python -m db.seed
```

Start the API:

```powershell
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

In a second PowerShell window, activate the same virtual environment and run:

```powershell
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Expected local endpoints:

- API: `http://127.0.0.1:8000`
- API documentation: `http://127.0.0.1:8000/docs`
- Streamlit: `http://127.0.0.1:8501`

FastAPI serves interactive API docs at `http://127.0.0.1:8000/docs` and OpenAPI JSON at `http://127.0.0.1:8000/openapi.json`. The Streamlit Leads screen supports searching/filtering, lead detail edits and lifecycle status, company analysis, and viewing saved insights. Separate pages handle manual add and CSV import. CSV is all-or-nothing: any invalid or duplicate row rejects the file without creating any of its otherwise-valid rows.

Analysis requests use the local Ollama server and configured model; no hosted
AI API key is required. If Ollama is unavailable or returns an invalid result,
the API returns an explicit error and does not create a success-shaped analysis
record. Automated flow tests inject a deterministic test-only provider.

## 6. Database and Docker baseline

- Local development default: SQLite, selected from the training-guide baseline.
- Production target: PostgreSQL.
- Use SQLAlchemy for persistence and Alembic migrations for schema changes.
- The workspace includes an eight-table SQLAlchemy model and Alembic migration in `db/` and `alembic/`. The eight tables are documented in `db/README.md`. The requester confirms approval of the status values, duplicate matching rule, SRS, and API contract.
- `compose.yaml` runs PostgreSQL 16 for parity testing, binds its port to localhost, obtains its password from the ignored local `.env`, and persists data in a named volume. Never use the example password outside an isolated local environment.
- GitHub Actions is configured to validate upgrade/check/downgrade on SQLite and PostgreSQL. SQLite tests and PostgreSQL 16 migration/API tests passed locally; a remote GitHub Actions run is not recorded.

For PostgreSQL local development, copy `.env.example` to `.env`, replace the local-only password, and follow the tested command sequence in `db/README.md`. Never commit `.env`.

Docker Compose configuration is present. PostgreSQL 16 was validated in an isolated temporary container; the persistent Compose volume was not created or changed by that check.

## 7. Initial verification checklist

Verified in this workspace on 24 October 2026:

- `python -m pytest db\tests -q` passes 17 tests with one PostgreSQL-only test skipped when `TEST_DATABASE_URL` is unset. A fresh Python 3.13 virtual environment installed the declared requirements and passed the same suite. `httpx2` is declared for Starlette's test client. Against PostgreSQL 16, all 14 tests passed in the earlier database/API parity run, including a 20-prospect API flow using a test-only provider.
- Tests use synthetic records and a temporary SQLite database; no provider key is needed for test execution.
- API health, Streamlit health, isolated SQLite migrations, and the live Ollama analysis display/retrieval flow passed. The browser still showed the saved result after reload.

Remaining for objective acceptance: the approved >=95% insight-accuracy target
cannot be calculated because the requester reports the approved test set is
unavailable; reviewer-rubric details and labeled expected facts are also not
recorded. The requester replied "ok" regarding the clean-machine walkthrough
and demo rehearsal, but no date or outcomes were supplied. Docker Desktop's Linux engine was
unavailable during the latest run, so PostgreSQL could not be rerun. The
requester confirmed team SRS/API approval; individual signature references
were not provided. See
[MILESTONE_1_TEST_REPORT.md](./MILESTONE_1_TEST_REPORT.md) and
[runtime-validation-report.md](./runtime-validation-report.md).
