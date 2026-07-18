"""SQLAlchemy async engine and session management."""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = "sqlite+aiosqlite:///./data/bazi.db"
engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    """Create all tables + migration. Call at app startup."""
    import os
    os.makedirs("data", exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate)


def _migrate(conn):
    """Add missing columns to users table."""
    try:
        sqlite_conn = conn.connection.connection
        cursor = sqlite_conn.execute("PRAGMA table_info(users)")
        columns = {row[1] for row in cursor.fetchall()}
        if "username" not in columns:
            sqlite_conn.execute('ALTER TABLE users ADD COLUMN username VARCHAR(50) NOT NULL DEFAULT ""')
        if "password_hash" not in columns:
            sqlite_conn.execute('ALTER TABLE users ADD COLUMN password_hash VARCHAR(128) NOT NULL DEFAULT ""')
    except Exception as e:
        print(f"[migration] skip: {e}")


async def get_session() -> AsyncSession:
    """Dependency: yield an async session."""
    async with async_session() as session:
        yield session


# Model imports moved to orm/models.py to avoid circular imports
