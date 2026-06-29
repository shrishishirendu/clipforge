"""B1: confirm the seven core entities (architecture §5) map to seven tables and
that the schema is creatable. Runs against in-memory SQLite so it needs no live
Postgres — it verifies the models, which the Alembic migration is generated from."""
from sqlalchemy import create_engine, inspect

from app.models import Base

# The seven core entities, per technical-architecture §5.
EXPECTED_TABLES = {
    "projects",
    "media_assets",
    "transcripts",
    "key_points",
    "clip_lists",
    "segments",
    "render_jobs",
}


def test_models_define_exactly_the_seven_core_tables():
    assert set(Base.metadata.tables.keys()) == EXPECTED_TABLES


def test_schema_is_creatable():
    """create_all proves the mapped schema is internally consistent (FKs, types)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    created = set(inspect(engine).get_table_names())
    assert EXPECTED_TABLES <= created
