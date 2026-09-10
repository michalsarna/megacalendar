"""Persistent project definition. Colours are stored as JSON {"c","m","y","k"} in percent."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))

    page_size: Mapped[str] = mapped_column(String(10), default="A1", nullable=False)
    orientation: Mapped[str] = mapped_column(String(10), default="portrait", nullable=False)
    margin_mm: Mapped[float] = mapped_column(Float, default=10.0, nullable=False)
    locale: Mapped[str] = mapped_column(String(20), default="en", nullable=False)
    week_start: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    font_family: Mapped[str] = mapped_column(String(100), default="DejaVuSans", nullable=False)
    show_week_numbers: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    title_align: Mapped[str] = mapped_column(String(10), default="center", nullable=False, server_default="center")
    show_year: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default=false())
    year_align: Mapped[str] = mapped_column(String(10), default="center", nullable=False, server_default="center")
    year_color: Mapped[dict | None] = mapped_column(JSON)  # None = same as title
    layout: Mapped[str] = mapped_column(String(10), default="grid", nullable=False, server_default="grid")
    month_names_uppercase: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default=false())
    day_names_uppercase: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default=false())
    day_number_scale: Mapped[float] = mapped_column(Float, default=100.0, nullable=False, server_default="100")
    table_day_names: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default=true())
    month_gap_mm: Mapped[float | None] = mapped_column(Float)  # None = automatic
    show_legend: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default=false())

    # "RGB" or "CMYK". Stored colours may be in either model; they are converted on read/render.
    color_mode: Mapped[str] = mapped_column(String(4), default="RGB", nullable=False, server_default="RGB")
    # Text colours. Nullable at DB level only so they can be added to old databases; the schema always fills them.
    title_color: Mapped[dict] = mapped_column(JSON, nullable=False)
    month_name_color: Mapped[dict | None] = mapped_column(JSON)
    day_name_color: Mapped[dict | None] = mapped_column(JSON)
    day_number_color: Mapped[dict | None] = mapped_column(JSON)
    week_number_color: Mapped[dict | None] = mapped_column(JSON)
    weekday_color: Mapped[dict | None] = mapped_column(JSON)
    weekend_color: Mapped[dict | None] = mapped_column(JSON)
    holiday_color: Mapped[dict | None] = mapped_column(JSON)
    month_border_color: Mapped[dict | None] = mapped_column(JSON)
    month_border_width_mm: Mapped[float] = mapped_column(Float, default=0.5, nullable=False, server_default="0.5")
    day_border_color: Mapped[dict | None] = mapped_column(JSON)
    day_border_width_mm: Mapped[float] = mapped_column(Float, default=0.2, nullable=False, server_default="0.2")

    holidays_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    holiday_country: Mapped[str | None] = mapped_column(String(10))
    holiday_subdiv: Mapped[str | None] = mapped_column(String(20))
    holiday_day_number_color: Mapped[dict | None] = mapped_column(JSON)
    holiday_day_name_color: Mapped[dict | None] = mapped_column(JSON)

    background_asset_id: Mapped[int | None] = mapped_column(ForeignKey("background_assets.id", ondelete="SET NULL"))
    logo_asset_id: Mapped[int | None] = mapped_column(ForeignKey("background_assets.id", ondelete="SET NULL"))
    logo_align: Mapped[str] = mapped_column(String(10), default="right", nullable=False, server_default="right")
    logo_opacity: Mapped[float] = mapped_column(Float, default=100.0, nullable=False, server_default="100")
    background_mode: Mapped[str] = mapped_column(String(10), default="cover", nullable=False)
    background_opacity: Mapped[float] = mapped_column(Float, default=100.0, nullable=False, server_default="100")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    day_overrides: Mapped[list["DayOverride"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="DayOverride.day"
    )
    background: Mapped["BackgroundAsset | None"] = relationship(
        back_populates="projects", lazy="joined", foreign_keys=[background_asset_id]
    )
    logo: Mapped["BackgroundAsset | None"] = relationship(lazy="joined", foreign_keys=[logo_asset_id])


class BackgroundAsset(Base):
    """An uploaded background file kept on the server; reusable across projects."""

    __tablename__ = "background_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)  # name on disk
    original_name: Mapped[str] = mapped_column(String(300), nullable=False)
    suffix: Mapped[str] = mapped_column(String(10), nullable=False)  # ".svg", ".png", ".jpg"
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)  # pixels for rasters, None for SVG
    height: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    projects: Mapped[list[Project]] = relationship(back_populates="background", foreign_keys=[Project.background_asset_id])


class DayOverride(Base):
    __tablename__ = "day_overrides"
    __table_args__ = (UniqueConstraint("project_id", "day", name="uq_project_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    color: Mapped[dict | None] = mapped_column(JSON)  # None = explicitly no background
    day_number_color: Mapped[dict | None] = mapped_column(JSON)  # None = inherit
    day_name_color: Mapped[dict | None] = mapped_column(JSON)  # None = inherit
    note: Mapped[str | None] = mapped_column(String(200))

    project: Mapped[Project] = relationship(back_populates="day_overrides")
