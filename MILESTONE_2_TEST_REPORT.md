# SalesGenie AI — Milestone 2 Test Report

**Verification date:** 3 November 2026

**Scope:** Outreach generation, saved/editable drafts, lead scoring, activity capture, and next-best-action recommendations

**Workbook:** [TEAM D BATCH 4](https://docs.google.com/spreadsheets/d/1a_k0FYmsKhfPN8tGY0Cw-dsvQ_kb5ktuE3wYSsK9tSg/edit?gid=1260369314#gid=1260369314), `Module Task Breakdown` and `40-Day Schedule` tabs

## Implementation delivered

- Ollama-backed email and message draft generation using selected tone, length,
  goal, lead details, and user-supplied pain points.
- Evidence-guided outreach prompting with a concrete style example and a
  required non-empty subject for email drafts.
- Saved drafts linked to leads; list, edit, regenerate, copy/download, and open
  email drafts in the user's local email client after review. The application
  does not send emails.
- Persisted activities to provide explicit engagement data for scoring.
- A transparent, rule-based 0–100 estimate with fit, engagement, intent, and
  decision-readiness factor contributions and a persisted next-best-action
  recommendation.
- Streamlit Outreach Strategy UI and documented API routes.
- Alembic revision `0002_milestone2_recommendations` to persist
  recommendations with lead scores.

## Automated verification

| Check | Result |
|---|---|
| SQLite API, provider, and database test suite | **24 passed, 1 PostgreSQL-only test skipped**; rerun 3 November |
| Draft generation/list/edit API flow | Pass; deterministic provider test |
| Provider failure behavior | Pass; returns explicit error and saves no draft |
| Scoring factors and recommendation persistence | Pass |
| Activity creation and engagement contribution | Pass |
| Milestone 1 analysis retrieval after a Milestone 2 score is created | Pass |
| Migration upgrade | Pass as part of the SQLite migration tests |
| Live Ollama draft generation | **2 synthetic examples passed** after prompt tuning; see below |
| Email-client handoff | Not run; the application does not send email |

## Live outreach prompt check

On 3 November 2026, the configured local `llama3.2:latest` model generated
drafts for two synthetic leads in different industries: B2B software
(Northstar Analytics) and manufacturing (Cedar Works). Both drafts included a
non-empty subject tied to the supplied pain point, cautiously referenced the
user-provided note, and used a discovery question and low-pressure call to
action. The prompt now uses a grounded style example, and the email response
schema requires a subject.

This is a two-example functional check, not a human quality review or evidence
of scoring accuracy. Generated text remains subject to salesperson review;
cross-industry human acceptance is still pending.

Run the automated suite from the workspace root:

```powershell
python -m pytest db\tests -q
```

## Accuracy and sign-off status

The shared schedule specifies a Milestone 2 scoring accuracy target of at least
85%, but no labeled scoring outcomes, acceptance rubric, or case-level expected
labels were supplied. The implemented score is therefore a transparent
rule-based baseline, not a trained or calibrated conversion-probability model.
Automated unit/API tests verify deterministic behavior and persistence; they
do **not** establish 85% predictive accuracy. The scoring-accuracy criterion
remains **unverified** until the team supplies and reviews an agreed labeled
test set.

The project workbook also calls for cross-industry outreach review, a demo,
test report review, and Milestone 2 sign-off. Automated API/provider tests are
complete; human review, live-model review, demo, and sign-off remain team
activities and are not represented as completed here.

## Limitations

- Authentication is not implemented; continue to bind local services to
  localhost and use synthetic or approved sample data.
- Email is not delivered by the application. The email-client handoff requires
  the user to review and send.
- No PostgreSQL run was performed for this milestone in this environment.
- A labeled score evaluation set and rubric are needed before the 85% target
  can be evaluated or claimed.
