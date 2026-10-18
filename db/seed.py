from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from db.database import create_database_engine
from db.models import Lead


load_dotenv()
SAMPLE_LEADS = (
    {
        "company_name": "Northstar Analytics",
        "industry": "Software",
        "contact_name": "Casey Morgan",
        "email": "casey.morgan@example.test",
        "phone": "+1-555-0101",
        "lead_status": "New",
    },
    {
        "company_name": "Cedar Ridge Manufacturing",
        "industry": "Manufacturing",
        "contact_name": "Taylor Patel",
        "email": "taylor.patel@example.test",
        "phone": "+1-555-0102",
        "lead_status": "Contacted",
    },
    {
        "company_name": "Blue Harbor Consulting",
        "industry": "Professional Services",
        "contact_name": "Riley Chen",
        "email": "riley.chen@example.test",
        "phone": "+1-555-0103",
        "lead_status": "Qualified",
    },
)


def ensure_local_database(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite":
        return
    if (
        url.get_backend_name() == "postgresql"
        and url.host in {"localhost", "127.0.0.1", "::1"}
        and url.database == "salesgenie_dev"
    ):
        return
    raise ValueError(
        "Synthetic seed data is restricted to SQLite or local PostgreSQL "
        "database salesgenie_dev."
    )


def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "sqlite:///./salesgenie.db")
    ensure_local_database(database_url)
    engine = create_database_engine(database_url)

    with Session(engine) as session, session.begin():
        inserted = 0
        for lead_data in SAMPLE_LEADS:
            email = lead_data["email"]
            exists = session.scalar(
                select(Lead.lead_id).where(
                    func.lower(func.trim(Lead.email)) == email.lower()
                )
            )
            if exists is None:
                session.add(Lead(**lead_data))
                inserted += 1

    print(f"Synthetic lead seed complete; inserted {inserted} new leads.")


if __name__ == "__main__":
    main()
