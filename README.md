# SalesGenie AI — Milestone 2

Milestone 2 builds on the Milestone 1 lead-management and company-intelligence
workflow with human-reviewed outreach drafts, explainable sales-readiness scores,
and next-best-action recommendations.

## Features

- FastAPI endpoints for lead creation, paginated search, retrieval, detail and
  status updates, CSV import, company analysis, saved outreach, activity logging,
  lead scoring, and recommendations.
- Streamlit screens for leads, adding/importing leads, and an Outreach Strategy
  panel for scoring, activity tracking, draft generation, editing, copying, and
  opening a draft in the user's email client.
- SQLAlchemy models and Alembic migrations for the eight-table project schema.
- SQLite for local development; PostgreSQL 16 parity is supported.
- CSV imports are all-or-nothing: any duplicate or invalid row prevents all
  leads in that file from being created.
- Scores are transparent rule-based estimates, not calibrated conversion
  probabilities. The workbook's 85% scoring-accuracy target cannot be verified
  until the project supplies labeled outcomes and an evaluation rubric.
- Generated outreach is saved for human review and is never sent automatically.
- Ollama generation uses domain-specific evidence-grounding instructions,
  low-variance decoding, and schema-constrained JSON for company insights and
  outreach. These improve consistency but do not constitute model-weight
  fine-tuning or guarantee factual accuracy; human review remains required.

Authentication is not implemented. Keep the app local and use synthetic data;
do not expose it publicly or use real prospect data.

## Requirements

- Python 3.10 or newer
- Git
- Ollama with schema-constrained structured-output support for local company
  analysis and outreach generation (no hosted AI API key required)
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
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.2:latest
API_BASE_URL=http://127.0.0.1:8000
```

Install and start Ollama for Windows, then download the configured local model:

```powershell
ollama pull llama3.2:latest
```

Ollama serves its local API on `http://127.0.0.1:11434` by default. No AI API key
is needed. Apply the migration and load synthetic sample leads:

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

The Milestone 2 API, provider, and database tests passed in SQLite. See
[MILESTONE_2_TEST_REPORT.md](./MILESTONE_2_TEST_REPORT.md) for the current
result and the scoring-accuracy evidence gap. The requester reports that the
Milestone 1 team evaluation and walkthrough were completed; supporting
case-level review and walkthrough records are not included here.

The local Ollama `llama3.2:latest` model was exercised with synthetic input. A
temporary-database API/UI end-to-end check generated, displayed, and retrieved
the saved analysis after a page reload without a hosted API key. The requester
confirmed that all team members signed and approved the SRS/API contract; the
individual signature references were not supplied in this workspace. The
requester reports that the team approved the 20-case synthetic dataset and
rubric, that Ollama completed 20/20 operational flows, and that human review
scored 20/20 insights accurate (100%, meeting the >=95% target). The reviewer
worksheet and reviewer identity were not supplied, so this evaluation is
recorded as requester-reported.
