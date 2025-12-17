import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    TEACHER = "teacher"
    STUDENT = "student"


class TestDirection(str, enum.Enum):
    TR_TO_UZ = "tr_to_uz"
    UZ_TO_TR = "uz_to_tr"


class TestStatus(str, enum.Enum):
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"
    CANCELLED = "cancelled"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"), default=UserRole.STUDENT, nullable=False
    )
    is_registered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    preferred_cefr_level: Mapped[str | None] = mapped_column(String(4), nullable=True)
    preferred_direction: Mapped[TestDirection | None] = mapped_column(
        Enum(TestDirection, name="preferred_direction"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    test_sessions: Mapped[list["TestSession"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )


class WordList(Base):
    __tablename__ = "word_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    cefr_level: Mapped[str] = mapped_column(
        String(4), nullable=False
    )  # e.g. A1, A2, B1, B2, C1, C2
    topic: Mapped[str | None] = mapped_column(String(128), nullable=True)
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    words: Mapped[list["Word"]] = relationship(
        back_populates="word_list", cascade="all, delete-orphan"
    )


class Word(Base):
    __tablename__ = "words"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    turkish: Mapped[str] = mapped_column(String(128), nullable=False)
    uzbek: Mapped[str] = mapped_column(String(128), nullable=False)
    example_sentence: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    word_list_id: Mapped[int] = mapped_column(
        ForeignKey("word_lists.id", ondelete="CASCADE"), nullable=False
    )

    word_list: Mapped[WordList] = relationship(back_populates="words")
    questions: Mapped[list["TestQuestion"]] = relationship(
        back_populates="word", cascade="all, delete-orphan"
    )


class TestSession(Base):
    __tablename__ = "test_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    cefr_level: Mapped[str] = mapped_column(String(4), nullable=False)
    direction: Mapped[TestDirection] = mapped_column(
        Enum(TestDirection, name="test_direction"), nullable=False
    )
    total_questions: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[TestStatus] = mapped_column(
        Enum(TestStatus, name="test_status"),
        default=TestStatus.IN_PROGRESS,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    student: Mapped[User] = relationship(back_populates="test_sessions")
    questions: Mapped[list["TestQuestion"]] = relationship(
        back_populates="test_session", cascade="all, delete-orphan"
    )


class TestQuestion(Base):
    __tablename__ = "test_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    test_session_id: Mapped[int] = mapped_column(
        ForeignKey("test_sessions.id", ondelete="CASCADE"), nullable=False
    )
    word_id: Mapped[int] = mapped_column(
        ForeignKey("words.id", ondelete="CASCADE"), nullable=False
    )

    # Language shown to student: "tr" or "uz"
    shown_lang: Mapped[str] = mapped_column(String(2), nullable=False)
    correct_answer: Mapped[str] = mapped_column(String(128), nullable=False)

    student_answer: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    skipped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    test_session: Mapped[TestSession] = relationship(back_populates="questions")
    word: Mapped[Word] = relationship(back_populates="questions")


