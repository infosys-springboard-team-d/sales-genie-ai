# SalesGenie AI — Sprint 1 Backlog

**Status:** Core implementation, reported team approvals, evaluation, and walkthrough are complete per requester confirmation; repository publication remains open (24 October 2026)  
**Planning window:** 12–20 October 2026  
**Prepared:** 15 October 2026  
**Milestone goal:** Deliver a reliable lead creation-to-saved-company-insight flow  
**Repository supplied:** `https://github.com/230701224/sales-genie-ai.git`

> The updated task rows assign kickoff/SRS to the Project Lead + Full Team, and API/stack/repository/environment planning to the Project Lead + Backend Developer + Database/DevOps Engineer. The backlog therefore assigns by role, not by individual name. The older milestone plan's individual mapping should not override the updated sheet without team confirmation.

## 1. Sprint outcome

A user can create or import a sample lead, retrieve/search/update it, request company analysis, and view the saved analysis against the same lead. The team can run the agreed local setup and demonstrate the flow. Test evidence includes the agreed test-set denominator and result.

## 2. Backlog items

| ID | Priority | Work item | Owner role(s) | Acceptance criteria | Status |
|---|---|---|---|---|---|
| SG-01 | P0 | Review scope and approve SRS | Project Lead + Full Team | Six modules and Milestone 1 scope are reviewed; decisions/open questions are recorded; sign-off table is completed by team members | Approved per requester confirmation on 24 October 2026; individual names/signature references were not supplied and are not fabricated |
| SG-02 | P0 | Agree architecture, lead fields, and database model | Project Lead + Backend Developer + Database/DevOps Engineer | Shared lead/analysis fields, status values, foreign keys, SQLite/PostgreSQL behavior, and migration approach are approved | Eight-table schema implemented; SQLite migration/drift and API tests pass; PostgreSQL 16 migration/API parity passed previously; approval confirmed by requester |
| SG-03 | P0 | Finalize technology baseline | Project Lead + Backend Developer + Database/DevOps Engineer | Python/FastAPI/Streamlit/SQLAlchemy/Alembic, SQLite dev/PostgreSQL production, local Ollama provider, and exact model/version follow-ups are recorded | Approved per requester confirmation; `llama3.2:latest` is installed and local analysis/UI persistence was verified using synthetic data |
| SG-04 | P0 | Approve API contracts | Backend Developer + Project Lead + Database/DevOps Engineer | Create/list/get/update/status/import/analysis contracts and common errors are agreed and captured in OpenAPI | Contract approved per requester confirmation; current OpenAPI implementation is covered by the test suite |
| SG-05 | P0 | Establish repository and branching workflow | Project Lead + Backend Developer + Database/DevOps Engineer | Access to supplied remote is verified; `main`/`develop` policy and feature-branch/PR rules are agreed; secrets are excluded | Supplied remote was found to contain only a one-line README; workspace has no Git metadata; checkout/branch details and publication remain unresolved |
| SG-06 | P0 | Prepare repeatable local development and Docker baseline | Database/DevOps Engineer + Backend Developer | Setup works on a clean Windows machine; documented app ports, database config, sample data, and Docker/local DB workflow are validated | Fresh Python 3.13 virtual environment dependency installation, isolated SQLite migrations/tests, and API/UI startup verified on this workstation; Docker daemon unavailable, so Compose and a separate team clean-machine walkthrough remain unverified |
| SG-07 | P1 | Implement lead schema, migration, and synthetic seed data | Database/DevOps Engineer + Backend Developer | Migration applies to the agreed databases; seed data can be loaded repeatably and contains no real customer data | Eight-table schema/migration and repeatable seed implemented; SQLite and ephemeral PostgreSQL 16 migrations/drift checks passed; three-row synthetic seed verified |
| SG-08 | P1 | Implement lead CRUD, search, status, and validation API | Backend Developer | Contracted endpoints pass create/read/update/search/status tests; invalid input and unknown IDs return explicit errors | Implemented; API tests cover CRUD/search/status, validation, duplicate rules, and missing IDs |
| SG-09 | P1 | Implement manual and CSV import with duplicate reporting | Backend Developer + Database/DevOps Engineer | Valid rows are created, duplicate/invalid rows are reported, and the outcome counts reconcile | Implemented with requester-selected all-or-nothing behavior; tests verify atomic rollback, row numbers, batch counts, and valid-file commit |
| SG-10 | P1 | Implement and persist company analysis | Backend Developer + AI/Analysis role | Analysis uses agreed inputs, returns the agreed shape, stores against the correct lead, and provider errors do not appear as success | Ollama `llama3.2:latest` provider, saved insight, and explainable heuristic implemented; automated tests and live UI/API save/retrieve pass; generated insight quality is not yet measured against labeled ground truth |
| SG-11 | P1 | Connect Leads screen to the API | Frontend role + Backend Developer | User can add, search, inspect, update status, analyze, and view saved insights | Leads, Add Lead, and CSV Import screens implemented; browser smoke verified list and saved Ollama insight display after reload; prior browser smoke also verified create, field clearing, and atomic duplicate reporting |
| SG-12 | P1 | Run tests, record evidence, rehearse demo, and report risks | Project Lead + Full Team | Results report denominator and outcome against the sheet's >=95% manageable-record/insight-accuracy target; defects have owners/disposition; demo uses approved synthetic data | 24 October SQLite run: 17 passed/1 PostgreSQL-only skipped; PostgreSQL 16 14 passed in earlier parity run; Ollama flow 20/20 manageable; requester reports team-approved dataset/rubric, 20/20 human-reviewed accuracy, and completed team walkthrough. Reviewer worksheet, reviewer identity, walkthrough date/results, and defect dispositions were not supplied; see runtime report |

## 3. Suggested sequencing

1. Close SG-01 through SG-04 first; these define shared scope, data shape, and endpoint contracts.
2. SG-05 and SG-06 establish repeatable collaboration and local execution. Do not put populated `.env` files or API keys in Git.
3. SG-07 must be ready before database-backed CRUD and analysis integration.
4. SG-08 and SG-09 provide leads for SG-10/SG-11.
5. Complete SG-12 against the integrated flow and record evidence before submission.

The source milestone plan sets 19 October as demo/rehearsal and 20 October as submission/sign-off. The requester confirms that team members signed and approved the SRS/API contract and reports the team walkthrough was completed. The requester also reports approval of the 20-case set/rubric and 20/20 accurate human-reviewed outputs. Reviewer worksheet and walkthrough details were not supplied; outcomes are recorded as reported.

## 4. Risks and dependencies

- **Repository/source alignment:** the public remote currently contains only a one-line README, while the application implementation is in this non-Git workspace. Coordinate import/reconciliation before pushing or opening a PR.
- **Acceptance evidence:** requester reports team approval of the dataset/rubric, a 20/20 human accuracy result, and completion of the walkthrough. The reviewer worksheet, reviewer identity, walkthrough date/results, and defect dispositions were not supplied.
- **AI output quality:** the requester-reported evaluation meets the 95% threshold; generated insights remain advisory and should be verified before operational use.
- **Human acceptance:** requester replied "ok" regarding the clean-machine walkthrough/demo rehearsal, but no date, run results, or defect dispositions were supplied. Reported SRS/API approval is recorded; individual signature evidence was not supplied.
- **Repository/source alignment:** reconcile this workspace with the remote only after the correct checkout/branch workflow is supplied; do not overwrite or push unreviewed work.
- **Data/privacy:** use synthetic sample records in demos and tests; protect keys and any real prospect data.
