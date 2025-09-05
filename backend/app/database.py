import os
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

# Load environment variables from .env
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set in environment variables")

# Create the database engine (new database connection)
engine = create_async_engine(DATABASE_URL, echo=True)

# Factory for creating new database sessions
AsyncSessionLocal = async_sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

# Provides a session for each request
async def get_db_async():
    async with AsyncSessionLocal() as session:
        yield session
