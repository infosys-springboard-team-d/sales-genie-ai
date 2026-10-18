from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine


def create_database_engine(database_url: str, **engine_options: Any) -> Engine:
    engine = create_engine(database_url, **engine_options)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def enable_sqlite_foreign_keys(connection, _record) -> None:
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine
