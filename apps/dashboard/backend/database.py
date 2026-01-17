import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Path to the database from environment or default dev path
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "data/metrics_dev.db")
# For SQLAlchemy async, we need the sqlite+aiosqlite prefix
DATABASE_URL = f"sqlite+aiosqlite:///{SQLITE_DB_PATH}"

# Create engine with WAL-friendly settings
engine = create_async_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_size=20,
    max_overflow=30,
    pool_timeout=30,  # Wait up to 30s for a connection before failing
)

# Async session factory
AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
