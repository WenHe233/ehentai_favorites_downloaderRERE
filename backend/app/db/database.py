from sqlalchemy import text
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

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()

async def get_db():
    async with SessionLocal() as session:
        yield session

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
