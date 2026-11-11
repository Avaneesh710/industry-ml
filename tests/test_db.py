from industry_ml.db import get_connection, read_sql


def test_can_connect():
    with get_connection() as conn:
        assert conn.execute("SELECT 1").fetchone() == (1,)


def test_schemas_exist():
    df = read_sql(
        "SELECT schema_name FROM information_schema.schemata "
        "WHERE schema_name = ANY(%(names)s)",
        {"names": ["raw", "features", "results"]},
    )
    assert set(df["schema_name"]) == {"raw", "features", "results"}