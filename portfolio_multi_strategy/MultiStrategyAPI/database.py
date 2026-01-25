"""
Database configuration and session management
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import Base

# Database URL from environment variable
# For local dev: sqlite:///./multistrategy.db
# For production: postgresql://postgres:postgres@postgres:5432/multistrategy
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    # "postgresql://postgres:postgres@postgres:5432/multistrategy"
    "sqlite:///./multistrategy.db"
)

# Create SQLAlchemy engine
engine = create_engine(DATABASE_URL)

# Create SessionLocal class for database sessions
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)


def get_db():
    """
    Dependency function for FastAPI to get database session
    Usage: db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
