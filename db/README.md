# SalesGenie database and local PostgreSQL

This standalone database deliverable follows the project baseline: SQLAlchemy 2.x,
Alembic migrations, SQLite for a lightweight local run, and PostgreSQL 16 for
database-parity development and production. It defines the six entities in the
SRS plus `import_batches` and `agent_runs`, for the eight-table assignment.

## Tables

See [ER_DIAGRAM.md](./ER_DIAGRAM.md) for the Mermaid entity-relationship diagram.

| Table | Purpose |
|---|---|
| `leads` | Lead/contact fields, lifecycle status, and timestamps |
| `company_insights` | Persisted analysis linked to its lead |
| `lead_scores` | Estimated score, rationale, and factors |
| `outreach_drafts` | Drafted email/message content; never sent automatically |
| `activities` | Lead engagement events and structured details |
| `conversation_summaries` | Summary, key points, and action items |
| `import_batches` | CSV import counters and row-level validation errors |
| `agent_runs` | Workflow status and checkpoint reference, without prompts or secrets |

Child records for insights, scores, drafts, and activities are deleted with a
lead. Conversation summaries and agent-run metadata are retained with a null
lead reference if the lead is deleted. JSON fields use SQLAlchemy's portable
JSON type, suitable for both SQLite and PostgreSQL.

Partial unique indexes enforce normalized nonblank email and normalized
company/contact pairs when email is absent. The API must normalize blank
optional fields to `NULL`, check a no-email import against existing company and
contact values even when the existing row has an email, and translate database
uniqueness violations to the contract's explicit duplicate response. The
requester-reported team approval of the selected lifecycle values and duplicate
rule is recorded in the SRS/API contract; formal contract signatures remain
pending. SQLite foreign-key checks are enabled by the shared
`db.database.create_database_engine` helper.

## Local SQLite migration (PowerShell)

```powershell
python -m pip install -r db/requirements.txt
$env:DATABASE_URL = "sqlite:///./salesgenie.db"
alembic upgrade head
alembic current
```

To remove the schema in the disposable local database:

```powershell
alembic downgrade base
```

Load the repeatable synthetic lead set after applying the migration:

```powershell
python -m db.seed
```

The seed command is restricted to SQLite or a local PostgreSQL database named
`salesgenie_dev`; it refuses other database targets and inserts no real prospect
data.

## PostgreSQL with Docker Compose (PowerShell)

```powershell
Copy-Item .env.example .env
# Edit .env and set a unique local-only POSTGRES_PASSWORD and matching DATABASE_URL.
docker compose up -d postgres
$env:DATABASE_URL = "postgresql+psycopg://salesgenie:<password>@localhost:5432/salesgenie_dev"
alembic upgrade head
alembic current
```

Keep the same actual password in the local `.env` and the shell's `DATABASE_URL`.
The Compose port is bound to loopback only. The named volume persists local data;
`docker compose down -v` deletes it and should only be used when intentionally
discarding this local database.

## Migration workflow

1. Update the SQLAlchemy models and add a new numbered Alembic revision; do not
   edit an already-applied revision.
2. Review the generated migration before applying it.
3. Apply and test against SQLite and PostgreSQL before merging.
4. Keep credentials, real lead data, CSV contents, prompts, and model outputs
   out of source control and deployment logs.

The GitHub Actions workflow runs upgrade, metadata-drift check, and downgrade
against both SQLite and PostgreSQL. SQLite migration checks passed locally.
PostgreSQL 16 upgrade, metadata-drift check, API integration tests, and
downgrade passed in an ephemeral Docker container; this did not start or modify
the persistent Compose database volume.
