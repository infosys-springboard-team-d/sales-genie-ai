# SalesGenie Runtime Validation Report

**Generated:** 2026-11-19 19:35 (+05:30)  
**Target:** SalesGenie  
**Validation scope:** Backend API, Streamlit frontend, AI/ML providers, and database

## Summary

| Area | Status | Exit code | Results |
|---|---|---:|---|
| Application startup | PASS | 0 | FastAPI health endpoint and Streamlit root returned HTTP 200 |
| Complete pytest suite | PASS | 0 | 49 passed, 1 PostgreSQL-only test skipped, 0 failed; 27 non-failing warnings |
| Frontend/browser workflows | PASS (targeted) | 0 | Add/edit lead, analysis/score, CSV import, outreach, and conversation summary exercised in a real browser |
| Live AI/ML integration | PASS (functional) | 0 | Local Ollama analysis, grounded outreach with supplied notes, and conversation-summary flows persisted |
| SQLite migrations/schema/seed | PASS | 0 | Migration tests and drift check passed; seed run inserted 3 rows, then 0 on repeat |
| Outreach grounding regression | FIXED / PASS | 0 | Blank-notes hallucination reproduced, replaced by neutral deterministic template, and API/UI read-back verified |
| PostgreSQL integration | SKIPPED | N/A | No `TEST_DATABASE_URL`; `docker info` failed because Docker Desktop's engine pipe was unavailable |
| Live CRM writes and model-quality evaluation | NOT RUN | N/A | CRM writes need sandbox authorization; the Milestone 1 evaluation CSV is missing |

**Overall: PASS WITH LIMITATIONS.** The executable local checks passed, and the discovered blank-notes outreach hallucination was fixed. PostgreSQL parity, live CRM writes, and a fresh human-reviewed AI-quality score remain unverified.

## Test evidence

### Module coverage matrix

| Module / layer | Coverage in this run | Evidence | Status / gap |
|---|---|---|---|
| `main.py` — FastAPI routes and error handling | Lead CRUD/search/status, CSV import, analysis, scoring, activities, outreach, conversations, and CRM sync | `test_api.py`, `test_milestone3.py`, live Ollama API flows | PASS |
| `api/schemas.py` — request/response validation | Invalid lead/status, transcript length/blank input, response validation | `test_api.py`, `test_milestone3.py` | PASS |
| `api/analysis.py` — company analysis provider | Valid/invalid Ollama outputs, provider unavailable/configuration failures; one live analysis | `test_analysis_provider.py`, `test_api.py`, live Ollama flow | PASS |
| `api/outreach.py` — outreach provider | Valid email parsing, missing subject, provider unavailable, neutral no-pain-point template; live Ollama draft with supplied notes | `test_outreach_provider.py`, live API/browser flows | PASS; no-pain-point case bypasses the model |
| `api/conversations.py` — transcript summary provider | API validation/failure behavior and one live summary; source transcript is not persisted | `test_milestone3.py`, live Ollama flow | PASS |
| `api/crm.py` — CRM providers and sync orchestration | Salesforce/HubSpot request mapping, repeat-sync behavior, partial failure, missing config, safe mapping response | `test_milestone3.py` with fake HTTP responses/providers | PASS for mocked tests; no live CRM account call |
| `api/scoring.py` — lead scoring and recommendations | Score factors, score persistence, activity impact, recommendations | `test_api.py` | PASS; rule-based score, not validated predictive ML |
| `app.py` — Streamlit user interface | Lead create/edit, analysis, scoring, CSV import, outreach generation, and conversation summary | Integrated real-browser journeys and API/database read-back | PASS for these journeys; no exhaustive visual/accessibility audit |
| `db/database.py`, `db/models.py` | SQLite persistence, foreign keys/cascade, uniqueness, JSON-backed records, and model constraints | `test_api.py`, `test_schema.py`, live flows | PASS on SQLite |
| `alembic/` — database migrations | Upgrade to head, expected tables/indexes, drift check, downgrade to base | `test_schema.py`, direct `alembic check` | PASS on SQLite; SQLite expression-index reflection warning |
| `db/seed.py` | Two consecutive runs against a fresh migrated SQLite DB; exact three synthetic rows verified | Isolated seed validation | PASS; first run inserted 3, second inserted 0 |
| PostgreSQL deployment parity | PostgreSQL integration test was collected but skipped | `test_postgres.py` | UNVERIFIED: no configured test URL and Docker daemon unavailable |

### Backend and API

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

**Fresh result:** `.\.venv\Scripts\python.exe -m pytest -v` — 50 collected; 49 passed, 1 skipped, 0 failed; exit code 0 (16.00 seconds).  
**Environment:** Python 3.13.5, pytest 8.4.2, Windows.

### Individual automated test results

All tests below passed unless marked **SKIPPED**. The PostgreSQL test was skipped because `TEST_DATABASE_URL` was not set.

#### `db/tests/test_api.py` — 14 passed

| Test | What it verifies |
|---|---|
| `test_lead_create_search_retrieve_update_and_status` | Create a lead, search by contact, retrieve, patch a field, and move its status. |
| `test_duplicate_rules_and_explicit_unknown_lead_error` | Reject duplicate email/contact records and return the documented not-found error for an unknown lead. |
| `test_validation_error_uses_common_envelope` | Invalid lead input returns the shared error response structure and details. |
| `test_csv_import_rolls_back_all_rows_when_any_row_is_invalid_or_duplicate` | A mixed invalid/duplicate CSV import persists no otherwise-valid rows and records a failed import batch. |
| `test_csv_import_commits_complete_valid_file_and_detects_within_file_duplicates` | Valid CSV rows commit; duplicate rows in one file are detected and rolled back. |
| `test_analysis_is_saved_and_retrievable_for_same_lead` | Analysis output and qualification are linked to the lead and persist for retrieval. |
| `test_lead_score_activity_and_recommendation_are_persisted` | Sales-readiness score, recommendation, activity, and updated score factors persist and can be retrieved. |
| `test_outreach_draft_generate_list_and_edit` | Generate an email draft, list it, update it, and verify the saved content. |
| `test_outreach_provider_failure_does_not_save_a_draft` | Provider failure returns an explicit error and creates no draft. |
| `test_latest_company_analysis_keeps_its_own_qualification_after_milestone2_score` | Adding a Milestone 2 score does not alter the saved analysis qualification. |
| `test_analysis_provider_failure_never_returns_success_or_persists` | Missing provider configuration is not reported as success. |
| `test_ollama_failure_returns_explicit_error_without_saving_analysis` | Ollama failure returns an explicit provider error and leaves no saved analysis. |
| `test_no_analysis_and_invalid_status_are_explicit` | Missing analysis and an invalid status produce explicit error responses. |
| `test_twenty_synthetic_leads_complete_supported_api_flow` | Twenty synthetic lead create/retrieve/update/status/analyze/read-back flows complete through the API. |

#### Provider tests — 8 passed

| Test module / test | What it verifies |
|---|---|
| `test_analysis_provider.py::test_ollama_provider_parses_analysis_response` | Parse a valid structured Ollama analysis response. |
| `test_analysis_provider.py::test_ollama_provider_reports_unavailable_service` | Convert provider connectivity failure to the expected domain error. |
| `test_analysis_provider.py::test_ollama_provider_rejects_invalid_analysis_json` | Reject malformed analysis output. |
| `test_outreach_provider.py::test_ollama_outreach_provider_parses_a_personalized_email` | Parse a valid generated email and its subject/body. |
| `test_outreach_provider.py::test_ollama_outreach_provider_surfaces_unavailable_service` | Surface Ollama unavailability explicitly. |
| `test_outreach_provider.py::test_ollama_outreach_provider_rejects_missing_email_subject` | Reject an email response missing the required subject. |
| `test_outreach_provider.py::test_ollama_outreach_provider_uses_neutral_template_without_pain_points[email-A brief conversation]` | Email with no verified need uses a safe subject/body without calling Ollama. |
| `test_outreach_provider.py::test_ollama_outreach_provider_uses_neutral_template_without_pain_points[message-None]` | Message with no verified need uses a safe body without a subject or Ollama call. |

#### `db/tests/test_milestone3.py` — 11 passed

| Test | What it verifies |
|---|---|
| `test_conversation_summary_is_saved_and_retrievable_without_transcript` | Summary, key points, and actions persist and are retrievable; the transcript is not stored in the summary record. |
| `test_conversation_provider_failure_does_not_save_a_summary` | Provider failure does not create a summary. |
| `test_conversation_request_rejects_blank_and_oversized_transcripts` | Blank and over-limit transcripts fail request validation. |
| `test_synthetic_sample_transcripts_match_summary_request_contract` | Sample transcript data conforms to the summary request schema and includes expected facts/actions. |
| `test_crm_sync_sends_contacts_activities_and_existing_deal_stage_once` | Sync contact, activities, and explicitly mapped deal stage; repeat sync avoids duplicate operations. |
| `test_crm_sync_reports_partial_activity_failures` | Partial CRM failures are reported and written to sync logs. |
| `test_crm_sync_requires_configured_credentials_and_records_failure` | Missing CRM configuration yields an explicit error and a failure log. |
| `test_deal_stage_is_not_updated_without_an_explicit_mapping` | Missing deal-stage mapping blocks sync before provider calls. |
| `test_crm_mapping_status_excludes_credentials` | CRM configuration status does not expose a provider token. |
| `test_salesforce_adapter_maps_contacts_activities_and_existing_deal` | Salesforce adapter maps contact/activity fields and updates only the supplied existing deal. |
| `test_hubspot_adapter_maps_contact_task_and_existing_deal` | HubSpot adapter maps contact/task fields and updates only the supplied existing deal. |

#### Database tests — 7 passed; PostgreSQL test — 1 skipped

| Test module / test | Status | What it verifies |
|---|---|---|
| `test_schema.py::test_all_migrations_can_downgrade_to_base` | PASS | All migrations can be reversed to an empty schema. |
| `test_schema.py::test_deleting_a_lead_cascades_its_insight` | PASS | Deleting a lead cascades to its dependent insight. |
| `test_schema.py::test_fallback_duplicate_is_unique_when_email_is_missing` | PASS | Normalized company/contact fallback uniqueness applies when email is absent. |
| `test_schema.py::test_migration_creates_the_nine_tables` | PASS | The expected nine application tables are created. |
| `test_schema.py::test_migration_metadata_has_no_drift` | PASS | Alembic reports no migration operations missing from the schema. |
| `test_schema.py::test_milestone3_columns_and_crm_sync_indexes_exist` | PASS | Conversation interaction type and CRM sync indexes exist. |
| `test_schema.py::test_normalized_email_is_unique` | PASS | Email uniqueness ignores case and surrounding whitespace. |
| `test_postgres.py::test_postgresql_milestone_flow_and_atomic_csv` | SKIPPED | PostgreSQL API/CSV transaction integration requires `TEST_DATABASE_URL`. |

The automated API tests use isolated SQLite test databases and deterministic provider doubles for repeatable results. They do not require external AI or CRM credentials. The twenty-record API test verifies operational flow completion; it is not evidence of model accuracy.

### Frontend and API integration

The Streamlit app was exercised in an integrated real browser against FastAPI
and an isolated migrated SQLite database. Synthetic `example.test` data was
used throughout:

- **Leads:** created a lead, verified it in the API-backed lead list, edited its
  industry, and observed the saved value after rerender.
- **Analysis and scoring:** submitted synthetic company notes, received a
  qualification analysis, and verified the displayed score/recommendation.
- **CSV import:** uploaded a synthetic CSV and observed a successful one-row
  import.
- **Outreach:** generated and persisted a draft with supplied notes. A separate
  empty-notes browser submission displayed the new neutral template and saved
  it successfully.
- **Conversations:** summarized a synthetic transcript and verified the
  summary/action output; the transcript is not persisted in the summary record.
- **Service readiness:** FastAPI `/health` and the Streamlit root returned
  HTTP 200.

These are targeted browser journeys, not an exhaustive visual, responsive,
accessibility, or cross-browser audit. The Playwright Chromium cache is missing;
the browser journeys used the available integrated browser instead.

### Live AI/ML provider checks

The local Ollama service was reachable and each configured provider model was
present in the local model list. Using synthetic-only content and a temporary
SQLite database, these live provider workflows passed:

1. **Company analysis:** created a synthetic lead, posted synthetic company context to `POST /api/v1/leads/{lead_id}/analysis`, received a successful response, and retrieved the saved result from `GET /api/v1/leads/{lead_id}/analysis`.
2. **Outreach with verified notes:** requested a short email using the explicit synthetic notes “Improve reporting; reduce manual work”. The live draft referenced those notes and did not add the previously observed inventory workflow or an unsupported sender-capability claim; the saved draft was retrievable from the API.
3. **Conversation summary:** submitted a synthetic meeting transcript to `POST /api/v1/leads/{lead_id}/conversation-summaries`, retrieved it from the matching GET endpoint, and verified the returned record did not include the source transcript.

These checks verify provider connectivity, output parsing, API workflow, and
persistence; they are not a human quality/accuracy evaluation. The lead
scoring implementation is also exercised by automated tests, but it is a
rule-based estimate, not a validated predictive model.

#### Outreach hallucination found and fixed

The browser retest showed that the model could invent “synthetic test data
management” and claim “our solutions” even when the needs field was blank,
despite prompt-only grounding instructions. Prompt wording alone was not a
reliable safeguard. The Ollama outreach provider now uses a deterministic,
neutral email/message template when no verified pain points are supplied; it
does not call Ollama for that case. The existing model-generated path remains
available when the user supplies notes.

Regression evidence:

- Two provider tests verify email and message fallback output and assert Ollama
  is not called.
- The complete test suite passes.
- A live API check with Ollama deliberately pointed at an unavailable local
  port still generated and persisted the neutral draft, and GET read-back
  matched it.
- The browser UI generated and displayed the same neutral fallback.

The deterministic fallback uses only the supplied contact name and user goal.
It does not infer a prospect problem from the company name or industry.

### AI quality and scoring limits

- `resource/milestone_1_ai_evaluation_set.csv` is absent, so the evaluator could
  not produce a fresh per-case Milestone 1 AI quality score. The historical
  results JSON is not a substitute for the missing case-level review evidence.
- The historical lead-outcome candidate reports 76% chronological holdout
  accuracy (76/100), below the 85% target; it is not deployed.
- The 95.6% synthetic prototype result is based on synthetic labels and is not
  production or acceptance evidence.
- Current application lead scoring is rule-based, not a validated predictive
  model. A human-reviewed labeled evaluation set is still needed for a quality
  or accuracy sign-off.

### Database and migrations

- Applied migrations to an isolated temporary SQLite database.
- Current revision: `0003_milestone3_conversations_crm` (`head`).
- `alembic check`: **No new upgrade operations detected**, exit code 0.
- Migration tests verified schema creation, constraints, downgrade behavior, and persistence-related database behavior.

Alembic/SQLAlchemy emitted warnings because SQLite cannot reflect the expression-based normalized-email indexes for drift comparison. The check still exited successfully; duplicate handling and constraints are also covered by tests.

## Environment and limitations

| Capability | Result |
|---|---|
| Python | 3.13.5 |
| Test runner | pytest 8.4.2 |
| Node.js | Available, v22.17.0 |
| Docker | Unavailable; `docker info` exit code 1, Docker Desktop engine pipe not found |
| PostgreSQL test database | Not configured (`TEST_DATABASE_URL` unset) |
| Ollama | Reachable for live synthetic provider checks |
| Browser | Integrated browser available and used; local Playwright Chromium cache missing |

PostgreSQL parity remains unverified. Rerun the PostgreSQL integration test
with Docker Desktop running or a configured isolated PostgreSQL
`TEST_DATABASE_URL`. Browser coverage is targeted rather than exhaustive; no
local Playwright browser download was performed.

CRM adapter and failure behavior are covered by automated tests using mocked
provider responses. No live Salesforce or HubSpot account was contacted because
sync can create or update external records. Authentication is not enabled, so
authentication/authorization behavior was not tested.

### Warnings

The successful complete test run reported 27 warnings and no failures. They
were associated with:

- Alembic's `path_separator` setting falling back to legacy parsing.
- SQLite/SQLAlchemy being unable to reflect the expression-based normalized-email indexes for migration-drift comparison.

The migration check returned exit code 0. Normalized uniqueness behavior is
independently covered by database tests; PostgreSQL-specific reflection/parity
was not tested in this run.

### Data safety and cleanup

- All new test records used synthetic `example.test` addresses and fictional company/context values.
- Live AI checks used temporary SQLite storage; UI/API checks used a separate isolated temporary database.
- Temporary runtime database/CSV files were removed and no validation services remain running.
- The repository's `salesgenie.db` and `salesgenie.db.bak` were not used as test databases or modified.

## Re-run commands

```powershell
.\.venv\Scripts\python.exe -m pytest -v
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic check
```

For PostgreSQL integration, set `TEST_DATABASE_URL` to an isolated test database before running the pytest command. Do not point tests at production data.
