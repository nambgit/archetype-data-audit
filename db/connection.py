"""
PostgreSQL database connection and initialization.
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from config.settings import settings

@contextmanager
def get_db_connection():
    """
    Create and return a new PostgreSQL database connection.
    Uses settings from config.settings.
    """
    conn = None
    try:
        conn = psycopg2.connect(
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            dbname=settings.DB_NAME,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            cursor_factory=RealDictCursor
        )
        yield conn
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            conn.close()

def init_db():
    """Initialize schema from file schema.sql."""
    from pathlib import Path
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            schema_path = Path(__file__).parent / "schema.sql"
            cur.execute(schema_path.read_text(encoding="utf-8"))
        conn.commit()
    print(f"✅ PostgreSQL schema initialized on {settings.DB_HOST}/{settings.DB_NAME}")