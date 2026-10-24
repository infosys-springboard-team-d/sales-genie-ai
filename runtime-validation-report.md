# Runtime Validation Report

**Generated:** 2026-10-24  
**Target:** `C:\Users\parvathraj\Downloads\SalesGenie`  
**Scope:** Milestone 1 lead-to-saved-insight workflow

## Summary

| Step | Status | Exit code | Details |
|---|---|---:|---|
| Fresh environment | PASS | 0 | New Python 3.13 virtual environment installed the declared requirements; test suite passed after adding the missing `httpx2` test-client dependency |
| SQLite migrations | PASS | 0 | Isolated database upgraded to `0001_initial`; `alembic check` reported no new operations; current revision is head |
| API/UI startup | PASS | 0 | API `/health` and Streamlit `/_stcore/health` both returned HTTP 200 |
| Integration tests | PASS | 0 | `python -m pytest db\tests -q`: 17 passed, 1 PostgreSQL-only test skipped |
| Browser E2E | PASS | 0 | Leads screen rendered seeded synthetic leads; Ollama analysis appeared in UI and remained visible after reload |
| PostgreSQL | Previously verified | 0 | Earlier PostgreSQL 16 ephemeral-container migration/drift and API run passed; not repeated because Docker Desktop's Linux engine was unavailable |

**Overall:** Core local Milestone 1 workflow passed. The 20-case Ollama evaluation completed 20/20 create/analyze/save/retrieve flows (100% operationally manageable). The requester reports that the team approved the dataset and rubric, that human review scored 20/20 outputs accurate (100%), and that the team walkthrough was completed. These outcomes meet the >=95% target as reported. The reviewer worksheet, reviewer identity, and walkthrough date/results were not supplied, so those outcomes are not independently evidenced here.

The first test run in the new environment failed during collection because Starlette's `TestClient` now requires `httpx2`, which was not declared. The dependency was added to `requirements.txt`; the rerun passed in the fresh environment, as did a second run in the configured environment.

## Environment

- Python: 3.13.5
- Node.js: v22.17.0
- Docker CLI: installed; Docker daemon unavailable (`docker info` could not connect to `//./pipe/dockerDesktopLinuxEngine`)
- Ollama: local service available at `127.0.0.1:11434`; configured `llama3.2:latest` model present
- Browser: integrated browser available and used for the Streamlit user flow
- Test isolation: temporary SQLite database under the session state directory; the project's `salesgenie.db` was not used for the live-model walkthrough
- Test data: fictional synthetic leads and user-supplied fictional context only

## User flow exercised

1. Started the API and Streamlit on isolated ports `18000` and `18501`.
2. Confirmed the Leads screen displayed the seeded leads and initial empty-analysis state.
3. Submitted synthetic context for the selected fictional lead to the local Ollama model.
4. Confirmed the saved analysis rendered with summary, needs, opportunities, and the estimated qualification score.
5. Reloaded the page and confirmed the saved analysis was retrieved and rendered again for the same lead.
6. Retrieved the analysis through the API and confirmed it was linked to the expected lead.

The model's output is generated content, not verified market research. The score is an explainable completeness/analysis-signal heuristic, not conversion probability. Human review against labeled facts is required for any accuracy claim.

## 20-case model evaluation

- Dataset: `resource/milestone_1_ai_evaluation_set.csv` (20 fictional cases).
- Review criteria: `MILESTONE_1_AI_EVALUATION_RUBRIC.md`; requester confirms team approval.
- Model: local Ollama `llama3.2:latest`.
- Result: 20/20 cases successfully created a lead, generated and saved an analysis, and retrieved the same analysis linked to the same lead. Operational manageability: 100% (20/20) under the proposed definition.
- Accuracy: requester reports human review judged 20/20 outputs accurate (100%, above the >=95% threshold). Reviewer identity and case-level notes were not provided. The JSON records this as an aggregate requester-reported result; its per-case `manual_review` entries remain pending because individual worksheet details were not supplied.
- Team walkthrough: requester reports completion; date, run results, and defect dispositions were not provided.
- Full generated outputs and case-level linkage checks: `resource/milestone_1_ai_evaluation_results.json`.

## Capability and coverage gaps

- **Infrastructure tier:** Docker was unavailable, so no new PostgreSQL container test was run. SQLite was used for this run; PostgreSQL 16 results in `MILESTONE_1_TEST_REPORT.md` are prior evidence.
- **Insight accuracy:** Requester reports team approval of the dataset/rubric and a human score of 20/20 (100%). The case-level review worksheet and reviewer identity were not supplied; the result is reported, not independently evidenced.
- **Team acceptance:** Requester confirmed that all team members signed and approved the SRS/API contract and reports that the team walkthrough is complete. Individual names, signature references, walkthrough date/results, and defect dispositions were not supplied.
- **Authentication:** Authentication is intentionally out of Milestone 1 scope; no authentication-failure test was run. Keep the application local and use synthetic data.
- **Repository:** This workspace has no Git metadata; the changes have not been pushed to the supplied remote.

See [MILESTONE_1_TEST_REPORT.md](./MILESTONE_1_TEST_REPORT.md) for the broader historical verification record and acceptance details.
