from app.core.config import normalize_database_url


def test_neon_postgresql_urls_use_the_installed_psycopg_driver():
    assert normalize_database_url(
        "postgresql://user:password@host/db?sslmode=require"
    ) == "postgresql+psycopg://user:password@host/db?sslmode=require"
    assert normalize_database_url(
        "postgres://user:password@host/db?sslmode=require"
    ) == "postgresql+psycopg://user:password@host/db?sslmode=require"


def test_other_database_urls_are_preserved():
    url = "postgresql+psycopg://user:password@host/db?sslmode=require"
    assert normalize_database_url(url) == url
    assert normalize_database_url("sqlite:///./repopilot.db") == "sqlite:///./repopilot.db"
