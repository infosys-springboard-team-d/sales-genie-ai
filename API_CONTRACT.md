# SalesGenie AI — API Contract

**Status:** Implemented and approved per requester confirmation on 24 October 2026; individual approval records are not included in this workspace  
**Version:** 0.1  
**Prepared:** 15 October 2026  
**Base path:** `/api/v1`  
**Related specification:** [SRS.md](./SRS.md)

> The requester confirmed that all team members signed and approved the API contract. Individual names and signature references were not supplied here. The API is intended for local development; it must not be publicly exposed with real lead data before an authentication/security design is implemented and reviewed.

## 1. Conventions

- JSON request and response bodies use `application/json`, except CSV upload.
- Identifiers are integer `lead_id` values.
- Timestamps are ISO 8601 UTC strings.
- Unknown fields and invalid values return a validation error; they are not silently ignored.
- List endpoints return stable pagination metadata.
- Errors use the common envelope below.

### 1.1 Error response

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "The request contains invalid fields.",
    "details": [
      {"field": "email", "message": "Must be a valid email address."}
    ]
  }
}
```

`details` may be an empty array when there are no field-specific details. Do not return secrets, provider credentials, stack traces, or internal database details.

## 2. Lead schema

```json
{
  "lead_id": 123,
  "company_name": "Example Systems",
  "industry": "Software",
  "contact_name": "Jordan Lee",
  "email": "jordan@example.com",
  "phone": "+1-555-0100",
  "lead_status": "New",
  "created_at": "2026-10-15T12:00:00Z",
  "updated_at": "2026-10-15T12:00:00Z"
}
```

`company_name` is required. Other contact/company fields are optional and nullable. The server owns `lead_id`, `created_at`, and `updated_at`; clients must not set them. Blank optional text fields are normalized to null.

Implemented draft `lead_status` values: `New`, `Contacted`, `Qualified`, `Proposal`, `Won`, and `Lost`. Backend and database owners must confirm these values before production use.

## 3. Milestone 1 endpoints

### 3.1 Create lead

`POST /api/v1/leads`

Request:

```json
{
  "company_name": "Example Systems",
  "industry": "Software",
  "contact_name": "Jordan Lee",
  "email": "jordan@example.com",
  "phone": "+1-555-0100"
}
```

Response: `201 Created`, body is the created Lead schema.

Errors: `400` validation failure; `409` duplicate detected using the current draft rule.

### 3.2 List, search, and filter leads

`GET /api/v1/leads`

Query parameters:

| Name | Type | Default | Meaning |
|---|---|---:|---|
| `q` | string | none | Case-insensitive search over company, contact, email, and industry |
| `status` | string | none | Filter by an allowed lifecycle status |
| `page` | integer ≥ 1 | `1` | Page number |
| `page_size` | integer 1–100 | `20` | Maximum records in the page |

Response: `200 OK`.

```json
{
  "items": [],
  "page": 1,
  "page_size": 20,
  "total": 0
}
```

### 3.3 Retrieve lead

`GET /api/v1/leads/{lead_id}`

Response: `200 OK`, body is the Lead schema. Unknown ID: `404 Not Found`.

### 3.4 Update lead

`PATCH /api/v1/leads/{lead_id}`

Request contains one or more editable fields from `company_name`, `industry`, `contact_name`, `email`, and `phone`. `lead_id`, timestamps, and `lead_status` are not editable through this endpoint.

Response: `200 OK`, body is the updated Lead schema. Unknown ID: `404`; invalid fields: `400`.

### 3.5 Update lifecycle status

`PATCH /api/v1/leads/{lead_id}/status`

Request:

```json
{"lead_status": "Qualified"}
```

Response: `200 OK`, body is the updated Lead schema. Unknown ID: `404`; unsupported status: `400`.

### 3.6 Import CSV

`POST /api/v1/leads/import`

Content type: `multipart/form-data`; field name: `file`. CSV header names: `company_name`, `industry`, `contact_name`, `email`, `phone`, `lead_status`. `company_name` is required; if `lead_status` is omitted, it defaults to `New`.

Uploads must be UTF-8 CSV, at most 5 MiB and 10,000 data rows, with unique supported headers.

Import is all-or-nothing. If any row is invalid or duplicated, none of the valid rows in that file are created. The batch result is still persisted with status `failed` and its duplicate/invalid counts.

Response: `200 OK`.

```json
{
  "created": 2,
  "duplicates": 0,
  "rejected": 0,
  "committed": true,
  "duplicate_rows": [],
  "rolled_back_rows": [],
  "row_errors": []
}
```

When the file is rejected, `created` is always zero and `committed` is false. `duplicate_rows` and `rolled_back_rows` contain CSV row numbers (header is row 1); `row_errors` gives duplicate/invalid row details. Valid rows rolled back due to another row's error are not classified as created or rejected. Therefore, `created + duplicates + rejected + len(rolled_back_rows)` equals the nonblank data-row count. `committed` is true only when all nonblank rows passed and were committed.

The approved duplicate rule is normalized email when present, otherwise normalized company name plus contact name. For a no-email incoming row, the fallback check also finds a matching existing lead with an email. For rows within the same CSV, email comparisons use the normalized email; no-email rows use the normalized company/contact pair.

### 3.7 Analyze a lead's company

`POST /api/v1/leads/{lead_id}/analysis`

Request:

```json
{
  "context": "Optional user-supplied company or industry notes."
}
```

`context` is optional. The first milestone uses saved lead fields and supplied context; live web research is not promised by this contract.

Response: `201 Created`.

```json
{
  "analysis_id": 456,
  "lead_id": 123,
  "summary": "Concise generated summary.",
  "potential_needs": ["Example need"],
  "opportunities": ["Example opportunity"],
  "qualification": {
    "score": 80,
    "rationale": "Estimated qualification score based on available lead details and analysis signals; not a predicted conversion probability.",
    "factors": {
      "industry_provided": 15,
      "contact_identified": 15,
      "email_available": 15,
      "phone_available": 10,
      "analysis_summary_available": 10,
      "potential_needs_identified": 15,
      "opportunities_identified": 0
    }
  },
  "created_at": "2026-10-15T12:05:00Z"
}
```

The analysis must be persisted and linked to the requested lead. `qualification.score` is an integer from 0 to 100. Milestone 1 uses an explainable completeness/analysis-signal heuristic; the rationale and factor contributions are returned and persisted. This is not a predicted conversion probability. The requester reports team approval of the 20-case synthetic evaluation set and rubric, 20/20 manageable Ollama flows, and a human accuracy score of 20/20 (100%, meeting the >=95% target). Reviewer identity and per-case review notes were not supplied; see `MILESTONE_1_TEST_REPORT.md` for evidence qualifications.

Errors: `404` unknown lead; `422` invalid request; `502` local AI provider unavailable or invalid response; `503` missing provider configuration or database unavailability. Provider failures must be explicit and must not create a success-shaped analysis record. The API uses the local Ollama server at `OLLAMA_BASE_URL` and the model configured by `OLLAMA_MODEL` (default `llama3.2:latest`); no hosted AI API key is required.

### 3.8 Retrieve the latest saved analysis

`GET /api/v1/leads/{lead_id}/analysis`

Response: `200 OK`, body is the latest analysis schema. Unknown lead: `404`; no analysis exists: `404` with code `ANALYSIS_NOT_FOUND`.

## 4. Future module endpoint proposals

These paths reserve a consistent API shape for the six-module scope. They are not part of the Milestone 1 implementation commitment and require detailed contracts before their milestone starts.

| Module | Proposed endpoint | Milestone |
|---|---|---|
| Outreach generation | `POST /api/v1/leads/{lead_id}/outreach-drafts` | 2 |
| Lead score/recommendation | `POST /api/v1/leads/{lead_id}/scores` and `GET /api/v1/leads/{lead_id}/scores/latest` | 2 |
| Conversation summary | `POST /api/v1/leads/{lead_id}/conversation-summaries` | 3 |
| CRM integration | Vendor-specific integration routes to be agreed | 3 |
| Dashboard analytics | `GET /api/v1/analytics/summary` | 4 |

## 5. Proposed persistence mapping

The eight-table schema keeps the six domain resources below and adds import-batch
and agent-run operational metadata. The database implementation and migration
are in the workspace `db/` and `alembic/` directories. The requester confirms
team approval of this contract and the selected status and duplicate policies.

| Resource | Table | Important fields |
|---|---|---|
| Lead | `leads` | `lead_id`, company/contact fields, `lead_status`, timestamps |
| Analysis | `company_insights` | `analysis_id`, `lead_id` foreign key, result fields, `created_at` |
| Score | `lead_scores` | `score_id`, `lead_id` foreign key, score, rationale, timestamp |
| Outreach draft | `outreach_drafts` | draft ID, `lead_id` foreign key, type, content, timestamp |
| Activity | `activities` | activity ID, `lead_id` foreign key, type, details, timestamp |
| Conversation summary | `conversation_summaries` | summary ID, optional `lead_id` foreign key, summary, key points, actions, timestamp |
| CSV import batch | `import_batches` | Batch ID, status, created/duplicate/rejected counts, row errors, timestamps |
| Agent workflow run | `agent_runs` | Run ID, optional `lead_id`, workflow/status/timing, checkpoint reference, safe error code |

Use database migrations for schema changes. The precise JSON/list storage representation must be tested against both the selected SQLite development configuration and PostgreSQL production configuration.

## 6. Shared decisions to close before coding

1. Approve lifecycle values and duplicate matching rule.
2. Confirm CSV UTF-8 encoding and maximum file/row limits.
3. Approve the transparent estimated qualification rubric (not a conversion prediction).
4. Approve the local Ollama model and provider timeout/retry policy.
5. Approve lead/analysis response types with the Streamlit consumer.
6. Review the FastAPI-generated OpenAPI document at `/openapi.json` whenever endpoint behavior changes.
