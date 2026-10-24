# SalesGenie detailed database ER diagram

This Mermaid diagram shows the tables, columns, SQL types, nullability, keys, and relationships from the initial Alembic migration.

```mermaid
erDiagram
    LEADS {
        int lead_id PK
        varchar_255 company_name
        varchar_120 industry "nullable"
        varchar_255 contact_name "nullable"
        varchar_320 email "nullable, normalized unique"
        varchar_64 phone "nullable"
        varchar_20 lead_status "default New"
        timestamptz created_at
        timestamptz updated_at
    }
    COMPANY_INSIGHTS {
        int analysis_id PK
        int lead_id FK
        text summary
        json potential_needs "default empty list"
        json opportunities "default empty list"
        int qualification_score "nullable, 0 to 100"
        text qualification_rationale "nullable"
        timestamptz created_at
    }
    LEAD_SCORES {
        int score_id PK
        int lead_id FK
        int score "0 to 100"
        text rationale
        json factors "default empty object"
        timestamptz created_at
    }
    OUTREACH_DRAFTS {
        int draft_id PK
        int lead_id FK
        varchar_20 draft_type "email or message"
        text content
        timestamptz created_at
    }
    ACTIVITIES {
        int activity_id PK
        int lead_id FK
        varchar_60 activity_type
        json details "default empty object"
        timestamptz occurred_at
        timestamptz created_at
    }
    CONVERSATION_SUMMARIES {
        int summary_id PK
        int lead_id FK "nullable"
        text summary
        json key_points "default empty list"
        json action_items "default empty list"
        timestamptz created_at
    }
    IMPORT_BATCHES {
        int import_batch_id PK
        varchar_255 filename "nullable"
        varchar_20 status "default processing"
        int created_count "default 0"
        int duplicate_count "default 0"
        int rejected_count "default 0"
        json row_errors "default empty list"
        timestamptz created_at
        timestamptz completed_at "nullable"
    }
    AGENT_RUNS {
        int agent_run_id PK
        int lead_id FK "nullable"
        varchar_100 workflow_name
        varchar_20 status "default queued"
        varchar_40 trigger_type "nullable"
        varchar_255 checkpoint_ref "nullable"
        varchar_80 error_code "nullable"
        timestamptz created_at
        timestamptz started_at "nullable"
        timestamptz completed_at "nullable"
    }

    LEADS ||--o{ COMPANY_INSIGHTS : produces
    LEADS ||--o{ LEAD_SCORES : receives
    LEADS ||--o{ OUTREACH_DRAFTS : has
    LEADS ||--o{ ACTIVITIES : records
    LEADS o|--o{ CONVERSATION_SUMMARIES : summarizes
    LEADS o|--o{ AGENT_RUNS : triggers
```

`import_batches` has no direct foreign-key relationship to `leads`: it records a
CSV import's status, counts, and row errors; successfully imported records are
stored in `leads`. A lead can have zero or many related records. Insights,
scores, outreach drafts, and activities are deleted with a lead. Conversation
summaries and agent-run records remain, with `lead_id` set to `NULL`.

The model and migration define the database constraints in
`alembic/versions/0001_initial_schema.py`. The requester reports team approval
of the selected lifecycle values and duplicate-matching policy; formal
requirements/API sign-off remains pending.
