from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def migrate_database(engine: Engine) -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    statements: list[str] = []

    if "chart_data" in table_names:
        chart_columns = {
            column["name"] for column in inspector.get_columns("chart_data")
        }
        if "name" not in chart_columns:
            statements.append("ALTER TABLE chart_data ADD COLUMN name VARCHAR(160)")
        if "password_hash" not in chart_columns:
            statements.append(
                "ALTER TABLE chart_data ADD COLUMN password_hash VARCHAR(256)"
            )
        if "key_bindings_json" not in chart_columns:
            statements.append(
                "ALTER TABLE chart_data ADD COLUMN key_bindings_json TEXT "
                "DEFAULT '[\"KeyD\",\"KeyF\",\"KeyJ\",\"KeyK\"]'"
            )

    if "wav_songs" in table_names:
        song_columns = {
            column["name"] for column in inspector.get_columns("wav_songs")
        }
        if "bpm" not in song_columns:
            statements.append("ALTER TABLE wav_songs ADD COLUMN bpm FLOAT")
        if "bpm_confidence" not in song_columns:
            statements.append(
                "ALTER TABLE wav_songs ADD COLUMN bpm_confidence FLOAT"
            )
        if "bpm_source" not in song_columns:
            statements.append(
                "ALTER TABLE wav_songs ADD COLUMN bpm_source VARCHAR(64)"
            )
        if "bpm_ambiguous" not in song_columns:
            statements.append(
                "ALTER TABLE wav_songs ADD COLUMN bpm_ambiguous BOOLEAN"
            )

    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
