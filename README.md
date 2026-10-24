# SalesGenie AI — Milestone 1

Milestone 1 delivers a local lead-management and company-intelligence workflow:
create or import a lead, search and update it, request company analysis, and
retrieve the saved insight associated with that lead.

## Features

- FastAPI endpoints for lead creation, paginated search, retrieval, detail and
  status updates, CSV import, company analysis, and saved-analysis retrieval.
- Streamlit screens for leads, adding a lead, and importing CSV files.
- SQLAlchemy models and Alembic migration for the eight-table project schema.
- SQLite for local development; PostgreSQL 16 parity is supported.
- CSV imports are all-or-nothing: any duplicate or invalid row prevents all
  leads in that file from being created.
- Qualification is an explainable heuristic estimate, not a conversion
  probability.

Authentication is not implemented. Keep the app local and use synthetic data;
do not expose it publicly or use real prospect data.

## Requirements

- Python 3.10 or newer
- Git
- An OpenAI API key with API usage available for live company analysis
- Docker Desktop only if you want to run the optional PostgreSQL service

## Run locally on Windows

From the project root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit the ignored local `.env` file and set:

```dotenv
DATABASE_URL=sqlite:///./salesgenie.db
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4o-mini
API_BASE_URL=http://127.0.0.1:8000
```

Never commit or share `.env` or its key. Apply the migration and load synthetic
sample leads:

```powershell
python -m alembic upgrade head
python -m db.seed
```

Start the API in one terminal:

```powershell
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Start the UI in a second terminal:

```powershell
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Open the UI at <http://127.0.0.1:8501> and API documentation at
<http://127.0.0.1:8000/docs>. For PostgreSQL setup and detailed API behavior,
see the project setup and API contract documents in the team's source materials.

## Verification status

The implementation's SQLite tests last passed with **13 passed, 1
PostgreSQL-only test skipped**. A separate PostgreSQL 16 run passed all 14
database/API tests and migration checks. A synthetic 20-record automated flow
passed using a deterministic test provider; this does not measure real AI
accuracy.

A live OpenAI analysis attempt returned HTTP 429, so successful real-provider
analysis and saved-result retrieval have not yet been verified. The milestone
sheet's >=95% manageable-record and accurate-insight target also remains open
until the team agrees on a test set and review rubric, evaluates the results,
and completes its demo and sign-off.
