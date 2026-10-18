from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.database import create_database_engine
from db.models import CompanyInsight, Lead


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_TABLES = {
    "leads",
    "company_insights",
    "lead_scores",
    "outreach_drafts",
    "activities",
    "conversation_summaries",
    "import_batches",
    "agent_runs",
}


class DatabaseMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.db"
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"
        self.previous_database_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = self.database_url

        config = Config(str(ROOT / "alembic.ini"))
        command.upgrade(config, "head")
        self.engine = create_database_engine(self.database_url)

    def tearDown(self) -> None:
        self.engine.dispose()
        if self.previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = self.previous_database_url
        self.temp_dir.cleanup()

    def test_migration_creates_the_eight_tables(self) -> None:
        tables = set(inspect(self.engine).get_table_names()) - {"alembic_version"}
        self.assertEqual(tables, EXPECTED_TABLES)

    def test_normalized_email_is_unique(self) -> None:
        with Session(self.engine) as session:
            session.add(
                Lead(
                    company_name="Example",
                    contact_name="Jamie Lee",
                    email="Jamie@Example.test",
                )
            )
            session.commit()
            session.add(
                Lead(
                    company_name="Another Example",
                    contact_name="Jamie Lee",
                    email=" jamie@example.test ",
                )
            )
            with self.assertRaises(IntegrityError):
                session.commit()

    def test_fallback_duplicate_is_unique_when_email_is_missing(self) -> None:
        with Session(self.engine) as session:
            session.add(
                Lead(company_name="Example Inc.", contact_name="Jamie Lee")
            )
            session.commit()
            session.add(
                Lead(company_name=" example inc. ", contact_name=" jamie lee ")
            )
            with self.assertRaises(IntegrityError):
                session.commit()

    def test_deleting_a_lead_cascades_its_insight(self) -> None:
        with self.engine.begin() as connection:
            lead_id = connection.execute(
                Lead.__table__.insert()
                .values(company_name="Example")
                .returning(Lead.lead_id)
            ).scalar_one()
            connection.execute(
                CompanyInsight.__table__.insert().values(
                    lead_id=lead_id, summary="Synthetic insight"
                )
            )
            connection.execute(Lead.__table__.delete().where(Lead.lead_id == lead_id))
            remaining = connection.exec_driver_sql(
                "SELECT COUNT(*) FROM company_insights WHERE lead_id = ?",
                (lead_id,),
            ).scalar_one()
        self.assertEqual(remaining, 0)


if __name__ == "__main__":
    unittest.main()
