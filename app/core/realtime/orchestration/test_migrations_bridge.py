def test_migrations_sql_has_create_table():
    from app.core.realtime import migrations
    assert "CREATE TABLE" in migrations.MIGRATIONS_SQL
