from datetime import datetime, timezone
from sqlalchemy import ForeignKey, String, UniqueConstraint, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Base class for all Sqlalchemy models
class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(128), nullable=False, default="")

class Follow(Base):
    __tablename__ = "follows"

    # Composite primary key
    follower_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
        nullable=False,
    )
    followee_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
        nullable=False,
    )

class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    contents: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False) # Postgres sets timestamp on insert
