from paper_trader.persistence.state_store import _with_psycopg2_driver


def test_forces_psycopg2_driver_on_bare_postgresql_url():
    assert _with_psycopg2_driver("postgresql://user:pw@host/db") == "postgresql+psycopg2://user:pw@host/db"


def test_forces_psycopg2_driver_on_postgres_scheme():
    assert _with_psycopg2_driver("postgres://user:pw@host/db") == "postgresql+psycopg2://user:pw@host/db"


def test_leaves_already_qualified_driver_untouched():
    url = "postgresql+psycopg2://user:pw@host/db"
    assert _with_psycopg2_driver(url) == url


def test_leaves_sqlite_url_untouched():
    assert _with_psycopg2_driver("sqlite:///paper_trader.db") == "sqlite:///paper_trader.db"
