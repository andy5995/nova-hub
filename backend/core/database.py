"""
Database session management for Nova Hub

Handles database initialization and provides session dependencies for FastAPI.
"""

from typing import Generator, Optional

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

# Database engine and session factory
engine = None
SessionLocal = None


def init_database(database_url: str) -> any:
    """
    Initialize database connection

    Args:
        database_url: SQLAlchemy database URL (e.g., "sqlite:////path/to/db.db")

    Returns:
        SQLAlchemy engine instance
    """
    global engine, SessionLocal

    connect_args = {}
    if "sqlite" in database_url:
        connect_args["check_same_thread"] = False

    engine = create_engine(database_url, connect_args=connect_args)
    if "sqlite" in database_url:
        event.listen(engine, "connect", sqlite_pragmas)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    return engine


def sqlite_pragmas(dbapi_connection, _record) -> None:
    """What SQLite leaves off on every new connection.

    foreign_keys: without it every REFERENCES and ON DELETE in the schema is
    decoration. WAL: readers (every client poll) no longer wait on a writer (a
    processing run, the retention pass). busy_timeout: a writer waits its turn
    rather than failing with "database is locked".

    Only the hub's own engine. Alembic makes its own, and must not have
    foreign keys on: a batch migration rebuilds a table by dropping it.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency for database sessions

    Yields a database session and ensures it's closed after the request.

    Usage:
        @app.get("/items")
        def get_items(db: Session = Depends(get_db)):
            return db.query(Item).all()
    """
    if SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session() -> Session:
    """
    Get a database session directly (for non-FastAPI usage)

    Remember to close the session when done!

    Usage:
        db = get_session()
        try:
            # do stuff
        finally:
            db.close()
    """
    if SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")

    return SessionLocal()
