import asyncio

from anyio import CancelScope
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

# Ensure data directory exists (handled by Settings validator, but good to be safe)
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False}, # Needed for SQLite
    echo=False,
)


class SafeAsyncSession(AsyncSession):
    async def execute(self, *args, **kwargs):
        with CancelScope(shield=True):
            return await super().execute(*args, **kwargs)

    async def commit(self) -> None:
        with CancelScope(shield=True):
            await super().commit()

    async def rollback(self) -> None:
        with CancelScope(shield=True):
            await super().rollback()

    async def flush(self, objects=None) -> None:
        with CancelScope(shield=True):
            await super().flush(objects)

    async def close(self) -> None:
        with CancelScope(shield=True):
            await super().close()

    async def invalidate(self) -> None:
        with CancelScope(shield=True):
            await super().invalidate()


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    class_=SafeAsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


def _is_ignorable_session_close_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return (
        "no active connection" in message
        or "cannot operate on a closed database" in message
        or "closed database" in message
    )


async def close_session_safely(session: AsyncSession) -> None:
    try:
        current_task = asyncio.current_task()
        if current_task and current_task.cancelling():
            await session.invalidate()
        else:
            await session.close()
    except asyncio.CancelledError:
        return
    except OperationalError as exc:
        if _is_ignorable_session_close_error(exc):
            return
        raise
    except ValueError as exc:
        if _is_ignorable_session_close_error(exc):
            return
        raise


async def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        await close_session_safely(session)

async def init_models():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_lightweight_migrations(conn)


async def _run_lightweight_migrations(conn) -> None:
    def sync_migrate(sync_conn):
        table_names = {
            row[0]
            for row in sync_conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
        if "galleries" not in table_names:
            return

        columns = {
            row[1]
            for row in sync_conn.execute(text("PRAGMA table_info(galleries)"))
        }
        if "favcat" not in columns:
            sync_conn.execute(text("ALTER TABLE galleries ADD COLUMN favcat INTEGER"))
        if "requested_quality" not in columns:
            sync_conn.execute(text("ALTER TABLE galleries ADD COLUMN requested_quality TEXT"))
        if "resolved_quality" not in columns:
            sync_conn.execute(text("ALTER TABLE galleries ADD COLUMN resolved_quality TEXT"))

    await conn.run_sync(sync_migrate)
