from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def migrate_database(engine: Engine) -> None:
    inspector = inspect(engine)
    if "chart_data" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("chart_data")}
    statements: list[str] = []
    if "name" not in columns:
        statements.append("ALTER TABLE chart_data ADD COLUMN name VARCHAR(160)")
    if "password_hash" not in columns:
        statements.append("ALTER TABLE chart_data ADD COLUMN password_hash VARCHAR(256)")
    if "key_bindings_json" not in columns:
        statements.append(
            "ALTER TABLE chart_data ADD COLUMN key_bindings_json TEXT "
            "DEFAULT '[\"KeyD\",\"KeyF\",\"KeyJ\",\"KeyK\"]'"
        )

    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
