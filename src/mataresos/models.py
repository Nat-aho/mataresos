"""Modello dati del calendario, indipendente dal rendering."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["HOLIDAY", "SPECIAL", "CalendarModel", "DayCell", "MonthGrid"]

HOLIDAY = "holiday"
"""Festività: pallino con i colori ``palette.holiday_*``."""
SPECIAL = "special"
"""Data speciale: pallino con i colori ``palette.special_*``."""


@dataclass(frozen=True, slots=True)
class DayCell:
    """Singolo giorno del calendario, con l'eventuale ricorrenza."""

    day: int
    weekday: int
    """0 = lunedì ... 6 = domenica (convenzione ``datetime``)."""
    weekend: bool
    kind: str | None = None
    """``HOLIDAY``, ``SPECIAL``, oppure ``None`` per un giorno ordinario."""
    label: str | None = None
    """Nome della ricorrenza, su una riga sola."""
    label_lines: tuple[str, ...] = ()
    """Righe indicate in configurazione: vuoto per lo spezzamento automatico."""

    @property
    def has_marker(self) -> bool:
        """True se il giorno porta un pallino: è una festività o una data speciale."""
        return self.kind is not None

    @property
    def marker_label(self) -> str:
        """Nome della ricorrenza, vuoto se il giorno è ordinario."""
        return self.label or ""


@dataclass(frozen=True, slots=True)
class MonthGrid:
    """Griglia di un mese, già allineata alla settimana configurata."""

    year: int
    month: int
    name: str
    weekday_order: tuple[int, ...]
    weeks: tuple[tuple[DayCell | None, ...], ...]

    @property
    def row_count(self) -> int:
        return len(self.weeks)

    def days(self) -> tuple[DayCell, ...]:
        """Tutti i giorni reali del mese, in ordine cronologico."""
        return tuple(cell for week in self.weeks for cell in week if cell is not None)


@dataclass(frozen=True, slots=True)
class CalendarModel:
    """Contenuto da disegnare: un anno completo o un singolo mese."""

    year: int
    months: tuple[MonthGrid, ...]

    @property
    def is_single_month(self) -> bool:
        return len(self.months) == 1

    @property
    def row_count(self) -> int:
        """Numero massimo di righe di giorni tra tutti i mesi."""
        return max((month.row_count for month in self.months), default=0)
