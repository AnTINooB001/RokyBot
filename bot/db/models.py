# bot/db/models.py

import datetime
from typing import Annotated
import enum

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    String,
    Float,
    Enum,  # <-- ИМПОРТИРУЕМ ОБЫЧНЫЙ Enum
    func
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Типы колонок остаются без изменений, они уже универсальны
int_pk = Annotated[int, mapped_column(primary_key=True)]
user_fk = Annotated[int, mapped_column(ForeignKey("users.id", ondelete="CASCADE"))]
created_at = Annotated[datetime.datetime, mapped_column(default=func.now())]
processed_at = Annotated[datetime.datetime, mapped_column(nullable=True, onupdate=func.now())]


class Base(DeclarativeBase):
    """Базовая модель для всех таблиц."""
    pass


class VideoStatus(enum.Enum):
    ACCEPTED = "принято"
    REJECTED = "отклонено"


class PayoutStatus(enum.Enum):
    PENDING = "ожидание"
    PAID = "выплачено"
    CANCELLED = "отменено"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int_pk]
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None]
    wallet: Mapped[str | None]
    balance: Mapped[float] = mapped_column(Float, default=0.0)
    subscribed: Mapped[bool] = mapped_column(default=False)
    registered_at: Mapped[created_at] 
    is_banned: Mapped[bool] = mapped_column(default=False, server_default="false", index=True)

    videos: Mapped[list["Video"]] = relationship(back_populates="user")
    video_history: Mapped[list["VideoHistory"]] = relationship(back_populates="user")
    payouts: Mapped[list["Payout"]] = relationship(back_populates="user")


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int_pk]
    user_id: Mapped[user_fk]
    link: Mapped[str]
    created_at: Mapped[created_at]

    user: Mapped["User"] = relationship(back_populates="videos")


class VideoHistory(Base):
    __tablename__ = "video_history"

    id: Mapped[int_pk]
    user_id: Mapped[user_fk]
    link: Mapped[str]
    # --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
    # Заменяем PgEnum на универсальный Enum
    status: Mapped[VideoStatus] = mapped_column(Enum(VideoStatus, native_enum=False))
    reason: Mapped[str | None]
    admin_tg_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime.datetime]
    processed_at: Mapped[processed_at]

    user: Mapped["User"] = relationship(back_populates="video_history")


class Payout(Base):
    __tablename__ = "payouts"

    id: Mapped[int_pk]
    user_id: Mapped[user_fk]
    amount: Mapped[float] = mapped_column(Float)
    wallet: Mapped[str]
    # --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
    # Заменяем PgEnum на универсальный Enum
    status: Mapped[PayoutStatus] = mapped_column(
        Enum(PayoutStatus, name="payout_status_enum", native_enum=False), 
        default=PayoutStatus.PENDING, 
        index=True
    )
    admin_tg_id: Mapped[int | None] = mapped_column(BigInteger)
    tx_hash: Mapped[str | None]
    created_at: Mapped[created_at]
    processed_at: Mapped[processed_at]

    user: Mapped["User"] = relationship(back_populates="payouts")