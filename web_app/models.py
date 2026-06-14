from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from web_app.database import Base


class Song(Base):
    __tablename__ = "wav_songs"
    __table_args__ = (UniqueConstraint("youtube_url", name="uq_wav_songs_youtube_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    youtube_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    wav_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    charts: Mapped[list["Chart"]] = relationship(
        back_populates="song",
        cascade="all, delete-orphan",
        order_by="Chart.created_at.desc()",
    )


class Chart(Base):
    __tablename__ = "chart_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    song_id: Mapped[int] = mapped_column(ForeignKey("wav_songs.id"), nullable=False)
    name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    key_bindings_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default='["KeyD","KeyF","KeyJ","KeyK"]',
    )
    chart_json: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(64), nullable=False)
    tap_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    hold_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    key_count: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    bpm: Mapped[float] = mapped_column(Float, nullable=False)
    tap_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    hold_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    song: Mapped[Song] = relationship(back_populates="charts")
