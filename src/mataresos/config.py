"""Caricamento e validazione della configurazione dei calendari Mataresos.

La configurazione è un documento YAML. Ogni sezione è opzionale: i valori
indicati dall'utente vengono uniti sopra i default integrati, quindi un file
di configurazione può sovrascrivere un singolo colore senza ripetere il resto.

Esempio minimo::

    palette:
      holiday_background: "#0b6e4f"

    holidays:
      "04-25": Festa della Liberazione
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "CalendarConfig",
    "ConfigError",
    "FontConfig",
    "Holiday",
    "LEGEND_STYLES",
    "LayoutConfig",
    "MONTH_SECOND_POSITIONS",
    "Palette",
    "config_template",
    "default_config",
    "load_config",
]


class ConfigError(ValueError):
    """Sollevata quando un documento di configurazione non è valido."""


MONTH_SECOND_POSITIONS: tuple[str, ...] = ("below", "beside")
"""Dove mettere il secondo nome del mese rispetto al principale."""

LEGEND_STYLES: tuple[str, ...] = ("stacked", "inline")
"""Disposizione di una voce della legenda: tre fasce impilate, oppure una riga sola."""


MONTH_NAMES: tuple[str, ...] = (
    "Gennaio",
    "Febbraio",
    "Marzo",
    "Aprile",
    "Maggio",
    "Giugno",
    "Luglio",
    "Agosto",
    "Settembre",
    "Ottobre",
    "Novembre",
    "Dicembre",
)

DAY_NAMES: tuple[str, ...] = (
    "Lunedì",
    "Martedì",
    "Mercoledì",
    "Giovedì",
    "Venerdì",
    "Sabato",
    "Domenica",
)

DAY_SHORT_NAMES: tuple[str, ...] = ("Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom")

_ENGLISH_WEEKDAYS: tuple[str, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

_HOLIDAY_KEY_RE = re.compile(r"^(?P<month>\d{1,2})-(?P<day>\d{1,2})$")

DEFAULT_CONFIG: dict[str, Any] = {
    "calendar": {
        "week_start": "monday",
        "weekend": ["saturday", "sunday"],
        "fixed_weeks": True,
    },
    "months": {
        "names": list(MONTH_NAMES),
        "second_names": [""] * 12,
    },
    "days": {
        "names": list(DAY_NAMES),
        "short": list(DAY_SHORT_NAMES),
    },
    "holidays": {
        "01-01": "Capodanno",
        "01-06": "Epifania",
        "04-25": "Festa della Liberazione",
        "05-01": "Festa del Lavoro",
        "06-02": "Festa della Repubblica",
        "08-15": "Ferragosto",
        "11-01": "Ognissanti",
        "12-08": "Immacolata",
        "12-25": "Natale",
        "12-26": "Santo Stefano",
    },
    "special_dates": {
        # Vuoto di default: sono ricorrenze tue, non c'è un elenco da sostituire.
    },
    "font": {
        "family": "'DejaVu Sans', 'Segoe UI', Helvetica, Arial, sans-serif",
        "title_family": "",
        "month_second_family": "",
        "year_title_size": 40.0,
        "month_title_size": 20.0,
        "month_second_size": 12.0,
        "weekday_size": 11.0,
        "day_size": 14.0,
        "holiday_size": 6.5,
        "legend_size": 8.0,
        "legend_title_size": 12.0,
        "title_weight": 700,
        "day_weight": 500,
        "weekend_weight": 0,
        "holiday_weight": 700,
        "title_letter_spacing": 1.5,
    },
    "palette": {
        "page_background": "#f6f6f3",
        "month_background": "#ffffff",
        "month_border": "#dcdcd6",
        "title": "#1c1c1c",
        "month_second": "#6b6b6b",
        "weekday": "#6b6b6b",
        "weekday_weekend": "#b5404a",
        "day": "#242424",
        "day_weekend": "#b5404a",
        "holiday_background": "#b5404a",
        "holiday_day": "#ffffff",
        "holiday_name": "#8f323b",
        "special_background": "#ffd166",
        "special_day": "#ff4242",
        "special_name": "#ff4242",
        "grid": "#ebebe6",
    },
    "layout": {
        "columns": 3,
        "cell_width": 46.0,
        "cell_height": 40.0,
        "month_padding": 12.0,
        "gap_x": 26.0,
        "gap_y": 34.0,
        "page_padding": 44.0,
        "year_title_height": 86.0,
        "grid_lines": True,
        "uppercase_titles": False,
        "show_holiday_names": False,
        "holiday_name_lines": 2,
        "month_second_position": "below",
        "show_holiday_legend": True,
        "legend_columns": 5,
        "legend_style": "stacked",
        "legend_title": "Festività",
        "legend_name_lines": 0,
        "legend_gap": 34.0,
        "single_month_rows": 6,
        "single_month_scale": 2.0,
    },
}


@dataclass(frozen=True, slots=True)
class FontConfig:
    """Impostazioni tipografiche del calendario."""

    family: str
    """Famiglia di base: numeri dei giorni, sigle, voci della legenda."""
    title_family: str
    """Famiglia di tutti i titoli: nome del mese, titolo di pagina, titolo dello specchietto."""
    month_second_family: str
    """Famiglia del secondo nome del mese; "" = quella di base."""
    year_title_size: float
    month_title_size: float
    month_second_size: float
    """Corpo del secondo nome del mese, mostrato sotto quello principale."""
    weekday_size: float
    day_size: float
    holiday_size: float
    legend_size: float
    legend_title_size: float
    title_weight: int
    day_weight: int
    weekend_weight: int
    """Peso di sabato e domenica: 0 = come ``day_weight``."""
    holiday_weight: int
    title_letter_spacing: float

    @property
    def weekend_text_weight(self) -> int:
        """Peso effettivo del fine settimana: ``weekend_weight``, o quello dei feriali se 0.

        Vale sia per i numeri dei giorni sia per le sigle dei giorni in intestazione.
        Le festività restano su ``holiday_weight``: il pallino inverte i colori, quindi
        hanno un'enfasi propria.
        """
        return self.weekend_weight or self.day_weight

    @property
    def title_stack(self) -> str:
        """Famiglia dei titoli, con fallback su quella di base.

        Serve a usare un carattere display (Anton, Bebas Neue…) solo sui titoli,
        lasciando i numeri dei giorni su una famiglia leggibile a corpo piccolo.
        """
        return self.title_family or self.family

    @property
    def month_second_stack(self) -> str:
        """Famiglia del secondo nome del mese, con fallback su quella di base."""
        return self.month_second_family or self.family


@dataclass(frozen=True, slots=True)
class Palette:
    """Colori usati dal renderer SVG (qualsiasi valore CSS valido)."""

    page_background: str
    month_background: str
    month_border: str
    title: str
    month_second: str
    """Colore del secondo nome del mese."""
    weekday: str
    weekday_weekend: str
    day: str
    day_weekend: str
    holiday_background: str
    holiday_day: str
    holiday_name: str
    special_background: str
    """Sfondo del pallino di una data speciale."""
    special_day: str
    """Numero del giorno dentro il pallino di una data speciale."""
    special_name: str
    """Nome di una data speciale."""
    grid: str


@dataclass(frozen=True, slots=True)
class LayoutConfig:
    """Geometria del calendario, in unità SVG (px)."""

    columns: int
    cell_width: float
    cell_height: float
    month_padding: float
    gap_x: float
    gap_y: float
    page_padding: float
    year_title_height: float
    grid_lines: bool
    uppercase_titles: bool
    show_holiday_names: bool
    """Se true il nome della festività viene scritto dentro la cella del giorno."""
    holiday_name_lines: int
    """Righe massime del nome della festività nella cella: 0 = quante ne entrano."""
    month_second_position: str
    """Secondo nome del mese: ``below`` (sotto) o ``beside`` (affiancato, dopo una barra)."""
    show_holiday_legend: bool
    """Se true disegna lo specchietto delle festività sotto il calendario."""
    legend_columns: int
    """Colonne dello specchietto. Se le voci non entrano si aggiungono righe."""
    legend_style: str
    """Voce dello specchietto: ``stacked`` (pallino, data e nome impilati) o
    ``inline`` (pallino, data e nome sulla stessa riga, allineati a sinistra).
    Con ``legend_columns: 1`` e ``inline`` ogni ricorrenza occupa una riga sola."""
    legend_title: str
    """Titolo dello specchietto; vuoto per non mostrarlo."""
    legend_name_lines: int
    """Righe massime su cui spezzare un nome nello specchietto: 0 = quante servono."""
    legend_gap: float
    """Spazio tra calendario e specchietto."""
    single_month_rows: int
    """Righe della vista a mese singolo: 6 = tutti i mesi della stessa altezza."""
    single_month_scale: float


@dataclass(frozen=True, slots=True)
class Holiday:
    """Nome di una festività, su una o più righe.

    Con una stringa in configurazione (``"Natale"``) il nome viene spezzato
    automaticamente secondo lo spazio disponibile. Con una lista
    (``["Sant Miquel", "Patró"]``) le righe sono quelle indicate, e servono a
    decidere dove va a capo.
    """

    lines: tuple[str, ...]
    """Righe del nome; vuoto se la festività è configurata senza nome."""
    explicit_lines: bool = False
    """True quando le righe arrivano dalla configurazione invece che dal wrapping."""

    @property
    def name(self) -> str:
        """Nome su una riga sola, usato dalla legenda e dai comandi di elenco."""
        return " ".join(self.lines)


@dataclass(frozen=True, slots=True)
class CalendarConfig:
    """Configurazione risolta e pronta all'uso."""

    month_names: tuple[str, ...]
    month_second_names: tuple[str, ...]
    """Secondo nome di ogni mese, da gennaio a dicembre ("" se assente)."""
    day_names: tuple[str, ...]
    day_short_names: tuple[str, ...]
    week_start: int
    weekend: frozenset[int]
    fixed_weeks: bool
    holidays: Mapping[str, Holiday]
    """Festività per chiave ``MM-GG``."""
    special_dates: Mapping[str, Holiday]
    """Date speciali per chiave ``MM-GG``. Su una data presente in entrambe le liste
    vince la data speciale."""
    font: FontConfig
    palette: Palette
    layout: LayoutConfig
    source: Path | None = None

    def month_name(self, month: int) -> str:
        """Nome configurato del mese ``month`` (1-12)."""
        if not 1 <= month <= 12:
            raise ValueError(f"mese fuori intervallo: {month}")
        return self.month_names[month - 1]

    def month_second_name(self, month: int) -> str:
        """Secondo nome del mese (``""`` se non configurato)."""
        if not 1 <= month <= 12:
            raise ValueError(f"mese fuori intervallo: {month}")
        return self.month_second_names[month - 1]

    @property
    def has_month_second_names(self) -> bool:
        """True se almeno un mese ha un secondo nome.

        Quando è false il secondo nome non occupa spazio; quando è true lo spazio
        viene riservato per tutti i mesi, anche quelli senza secondo nome.
        """
        return any(self.month_second_names)

    def day_label(self, weekday: int, *, short: bool = False) -> str:
        """Etichetta del giorno, dove ``weekday`` è 0 = lunedì."""
        names = self.day_short_names if short else self.day_names
        return names[weekday % 7]

    @property
    def weekday_order(self) -> tuple[int, ...]:
        """Indici dei giorni nella settimana come vanno mostrati."""
        return tuple((self.week_start + offset) % 7 for offset in range(7))

    def holiday_on(self, month: int, day: int) -> Holiday | None:
        """Festività per la data indicata, se presente."""
        return self.holidays.get(f"{month:02d}-{day:02d}")

    def special_date_on(self, month: int, day: int) -> Holiday | None:
        """Data speciale per la data indicata, se presente."""
        return self.special_dates.get(f"{month:02d}-{day:02d}")

    @property
    def named_dates(self) -> tuple[Holiday, ...]:
        """Tutte le ricorrenze con un nome, festività e date speciali.

        È il termine su cui si dimensionano la fascia riservata ai nomi nelle celle e
        la legenda: dipende solo dalla configurazione, quindi tutti i mesi restano
        della stessa altezza.
        """
        return tuple(
            item for item in (*self.holidays.values(), *self.special_dates.values()) if item.name
        )


def default_config() -> dict[str, Any]:
    """Copia indipendente dei valori di default."""
    return copy.deepcopy(DEFAULT_CONFIG)


def _merge(defaults: Mapping[str, Any], override: Mapping[str, Any], path: str = "") -> dict[str, Any]:
    unknown = sorted(key for key in override if key not in defaults)
    if unknown:
        raise ConfigError(
            f"chiave non riconosciuta in '{path or 'config'}': "
            f"{', '.join(unknown)} (valide: {', '.join(sorted(defaults))})"
        )
    merged: dict[str, Any] = {}
    for key, default_value in defaults.items():
        if key not in override:
            merged[key] = copy.deepcopy(default_value)
            continue
        value = override[key]
        if isinstance(default_value, dict):
            if not isinstance(value, Mapping):
                raise ConfigError(f"'{path}{key}' deve essere una mappa")
            merged[key] = _merge(default_value, value, f"{path}{key}.")
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _as_tuple(value: Any, expected: int, field: str, *, blank_none: bool = False) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ConfigError(f"'{field}' deve essere una lista di {expected} valori")
    items = tuple("" if blank_none and item is None else str(item) for item in value)
    if len(items) != expected:
        raise ConfigError(f"'{field}' deve contenere {expected} valori, trovati {len(items)}")
    return items


def _resolve_weekday(value: Any, day_names: Sequence[str], field: str) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"'{field}': atteso un giorno della settimana, trovato un booleano")
    if isinstance(value, int):
        if 0 <= value <= 6:
            return value
        raise ConfigError(f"'{field}': indice giorno fuori intervallo ({value}), usa 0-6")
    if not isinstance(value, str):
        raise ConfigError(f"'{field}': atteso un nome di giorno o un indice 0-6")

    text = value.strip().casefold()
    if text.isdigit():
        return _resolve_weekday(int(text), day_names, field)
    if text in _ENGLISH_WEEKDAYS:
        return _ENGLISH_WEEKDAYS.index(text)
    for index, name in enumerate(day_names):
        if name.casefold() == text or name.casefold().startswith(text):
            return index
    raise ConfigError(
        f"'{field}': giorno non riconosciuto '{value}' "
        f"(usa un nome configurato, un nome inglese o un indice 0-6)"
    )


def _holiday_value(value: Any, key: str, field: str) -> Holiday:
    """Converte il valore di una ricorrenza in :class:`Holiday`.

    Accetta una stringa, una lista di righe, oppure ``null`` per una ricorrenza senza
    nome (solo il pallino).
    """
    if value is None:
        return Holiday(lines=())
    if isinstance(value, str):
        text = value.strip()
        return Holiday(lines=(text,) if text else ())
    if isinstance(value, Sequence):
        lines = tuple(str(item).strip() for item in value if item is not None and str(item).strip())
        return Holiday(lines=lines, explicit_lines=True)
    raise ConfigError(
        f"'{field}': il valore di {key!r} deve essere un nome, una lista di righe o null"
    )


def _normalise_holidays(value: Any, field: str = "holidays") -> dict[str, Holiday]:
    """Normalizza una mappa ``MM-GG: nome`` (festività o date speciali)."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(f"'{field}' deve essere una mappa nel formato 'MM-GG: nome'")

    dates: dict[str, Holiday] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip().replace("/", "-").replace(".", "-")
        match = _HOLIDAY_KEY_RE.match(key)
        if match is None:
            raise ConfigError(f"'{field}': data non valida {raw_key!r}, usa il formato MM-GG")
        month = int(match["month"])
        day = int(match["day"])
        if not 1 <= month <= 12:
            raise ConfigError(f"'{field}': mese fuori intervallo in {raw_key!r}")
        if not 1 <= day <= 31:
            raise ConfigError(f"'{field}': giorno fuori intervallo in {raw_key!r}")
        dates[f"{month:02d}-{day:02d}"] = _holiday_value(raw_value, str(raw_key), field)
    return dict(sorted(dates.items()))


def build_config(data: Mapping[str, Any] | None, source: Path | None = None) -> CalendarConfig:
    """Costruisce una :class:`CalendarConfig` da un documento parziale."""
    payload = dict(data or {})
    raw_holidays = payload.pop("holidays", None)
    raw_special = payload.pop("special_dates", None)
    merged = _merge(DEFAULT_CONFIG, payload)

    day_names = _as_tuple(merged["days"]["names"], 7, "days.names")
    day_short = _as_tuple(merged["days"]["short"], 7, "days.short")
    month_names = _as_tuple(merged["months"]["names"], 12, "months.names")
    month_second = _as_tuple(merged["months"]["second_names"], 12, "months.second_names", blank_none=True)

    week_start = _resolve_weekday(merged["calendar"]["week_start"], day_names, "calendar.week_start")
    weekend_raw = merged["calendar"]["weekend"]
    if isinstance(weekend_raw, str) or not isinstance(weekend_raw, Sequence):
        raise ConfigError("'calendar.weekend' deve essere una lista di giorni")
    weekend = frozenset(_resolve_weekday(item, day_names, "calendar.weekend") for item in weekend_raw)

    holidays = _normalise_holidays(DEFAULT_CONFIG["holidays"] if raw_holidays is None else raw_holidays)
    special_dates = _normalise_holidays({} if raw_special is None else raw_special, "special_dates")

    legend_columns = int(merged["layout"]["legend_columns"])
    if legend_columns < 1:
        raise ConfigError(f"'layout.legend_columns': atteso un intero da 1 in su, trovato {legend_columns}")
    merged["layout"]["legend_columns"] = legend_columns

    legend_style = str(merged["layout"]["legend_style"]).strip().casefold()
    if legend_style not in LEGEND_STYLES:
        raise ConfigError(
            f"'layout.legend_style': attesa una tra {', '.join(LEGEND_STYLES)}, trovato {legend_style!r}"
        )
    merged["layout"]["legend_style"] = legend_style

    second_position = str(merged["layout"]["month_second_position"]).strip().casefold()
    if second_position not in MONTH_SECOND_POSITIONS:
        raise ConfigError(
            "'layout.month_second_position': attesa una tra "
            f"{', '.join(MONTH_SECOND_POSITIONS)}, trovato {second_position!r}"
        )
    merged["layout"]["month_second_position"] = second_position

    return CalendarConfig(
        month_names=month_names,
        month_second_names=month_second,
        day_names=day_names,
        day_short_names=day_short,
        week_start=week_start,
        weekend=weekend,
        fixed_weeks=bool(merged["calendar"]["fixed_weeks"]),
        holidays=holidays,
        special_dates=special_dates,
        font=FontConfig(**merged["font"]),
        palette=Palette(**merged["palette"]),
        layout=LayoutConfig(**merged["layout"]),
        source=source,
    )


def load_config(path: Path | str | None = None) -> CalendarConfig:
    """Carica la configurazione da ``path`` oppure usa i soli default."""
    if path is None:
        return build_config(None)

    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"file di configurazione non trovato: {config_path}")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML non valido in {config_path}: {exc}") from exc
    if raw is None:
        return build_config(None, source=config_path)
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{config_path}: la radice del documento deve essere una mappa")
    return build_config(raw, source=config_path)


_TEMPLATE_HEADER = """\
# Configurazione Mataresos: calendari SVG personalizzabili.
#
# Ogni sezione e' opzionale. I valori elencati sono i default: modifica solo
# cio' che ti serve e il resto resta invariato.
#
#   calendar.week_start     lunedi' di partenza della settimana (nome, nome
#                           inglese o indice 0-6 dove 0 = lunedi')
#   calendar.weekend        giorni considerati fine settimana
#   calendar.fixed_weeks    true = ogni mese occupa 6 righe (griglia allineata)
#   months.names            12 nomi di mese, da gennaio a dicembre
#   months.second_names     12 secondi nomi, "" se il mese non ne ha: con
#                           layout.month_second_position "below" la seconda riga
#                           viene riservata anche ai mesi che non lo hanno
#   days.names / days.short 7 nomi di giorno, da lunedi' a domenica
#   holidays                date fisse "MM-GG": nome  (sostituisce i default)
#   special_dates           altre date fisse "MM-GG": nome, con pallino giallo e
#                           colori palette.special_* (vuote di default). Se una data
#                           è in entrambe le liste vince la data speciale
#   font                    famiglia, corpi tipografici e pesi
#   palette                 colori (qualsiasi valore CSS)
#   layout                  geometria in px, colonne, titoli maiuscoli
#                           legend_style: "stacked" (tre fasce) o "inline" (una riga).
#                           Con legend_columns: 1 e "inline" ogni ricorrenza occupa
#                           una riga sola e i nomi lunghi non si spezzano
#
# Uso:  mataresos --year 2026 --config calendar.yaml
"""


def config_template() -> str:
    """Rappresentazione YAML commentata dei valori di default."""
    body = yaml.safe_dump(
        default_config(),
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=100,
    )
    return _TEMPLATE_HEADER + body
