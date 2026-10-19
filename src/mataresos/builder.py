"""Costruzione delle griglie di calendario a partire dalla configurazione."""

from __future__ import annotations

import calendar as _calendar
from datetime import date

from .config import CalendarConfig
from .models import HOLIDAY, SPECIAL, CalendarModel, DayCell, MonthGrid

__all__ = ["build_month", "build_single_month", "build_year"]


def build_month(
    year: int,
    month: int,
    config: CalendarConfig,
    *,
    rows: int | None = None,
) -> MonthGrid:
    """Costruisce la griglia di un mese.

    ``rows`` controlla quante righe di settimane disegnare:

    * ``None`` segue ``calendar.fixed_weeks`` (6 righe, oppure solo le necessarie);
    * un valore positivo riserva almeno quelle righe, allineando in altezza mesi
      di 4, 5 o 6 settimane;
    * ``0`` usa solo le righe effettivamente necessarie.
    """
    if not 1 <= month <= 12:
        raise ValueError(f"mese fuori intervallo: {month}")

    first_weekday, days_in_month = _calendar.monthrange(year, month)
    offset = (first_weekday - config.week_start) % 7

    cells: list[DayCell | None] = [None] * offset
    for day in range(1, days_in_month + 1):
        weekday = date(year, month, day).weekday()
        special = config.special_date_on(month, day)
        holiday = config.holiday_on(month, day)
        # La data speciale vince: un giorno porta un solo pallino.
        if special is not None:
            kind, marker = SPECIAL, special
        elif holiday is not None:
            kind, marker = HOLIDAY, holiday
        else:
            kind, marker = None, None
        cells.append(
            DayCell(
                day=day,
                weekday=weekday,
                weekend=weekday in config.weekend,
                kind=kind,
                label=marker.name if marker else None,
                label_lines=marker.lines if marker and marker.explicit_lines else (),
            )
        )

    natural_rows = max(1, -(-len(cells) // 7))
    if rows is None:
        row_count = 6 if config.fixed_weeks else natural_rows
    elif rows <= 0:
        row_count = natural_rows
    else:
        row_count = max(rows, natural_rows)

    while len(cells) < row_count * 7:
        cells.append(None)

    return MonthGrid(
        year=year,
        month=month,
        name=config.month_name(month),
        weekday_order=config.weekday_order,
        weeks=tuple(tuple(cells[start : start + 7]) for start in range(0, row_count * 7, 7)),
    )


def build_year(year: int, config: CalendarConfig) -> CalendarModel:
    """Calendario con i dodici mesi dell'anno."""
    months = tuple(build_month(year, month, config) for month in range(1, 13))
    return CalendarModel(year=year, months=months)


def build_single_month(year: int, month: int, config: CalendarConfig) -> CalendarModel:
    """Calendario con un solo mese.

    Le righe seguono ``layout.single_month_rows``: con il default 6 ogni mese
    occupa la stessa altezza, quindi tutti i file generati hanno dimensione
    fissa anche quando le settimane sono 4 invece di 5. Imposta ``0`` per
    usare solo le righe necessarie.
    """
    grid = build_month(year, month, config, rows=config.layout.single_month_rows)
    return CalendarModel(year=year, months=(grid,))
