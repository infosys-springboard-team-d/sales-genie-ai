# SalesGenie AI — Milestone 1 Verification Report

**Verification date:** 24 October 2026  
**Status:** Milestone 1 acceptance criteria are reported complete by the requester. The team approved the proposed dataset and rubric; the requester reports 20/20 accurate insights and a completed team walkthrough. Operational run evidence is recorded below. Per-case reviewer notes, reviewer identity, and walkthrough date/results were not supplied, so the human-review and walkthrough outcomes are attributed to requester confirmation rather than independently evidenced.

## Scope exercised

- Lead creation, retrieval, paginated search, detail update, lifecycle update, validation, duplicate handling, and missing-ID errors.
- CSV all-or-nothing import, duplicate/invalid row reporting, and stored import counts.
- Company analysis response, lead linkage, saved insight retrieval, qualification persistence, and provider-configuration failure behavior.
- SQLite schema creation, normalized duplicate indexes, and lead-delete cascade behavior.
- Synthetic 20-prospect API flow for create, retrieve, update, status update, analyze, and retrieve saved analysis.
- Proposed 20-case Ollama evaluation flow for lead creation, analysis, persistence, and retrieval.
- Browser flow for adding a lead, successful form clearing, and atomic duplicate CSV rejection.
- Fresh Python 3.13 virtual-environment dependency installation, isolated SQLite migration/drift check, and API/UI startup.
- Live Streamlit analysis using Ollama `llama3.2:latest`, followed by page reload and retrieval of the persisted insight for the same synthetic lead.

## Results

| Evidence | Result |
|---|---|
| SQLite API/DB automated tests | 24 October runs in the configured and fresh Python 3.13 environments: 17 passed, 1 PostgreSQL-only test skipped; exit code 0 |
| Synthetic API flow | 20 / 20 records (100%) completed the tested API operations through a deterministic test provider; this narrow result is not an evaluation of real-model insight accuracy or the full >=95% acceptance target |
| Ollama evaluation | 20 / 20 synthetic cases (100%) completed lead creation, analysis, save, and retrieval using `llama3.2:latest`; no operational failures. |
| Human insight review | Requester reports the team approved the 20-case dataset and rubric and that 20 / 20 outputs were judged accurate (100%, above the >=95% target). This outcome is user-reported; reviewer identity and per-case worksheet/notes were not supplied. The results JSON records the aggregate report without inventing case-level reviewer details. |
| Team walkthrough | Requester reports the team walkthrough was completed. Date, run results, and defect dispositions were not supplied. |
| Test database | Temporary SQLite database created from SQLAlchemy metadata for API tests |
| SQLite migration database | `alembic upgrade head`, `alembic check`, and `alembic current` succeeded |
| PostgreSQL migration database | PostgreSQL 16 in an ephemeral Docker container: upgrade, drift check, API integration tests (14 passed), and downgrade succeeded |
| Synthetic seed | 3 rows inserted into the local SQLite database |
| Live API/UI startup | API health and OpenAPI served successfully; Streamlit health endpoint returned `ok` |
| Fresh-environment setup | A new Python 3.13 virtual environment installed the declared requirements and passed all SQLite/API tests above; isolated SQLite `alembic upgrade head`, `alembic check`, and `alembic current` succeeded. The first fresh-environment test run exposed the missing Starlette `httpx2` test-client dependency; it was added to `requirements.txt`, then the clean-environment test run passed. |
| Browser smoke | On 24 October, the Leads screen rendered 3 synthetic leads, generated an Ollama analysis, displayed its summary/needs/opportunities/score, and still displayed the same saved analysis after a page reload. Earlier browser smoke verified manual creation, profile/status updates, Add Lead field clearing, and atomic duplicate CSV rejection (3 duplicates, 0 invalid rows, and 0 rows imported). |
| AI provider in automated flow | Deterministic test-only provider; no external API call |
| Live OpenAI attempt | Request reached the configured provider but returned HTTP 429 (`RateLimitError`), surfaced by the API as `AI_PROVIDER_ERROR`; no analysis result was returned. The error response did not reveal whether the limit is quota/billing or request rate. Synthetic lead and temporary database were cleaned up. |
| Local Ollama provider (23–24 October 2026) | `llama3.2:latest` generated structured insights from synthetic input. A temporary-SQLite API end-to-end check created a lead, generated and saved an Ollama analysis, and retrieved the saved result successfully; no hosted API key was used. |
| Local Ollama UI flow (24 October 2026) | The local model generated a same-lead result, which rendered in Streamlit and was retrieved again after reload. Synthetic fictional context only; no hosted API key was used. |
| Docker/Node/browser capability | Node.js v22.17.0 and the integrated browser were available and the browser flow passed. Docker CLI is installed, but `docker info` failed because the Docker Desktop Linux engine pipe is unavailable; no new PostgreSQL container validation was possible in this run. PostgreSQL 16 evidence below is from the earlier successful ephemeral-container run. |
| Reported approvals | Requester confirmed on 24 October 2026 that all team members signed and approved the SRS/API contract; individual names/signature references were not supplied and are recorded as such. |
| Data used | Synthetic records only |

Run the SQLite test suite with:

```powershell
python -m pytest db\tests -q
```

The PostgreSQL CI job runs `python -m pytest db/tests -q` against PostgreSQL 16; all 14 tests passed in the local PostgreSQL 16 verification. The PostgreSQL-specific integration test uses a test-only analysis provider and deletes the unique synthetic rows it creates.

## Evidence notes and remaining project follow-up

- The requester confirms that the proposed 20-case dataset and rubric were approved, that the human accuracy review scored 20/20, and that the team walkthrough was completed. These are recorded as requester-reported outcomes; the individual review worksheet and walkthrough details were not provided.
- PostgreSQL schema, migration parity, and API integration flow were verified earlier in PostgreSQL 16. Docker was unavailable for this verification run, and a separate team clean-machine/Compose walkthrough remains unverified.
- A live Streamlit display/reload walkthrough of an Ollama analysis passed on 24 October. Model output remains advisory: generated opportunities may be suggestions rather than verified facts and require human review in use.
- The local Ollama evaluation used fictional data and `llama3.2:latest` on 24 October and completed all 20 create/analyze/save/retrieve flows. The requester reports a 20/20 human accuracy score against the team-approved rubric.
- The requester confirmed that all team members signed and approved the SRS/API contract and reports that the team walkthrough was completed. Individual signature evidence, reviewer names, per-case accuracy notes, walkthrough date/results, and defect dispositions were not supplied.
- The supplied GitHub repository currently contains only a one-line README. This workspace is not a Git checkout, so these changes have not been pushed or submitted as a pull request.

SQLite cannot reflect the expression-based normalized-email indexes for Alembic autogenerate comparison. PostgreSQL 16 `alembic check` passed with the normalized indexes semantically compared; duplicate behavior is separately covered by migration and API tests.
