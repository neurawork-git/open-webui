import os
import json
import logging
from contextlib import contextmanager
from typing import Any, Optional

from open_webui.internal.wrappers import register_connection
from open_webui.env import (
    OPEN_WEBUI_DIR,
    DATABASE_URL,
    DATABASE_SCHEMA,
    DATABASE_POOL_MAX_OVERFLOW,
    DATABASE_POOL_RECYCLE,
    DATABASE_POOL_SIZE,
    DATABASE_POOL_TIMEOUT,
    DATABASE_ENABLE_SQLITE_WAL,
    DATABASE_ENABLE_SESSION_SHARING,
    ENABLE_DB_MIGRATIONS,
)
from peewee_migrate import Router
from sqlalchemy import Dialect, create_engine, MetaData, event, types
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker, Session
from sqlalchemy.pool import QueuePool, NullPool
from sqlalchemy.sql.type_api import _T
from typing_extensions import Self

log = logging.getLogger(__name__)


class JSONField(types.TypeDecorator):
    impl = types.Text
    cache_ok = True

    def process_bind_param(self, value: Optional[_T], dialect: Dialect) -> Any:
        return json.dumps(value)

    def process_result_value(self, value: Optional[_T], dialect: Dialect) -> Any:
        if value is not None:
            return json.loads(value)

    def copy(self, **kw: Any) -> Self:
        return JSONField(self.impl.length)

    def db_value(self, value):
        return json.dumps(value)

    def python_value(self, value):
        if value is not None:
            return json.loads(value)


# Workaround to handle the peewee migration
# This is required to ensure the peewee migration is handled before the alembic migration
def handle_peewee_migration(DATABASE_URL):
    # db = None
    try:
        # Replace the postgresql:// with postgres:// to handle the peewee migration
        db = register_connection(DATABASE_URL.replace("postgresql://", "postgres://"))
        migrate_dir = OPEN_WEBUI_DIR / "internal" / "migrations"
        router = Router(db, logger=log, migrate_dir=migrate_dir)
        router.run()
        db.close()

    except Exception as e:
        log.error(f"Failed to initialize the database connection: {e}")
        log.warning(
            "Hint: If your database password contains special characters, you may need to URL-encode it."
        )
        raise
    finally:
        # Properly closing the database connection
        if db and not db.is_closed():
            db.close()

        # Assert if db connection has been closed
        assert db.is_closed(), "Database connection is still open."


if ENABLE_DB_MIGRATIONS:
    handle_peewee_migration(DATABASE_URL)


SQLALCHEMY_DATABASE_URL = DATABASE_URL

# Handle SQLCipher URLs
if SQLALCHEMY_DATABASE_URL.startswith("sqlite+sqlcipher://"):
    database_password = os.environ.get("DATABASE_PASSWORD")
    if not database_password or database_password.strip() == "":
        raise ValueError(
            "DATABASE_PASSWORD is required when using sqlite+sqlcipher:// URLs"
        )

    # Extract database path from SQLCipher URL
    db_path = SQLALCHEMY_DATABASE_URL.replace("sqlite+sqlcipher://", "")

    # Create a custom creator function that uses sqlcipher3
    def create_sqlcipher_connection():
        import sqlcipher3

        conn = sqlcipher3.connect(db_path, check_same_thread=False)
        conn.execute(f"PRAGMA key = '{database_password}'")
        return conn

    engine = create_engine(
        "sqlite://",  # Dummy URL since we're using creator
        creator=create_sqlcipher_connection,
        echo=False,
    )

    log.info("Connected to encrypted SQLite database using SQLCipher")

elif "sqlite" in SQLALCHEMY_DATABASE_URL:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
    )

    def on_connect(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        if DATABASE_ENABLE_SQLITE_WAL:
            cursor.execute("PRAGMA journal_mode=WAL")
        else:
            cursor.execute("PRAGMA journal_mode=DELETE")
        cursor.close()

    event.listen(engine, "connect", on_connect)
else:
    if isinstance(DATABASE_POOL_SIZE, int):
        if DATABASE_POOL_SIZE > 0:
            engine = create_engine(
                SQLALCHEMY_DATABASE_URL,
                pool_size=DATABASE_POOL_SIZE,
                max_overflow=DATABASE_POOL_MAX_OVERFLOW,
                pool_timeout=DATABASE_POOL_TIMEOUT,
                pool_recycle=DATABASE_POOL_RECYCLE,
                pool_pre_ping=True,
                poolclass=QueuePool,
            )
        else:
            engine = create_engine(
                SQLALCHEMY_DATABASE_URL, pool_pre_ping=True, poolclass=NullPool
            )
    else:
        engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True)


SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
)
metadata_obj = MetaData(schema=DATABASE_SCHEMA)
Base = declarative_base(metadata=metadata_obj)
ScopedSession = scoped_session(SessionLocal)


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


get_db = contextmanager(get_session)


@contextmanager
def get_db_context(db: Optional[Session] = None):
    if isinstance(db, Session) and DATABASE_ENABLE_SESSION_SHARING:
        yield db
    else:
        with get_db() as session:
            yield session


class SchemaValidationError(Exception):
    """Raised when database schema doesn't match SQLAlchemy models."""
    pass


def validate_model_schema(model_class, db: Optional[Session] = None) -> list[str]:
    """
    Validate that a SQLAlchemy model's columns exist in the actual database.

    Args:
        model_class: SQLAlchemy model class to validate
        db: Optional database session

    Returns:
        List of error messages (empty if validation passes)

    This catches issues like:
    - Column renamed in model but not in DB
    - Column added to model but migration not run
    - Migration file differs from what was actually applied
    """
    from sqlalchemy import inspect

    errors = []
    table_name = model_class.__tablename__

    with get_db_context(db) as session:
        inspector = inspect(session.bind)
        tables = inspector.get_table_names()

        # Check table exists
        if table_name not in tables:
            errors.append(f"Table '{table_name}' does not exist in database")
            return errors

        # Get actual DB columns
        db_columns = {col['name'] for col in inspector.get_columns(table_name)}

        # Get model columns
        model_columns = {col.name for col in model_class.__table__.columns}

        # Check for missing columns (critical - will cause runtime errors)
        missing_in_db = model_columns - db_columns
        for col in missing_in_db:
            errors.append(
                f"CRITICAL: Column '{col}' exists in model '{model_class.__name__}' "
                f"but not in database table '{table_name}'. "
                f"Run migrations or manually add the column."
            )

    return errors


def validate_all_schemas(fail_fast: bool = True) -> dict[str, list[str]]:
    """
    Validate all registered SQLAlchemy models against the database schema.

    Args:
        fail_fast: If True, raise SchemaValidationError on first error.
                   If False, collect all errors and return them.

    Returns:
        Dict mapping model names to lists of error messages

    Raises:
        SchemaValidationError: If fail_fast=True and any validation fails
    """
    # Import models that need validation
    # Add new models here as they are created
    from open_webui.models.processing import ProcessingTask

    models_to_validate = [
        ProcessingTask,
        # Add other critical models here
    ]

    all_errors = {}

    for model in models_to_validate:
        errors = validate_model_schema(model)
        if errors:
            all_errors[model.__name__] = errors
            if fail_fast:
                error_msg = "\n".join(errors)
                raise SchemaValidationError(
                    f"Database schema validation failed for {model.__name__}:\n{error_msg}\n\n"
                    f"This usually means a migration was not run or column was renamed.\n"
                    f"Fix: Run 'alembic upgrade head' or check your migration files."
                )

    if all_errors:
        log.error(f"Schema validation found {len(all_errors)} models with issues")
        for model_name, errors in all_errors.items():
            for error in errors:
                log.error(f"  {model_name}: {error}")

    return all_errors
