import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Load environment variables from .env
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set in environment variables")

# Create the database engine (new database connection)
engine = create_engine(DATABASE_URL, echo=True)

# Factory for creating new database sessions
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

# Provides a session for each request
# Ensures the session is closed after use
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
