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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Auto-migration: add username/password_hash columns if missing
        await conn.run_sync(_migrate_users_table)


def _migrate_users_table(conn):
    """Add username + password_hash columns to users table if they don't exist."""
    import sqlite3
    raw = conn.connection.connection  # unwrap sync sqlite3 connection
    cursor = raw.execute("PRAGMA table_info(users)")
    columns = {row[1] for row in cursor.fetchall()}
    if "username" not in columns:
        raw.execute('ALTER TABLE users ADD COLUMN username VARCHAR(50) NOT NULL DEFAULT ""')
        raw.execute('CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username)')
    if "password_hash" not in columns:
        raw.execute('ALTER TABLE users ADD COLUMN password_hash VARCHAR(128) NOT NULL DEFAULT ""')
    raw.commit()


async def get_session() -> AsyncSession:
    """Dependency: yield an async session."""
    async with async_session() as session:
        yield session


# Model imports moved to orm/models.py to avoid circular imports
