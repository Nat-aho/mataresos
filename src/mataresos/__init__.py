"""Mataresos: generatore di calendari SVG personalizzabili."""

from __future__ import annotations

from .builder import build_month, build_single_month, build_year
from .cli import app, main
from .config import CalendarConfig, ConfigError, config_template, load_config
from .models import HOLIDAY, SPECIAL, CalendarModel, DayCell, MonthGrid
from .svg import calendar_block_size, render_calendar

__all__ = [
    "HOLIDAY",
    "SPECIAL",
    "CalendarConfig",
    "CalendarModel",
    "ConfigError",
    "DayCell",
    "MonthGrid",
    "app",
    "build_month",
    "build_single_month",
    "build_year",
    "calendar_block_size",
    "config_template",
    "load_config",
    "main",
    "render_calendar",
]

__version__ = "0.1.0"
