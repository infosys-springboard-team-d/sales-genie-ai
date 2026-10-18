from logging.config import fileConfig
import os
import re

from alembic import context
from dotenv import load_dotenv
from db.database import create_database_engine
from db.models import Base
from sqlalchemy.pool import NullPool


load_dotenv()
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

target_metadata = Base.metadata
NORMALIZED_LEAD_INDEXES = {
    "uq_leads_email_normalized",
    "uq_leads_company_contact_without_email",
}


def _normalize_index_sql(value: object) -> str:
    expression = str(value).lower()
    expression = re.sub(
        r"trim\s*\(\s*both\s+from\s+([a-z_]+)\s*\)",
        r"trim(\1)",
        expression,
    )
    expression = expression.replace("::text", "")
    return re.sub(r"[()\s]", "", expression)


def include_object(object_, name, type_, reflected, compare_to):
    if type_ != "index" or name not in NORMALIZED_LEAD_INDEXES or reflected:
        return True
    if compare_to is None or bool(object_.unique) != bool(compare_to.unique):
        return True

    inspected_expressions = getattr(compare_to, "expressions", [])
    metadata_expressions = getattr(object_, "expressions", [])
    if len(inspected_expressions) != len(metadata_expressions):
        return True
    if [
        _normalize_index_sql(expression) for expression in inspected_expressions
    ] != [
        _normalize_index_sql(expression) for expression in metadata_expressions
    ]:
        return True

    inspected_condition = compare_to.dialect_options["postgresql"].get("where")
    metadata_condition = object_.dialect_options["postgresql"].get("where")
    if _normalize_index_sql(inspected_condition) != _normalize_index_sql(metadata_condition):
        return True
    return False


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine_options = config.get_section(config.config_ini_section, {})
    database_url = engine_options.pop("sqlalchemy.url")
    connectable = create_database_engine(database_url, poolclass=NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
