"""Rendering SVG dei calendari Mataresos."""

from __future__ import annotations

from dataclasses import dataclass, field
from xml.sax.saxutils import escape, quoteattr

from .config import CalendarConfig, Palette
from .models import SPECIAL, CalendarModel, DayCell, MonthGrid

__all__ = ["calendar_block_size", "render_calendar"]

_UNLIMITED_LINES = 64
"""Tetto tecnico usato quando lo specchietto non limita le righe di un nome."""

_SECOND_SEPARATOR = " | "
"""Barra che separa i due nomi del mese quando il secondo sta affiancato."""

_TRANSPARENT_FILLS = frozenset({"transparent", "none"})
"""Valori di ``palette.page_background`` che lasciano il fondo non disegnato."""


def _is_transparent(colour: str | None) -> bool:
    """True se il colore richiede un fondo trasparente invece di un rettangolo pieno."""
    return colour is None or str(colour).strip().casefold() in _TRANSPARENT_FILLS


def _fill_value(colour: str | None) -> str:
    """Valore per l'attributo ``fill``: ``none`` quando il colore è trasparente.

    Un rettangolo o un cerchio senza ``fill`` verrebbe riempito di nero, che è il
    default SVG: ``none`` è l'unico modo corretto di dire "non disegnarlo".
    """
    return "none" if _is_transparent(colour) else str(colour)


def _num(value: float) -> str:
    """Formatta un numero in modo compatto per gli attributi SVG."""
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _attr(name: str, value: object) -> str:
    if isinstance(value, bool):
        raw = "true" if value else "false"
    elif isinstance(value, (int, float)):
        raw = _num(value)
    else:
        raw = str(value)
    return f" {name}={quoteattr(raw)}"


def _baseline(center_y: float, font_size: float) -> float:
    """Linea di base per centrare verticalmente il testo senza ``dominant-baseline``."""
    return center_y + font_size * 0.35


def _char_capacity(max_width: float, font_size: float) -> int:
    """Quanti caratteri entrano in ``max_width`` alla data dimensione."""
    return max(1, int(max_width / (font_size * 0.56) + 0.5))


def _fit_lines(text: str, capacity: int) -> list[str]:
    """Spezza ``text`` in righe di al più ``capacity`` caratteri, senza troncare.

    Le parole più lunghe della riga vengono spezzate a metà.
    """
    tokens: list[str] = []
    for word in text.split():
        while len(word) > capacity:
            tokens.append(word[:capacity])
            word = word[capacity:]
        if word:
            tokens.append(word)

    lines: list[str] = []
    current = ""
    for token in tokens:
        candidate = f"{current} {token}" if current else token
        if len(candidate) <= capacity:
            current = candidate
        else:
            lines.append(current)
            current = token
    if current:
        lines.append(current)
    return lines


def _limit_lines(lines: list[str], capacity: int, max_lines: int) -> list[str]:
    """Riduce a ``max_lines`` righe, chiudendo l'ultima con i puntini se serve."""
    if len(lines) <= max_lines:
        return lines
    lines = lines[:max_lines]
    lines[-1] = lines[-1][: max(1, capacity - 1)].rstrip() + "\u2026"
    return lines


def _wrap_text(text: str, max_width: float, font_size: float, max_lines: int) -> list[str]:
    """Spezza ``text`` in al più ``max_lines`` righe che entrano in ``max_width`` px.

    Le parole più lunghe della cella vengono spezzate; se il testo eccede le
    righe disponibili l'ultima riga viene chiusa con i puntini di sospensione.
    """
    if not text or max_lines <= 0 or max_width <= 0:
        return []
    capacity = _char_capacity(max_width, font_size)
    return _limit_lines(_fit_lines(text, capacity), capacity, max_lines)


def _layout_name_lines(sources: tuple[str, ...], capacity: int, max_lines: int) -> tuple[str, ...]:
    """Righe finali di un nome.

    Ogni riga di partenza resta una riga a sé, e viene spezzata solo se non entra
    comunque nella larghezza disponibile. L'intero blocco è poi limitato a
    ``max_lines`` righe, chiudendo con i puntini l'eventuale eccedenza.
    """
    lines = [piece for source in sources for piece in _fit_lines(source, capacity)]
    return tuple(_limit_lines(lines, capacity, max_lines))


def _marker_badge(palette: Palette, kind: str) -> str:
    """Colore del pallino di una ricorrenza."""
    return palette.special_background if kind == SPECIAL else palette.holiday_background


def _marker_day_colour(palette: Palette, kind: str) -> str:
    """Colore del numero del giorno dentro il pallino."""
    return palette.special_day if kind == SPECIAL else palette.holiday_day


def _marker_name_colour(palette: Palette, kind: str) -> str:
    """Colore del nome di una ricorrenza dentro la cella."""
    return palette.special_name if kind == SPECIAL else palette.holiday_name


def _marker_lines(cell: DayCell, max_width: float, font_size: float, max_lines: int) -> list[str]:
    """Righe del nome di una ricorrenza dentro la cella.

    Se la configurazione indica le righe (``label_lines``) sono quelle, e ognuna viene
    spezzata solo se non entra comunque; altrimenti si spezza il nome completo sulla
    larghezza disponibile.
    """
    if max_lines <= 0 or max_width <= 0:
        return []
    capacity = _char_capacity(max_width, font_size)
    sources = cell.label_lines or ((cell.marker_label,) if cell.marker_label else ())
    return list(_layout_name_lines(sources, capacity, max_lines))


@dataclass(frozen=True, slots=True)
class _Run:
    """Porzione di testo con stile proprio; la prima apre il ``<text>``, le altre sono ``<tspan>``."""

    text: str
    size: float
    fill: str
    family: str | None = None
    weight: int | None = None
    letter_spacing: float | None = None


@dataclass(slots=True)
class _Svg:
    """Piccolo accumulatore di elementi SVG."""

    width: float
    height: float
    elements: list[str] = field(default_factory=list)

    def rect(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        fill: str = "none",
        stroke: str | None = None,
        stroke_width: float = 1.0,
        radius: float | None = None,
    ) -> None:
        attrs = _attr("x", x) + _attr("y", y) + _attr("width", width) + _attr("height", height)
        attrs += _attr("fill", _fill_value(fill))
        if stroke is not None and not _is_transparent(stroke):
            attrs += _attr("stroke", stroke) + _attr("stroke-width", stroke_width)
        if radius:
            attrs += _attr("rx", radius) + _attr("ry", radius)
        self.elements.append(f"<rect{attrs}/>")

    def line(self, x1: float, y1: float, x2: float, y2: float, *, stroke: str, stroke_width: float = 1.0) -> None:
        if _is_transparent(stroke):
            return  # una linea senza colore non va nemmeno emessa
        attrs = _attr("x1", x1) + _attr("y1", y1) + _attr("x2", x2) + _attr("y2", y2)
        attrs += _attr("stroke", stroke) + _attr("stroke-width", stroke_width)
        self.elements.append(f"<line{attrs}/>")

    def circle(self, cx: float, cy: float, radius: float, *, fill: str) -> None:
        attrs = _attr("cx", cx) + _attr("cy", cy) + _attr("r", radius) + _attr("fill", _fill_value(fill))
        self.elements.append(f"<circle{attrs}/>")

    def text(
        self,
        x: float,
        y: float,
        content: str,
        *,
        size: float,
        fill: str,
        anchor: str = "middle",
        weight: int | None = None,
        family: str | None = None,
        letter_spacing: float | None = None,
    ) -> None:
        if content == "":
            return
        attrs = _attr("x", x) + _attr("y", y) + _attr("font-size", size) + _attr("fill", _fill_value(fill))
        attrs += _attr("text-anchor", anchor)
        if weight is not None:
            attrs += _attr("font-weight", weight)
        if family:
            attrs += _attr("font-family", family)
        if letter_spacing:
            attrs += _attr("letter-spacing", letter_spacing)
        self.elements.append(f"<text{attrs}>{escape(content)}</text>")

    def text_runs(self, x: float, y: float, runs: tuple[_Run, ...], *, anchor: str = "middle") -> None:
        """Testo su più porzioni di stile diverso, centrato come blocco unico.

        La prima porzione dà gli attributi al ``<text>``, le altre diventano
        ``<tspan>``. Il renderer misura il gruppo intero, quindi resta centrato senza
        dover stimare la larghezza dei glifi: serve per «Nadal | Desembre», dove la
        barra ha il corpo del titolo e il secondo nome il proprio.
        """
        first, *rest = runs
        if not first.text:
            return

        attrs = _attr("x", x) + _attr("y", y) + _attr("font-size", first.size)
        attrs += _attr("fill", _fill_value(first.fill)) + _attr("text-anchor", anchor)
        if first.weight is not None:
            attrs += _attr("font-weight", first.weight)
        if first.family:
            attrs += _attr("font-family", first.family)
        if first.letter_spacing:
            attrs += _attr("letter-spacing", first.letter_spacing)

        body = escape(first.text)
        for run in rest:
            span = _attr("font-size", run.size) + _attr("fill", _fill_value(run.fill))
            if run.weight is not None:
                span += _attr("font-weight", run.weight)
            if run.family:
                span += _attr("font-family", run.family)
            if run.letter_spacing:
                span += _attr("letter-spacing", run.letter_spacing)
            body += f"<tspan{span}>{escape(run.text)}</tspan>"

        self.elements.append(f"<text{attrs}>{body}</text>")

    def to_string(self, background: str | None) -> str:
        """Chiude il documento.

        Con ``page_background`` trasparente (o ``none``) il rettangolo di fondo non
        viene proprio disegnato, così l'SVG si può sovrapporre ad altro.
        """
        page = ""
        if not _is_transparent(background):
            page = (
                f'  <rect x="0" y="0" width="{_num(self.width)}" height="{_num(self.height)}"'
                f' fill={quoteattr(background)}/>\n'
            )
        body = "\n  ".join(self.elements)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{_num(self.width)}"'
            f' height="{_num(self.height)}"'
            f' viewBox="0 0 {_num(self.width)} {_num(self.height)}">\n'
            f"{page}"
            f"  {body}\n"
            "</svg>\n"
        )


@dataclass(frozen=True, slots=True)
class _Metrics:
    """Dimensioni calcolate per il disegno."""

    cell_w: float
    cell_h: float
    month_pad: float
    month_w: float
    month_h: float
    grid_top_offset: float
    month_title_size: float
    month_second_size: float
    title_block: float
    """Altezza riservata ai nomi del mese, secondo nome incluso."""
    weekday_size: float
    day_size: float
    holiday_size: float
    holiday_line_height: float
    holiday_max_lines: int
    holiday_wrap_width: float
    badge_radius: float
    number_zone: float
    """Altezza della fascia in cui è centrato il numero del giorno."""
    year_title_size: float
    row_count: int


def _metrics(
    config: CalendarConfig,
    model: CalendarModel,
    scale: float,
    show_holiday_names: bool,
) -> _Metrics:
    layout = config.layout
    font = config.font

    cell_w = layout.cell_width * scale
    cell_h = layout.cell_height * scale
    month_pad = layout.month_padding * scale
    row_count = max(model.row_count, 1)

    month_title_size = font.month_title_size * scale
    month_second_size = font.month_second_size * scale
    weekday_size = font.weekday_size * scale
    # Il secondo nome riserva una riga sua solo quando sta SOTTO; affiancato condivide
    # la riga del nome principale. La fascia dipende solo dalla configurazione, quindi
    # tutti i mesi restano della stessa altezza.
    second_on_own_line = config.has_month_second_names and layout.month_second_position == "below"
    title_block = month_title_size * 2.0 + (month_second_size * 1.7 if second_on_own_line else 0.0)
    weekday_block = weekday_size * 2.3

    holiday_size = font.holiday_size * scale
    holiday_line_height = holiday_size * 1.15
    holiday_wrap_width = cell_w * 0.94

    # Quante righe di nome entrano davvero nella cella. ``holiday_name_lines`` è un
    # tetto: 0 = quante ne entrano, come ``legend_name_lines``.
    lines_by_space = int((cell_h * 0.62 - holiday_size * 0.5) / holiday_line_height)
    limit = int(layout.holiday_name_lines) or _UNLIMITED_LINES
    max_lines = max(1, min(limit, lines_by_space))

    number_zone = cell_h
    if show_holiday_names:
        # Fascia riservata ai nomi, calcolata sulla festività più alta della
        # configurazione: tutti i numeri restano allineati, anche tra mesi diversi.
        capacity = _char_capacity(holiday_wrap_width, holiday_size)
        needed = max(
            (len(_layout_name_lines(source, capacity, max_lines)) for source in _holiday_sources(config)),
            default=0,
        )
        if needed:
            name_zone = min(needed * holiday_line_height + holiday_size * 0.5, cell_h * 0.62)
            number_zone = cell_h - name_zone

    month_w = 7 * cell_w + 2 * month_pad
    month_h = month_pad + title_block + weekday_block + row_count * cell_h + month_pad

    return _Metrics(
        cell_w=cell_w,
        cell_h=cell_h,
        month_pad=month_pad,
        month_w=month_w,
        month_h=month_h,
        grid_top_offset=month_pad + title_block + weekday_block,
        month_title_size=month_title_size,
        month_second_size=month_second_size,
        title_block=title_block,
        weekday_size=weekday_size,
        day_size=font.day_size * scale,
        holiday_size=holiday_size,
        holiday_line_height=holiday_line_height,
        holiday_max_lines=max_lines,
        holiday_wrap_width=holiday_wrap_width,
        badge_radius=min(min(cell_w, number_zone) * 0.32, number_zone * 0.45),
        number_zone=number_zone,
        year_title_size=font.year_title_size * scale,
        row_count=row_count,
    )


def _title_line_centers(
    origin_y: float,
    config: CalendarConfig,
    metrics: _Metrics,
) -> tuple[float, float | None]:
    """Centri verticali del nome del mese e, se previsto, del secondo nome.

    Le due righe sono centrate come un blocco unico dentro la fascia riservata.
    Il secondo centro è ``None`` quando il secondo nome non c'è, oppure quando sta
    **affiancato** al principale: in entrambi i casi la fascia resta di una riga.
    """
    block_top = origin_y + metrics.month_pad
    if not config.has_month_second_names or config.layout.month_second_position == "beside":
        return block_top + metrics.title_block / 2, None

    gap = metrics.month_title_size * 0.1
    group_height = metrics.month_title_size + gap + metrics.month_second_size
    group_top = block_top + (metrics.title_block - group_height) / 2
    return (
        group_top + metrics.month_title_size / 2,
        group_top + metrics.month_title_size + gap + metrics.month_second_size / 2,
    )


def _draw_month(
    svg: _Svg,
    month: MonthGrid,
    config: CalendarConfig,
    metrics: _Metrics,
    origin_x: float,
    origin_y: float,
    *,
    show_holiday_names: bool,
    short_weekday_labels: bool,
) -> None:
    font = config.font
    palette = config.palette
    layout = config.layout

    grid_left = origin_x + metrics.month_pad
    grid_top = origin_y + metrics.grid_top_offset

    svg.rect(
        origin_x,
        origin_y,
        metrics.month_w,
        metrics.month_h,
        fill=palette.month_background,
        stroke=palette.month_border,
        radius=metrics.month_pad * 0.6,
    )

    center_x = origin_x + metrics.month_w / 2
    first_center, second_center = _title_line_centers(origin_y, config, metrics)

    title_text = month.name.upper() if layout.uppercase_titles else month.name
    second_text = config.month_second_name(month.month)
    if layout.uppercase_titles:
        second_text = second_text.upper()

    title_weight = font.title_weight
    title_family = font.title_stack
    title_spacing = font.title_letter_spacing * (metrics.month_title_size / font.month_title_size)
    first_y = _baseline(first_center, metrics.month_title_size)

    if second_center is None and second_text:
        # Affiancato: «Nadal | Desembre» su una riga. La barra ha il corpo del titolo
        # principale ma colore, famiglia e peso del secondo nome; il secondo nome ha
        # il corpo suo.
        svg.text_runs(
            center_x,
            first_y,
            (
                _Run(title_text, metrics.month_title_size, palette.title, title_family, title_weight, title_spacing),
                _Run(
                    _SECOND_SEPARATOR,
                    metrics.month_title_size,
                    palette.month_second,
                    font.month_second_stack,
                    font.day_weight,
                ),
                _Run(
                    second_text,
                    metrics.month_second_size,
                    palette.month_second,
                    font.month_second_stack,
                    font.day_weight,
                ),
            ),
        )
    else:
        svg.text(
            center_x,
            first_y,
            title_text,
            size=metrics.month_title_size,
            fill=palette.title,
            weight=title_weight,
            family=title_family,
            letter_spacing=title_spacing,
        )

        # Il secondo nome sta sotto, e la fascia lo ha già riservato.
        if second_center is not None and second_text:
            svg.text(
                center_x,
                _baseline(second_center, metrics.month_second_size),
                second_text,
                size=metrics.month_second_size,
                fill=palette.month_second,
                weight=font.day_weight,
                family=font.month_second_stack,
            )

    separator_y = origin_y + metrics.month_pad + metrics.title_block
    svg.line(grid_left, separator_y, grid_left + 7 * metrics.cell_w, separator_y, stroke=palette.grid)

    weekday_center_y = separator_y + metrics.weekday_size * 1.15
    for column, weekday in enumerate(month.weekday_order):
        center_x = grid_left + column * metrics.cell_w + metrics.cell_w / 2
        svg.text(
            center_x,
            _baseline(weekday_center_y, metrics.weekday_size),
            config.day_label(weekday, short=short_weekday_labels),
            size=metrics.weekday_size,
            fill=palette.weekday_weekend if weekday in config.weekend else palette.weekday,
            weight=font.weekend_text_weight if weekday in config.weekend else font.day_weight,
            family=font.family,
        )

    header_line_y = grid_top
    svg.line(grid_left, header_line_y, grid_left + 7 * metrics.cell_w, header_line_y, stroke=palette.grid)

    if layout.grid_lines:
        grid_bottom = grid_top + metrics.row_count * metrics.cell_h
        for column in range(1, 7):
            x = grid_left + column * metrics.cell_w
            svg.line(x, grid_top, x, grid_bottom, stroke=palette.grid)
        for row in range(1, metrics.row_count):
            y = grid_top + row * metrics.cell_h
            svg.line(grid_left, y, grid_left + 7 * metrics.cell_w, y, stroke=palette.grid)

    for row, week in enumerate(month.weeks):
        cell_top = grid_top + row * metrics.cell_h
        number_center_y = cell_top + metrics.number_zone / 2
        name_top = cell_top + metrics.number_zone
        for column, cell in enumerate(week):
            if cell is None:
                continue
            center_x = grid_left + column * metrics.cell_w + metrics.cell_w / 2
            if cell.has_marker and cell.kind:
                badge = _marker_badge(palette, cell.kind)
                day_colour = _marker_day_colour(palette, cell.kind)
                name_colour = _marker_name_colour(palette, cell.kind)
                svg.circle(center_x, number_center_y, metrics.badge_radius, fill=badge)
                svg.text(
                    center_x,
                    _baseline(number_center_y, metrics.day_size),
                    str(cell.day),
                    size=metrics.day_size,
                    fill=day_colour,
                    weight=font.holiday_weight,
                    family=font.family,
                )
                if show_holiday_names and cell.marker_label:
                    lines = _marker_lines(
                        cell,
                        metrics.holiday_wrap_width,
                        metrics.holiday_size,
                        metrics.holiday_max_lines,
                    )
                    for index, line in enumerate(lines):
                        line_center_y = (
                            name_top + metrics.holiday_size * 0.5 + index * metrics.holiday_line_height
                        )
                        svg.text(
                            center_x,
                            _baseline(line_center_y, metrics.holiday_size),
                            line,
                            size=metrics.holiday_size,
                            fill=name_colour,
                            weight=font.day_weight,
                            family=font.family,
                        )
            else:
                svg.text(
                    center_x,
                    _baseline(number_center_y, metrics.day_size),
                    str(cell.day),
                    size=metrics.day_size,
                    fill=palette.day_weekend if cell.weekend else palette.day,
                    weight=font.weekend_text_weight if cell.weekend else font.day_weight,
                    family=font.family,
                )


@dataclass(frozen=True, slots=True)
class _LegendEntry:
    """Voce dello specchietto, con il nome già spezzato sulle righe disponibili."""

    day: int
    month: int
    kind: str
    """``HOLIDAY`` o ``SPECIAL``: decide i colori del pallino."""
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Legend:
    """Ingombro riservato alla legenda delle festività.

    La geometria dipende solo dalla configurazione, mai dai mesi disegnati: così
    tutti i file generati hanno lo stesso ingombro anche quando un mese non ha
    festività. In quel caso ``entries`` è vuoto e non si disegna nulla: lo spazio
    è comunque occupato.
    """

    x: float
    y: float
    width: float
    height: float
    pad: float
    size: float
    title_size: float
    title: str
    line_step: float
    columns: int
    style: str
    """``stacked`` o ``inline``: come è disposta ogni voce."""
    indent: float
    """Rientro delle voci dall'inizio dell'area utile; allinea il pallino alla prima
    colonna dei giorni nello stile ``inline``."""
    entries: tuple[_LegendEntry, ...]


def _legend_entries(model: CalendarModel) -> tuple[tuple[int, int, str, tuple[str, ...]], ...]:
    """Ricorrenze con un nome, limitate ai mesi effettivamente disegnati.

    Le righe sono quelle indicate in configurazione, oppure il nome intero: la
    legenda le rispetta, mettendo ogni voce su una riga propria. Il tipo
    (``HOLIDAY`` o ``SPECIAL``) decide i colori del pallino.
    """
    return tuple(
        (month.month, day_cell.day, day_cell.kind, day_cell.label_lines or (day_cell.marker_label,))
        for month in model.months
        for day_cell in month.days()
        if day_cell.has_marker and day_cell.kind and day_cell.marker_label
    )


def _holiday_sources(config: CalendarConfig) -> tuple[tuple[str, ...], ...]:
    """Righe di partenza di ogni ricorrenza con nome, festività e date speciali.

    È il termine su cui si dimensionano la fascia dei nomi nelle celle e la legenda,
    e dipende solo dalla configurazione.
    """
    return tuple(item.lines for item in config.named_dates if item.lines)


def _named_holidays(config: CalendarConfig) -> tuple[str, ...]:
    """Nomi di tutte le ricorrenze configurate, festività e date speciali.

    Non dipendono dai mesi disegnati: è quello che rende l'ingombro dello specchietto
    identico in tutti i file di ``--per-month``.
    """
    return tuple(item.name for item in config.named_dates)


def _legend_inline_offsets(size: float) -> tuple[float, float, float]:
    """(raggio del pallino, inizio della data, inizio del nome) in stile ``inline``.

    Il nome parte dopo la data più larga possibile (``88/88``), così le voci della
    stessa colonna restano allineate tra loro.
    """
    radius = size * 0.42
    date_offset = radius * 2.0 + size * 0.7
    return radius, date_offset, date_offset + 5 * size * 0.56 + size * 0.6


def _legend_row_heights(legend: _Legend) -> list[float]:
    """Altezza effettiva di ogni riga della legenda.

    Ogni riga si dimensiona sulle righe di nome che contiene davvero, più una sola
    spaziatura: così tra una voce e l'altra non restano righe vuote quando la
    configurazione ha un nome molto più alto degli altri. L'altezza del riquadro
    (``legend.height``) resta quella riservata dal layout: l'eventuale differenza
    finisce in fondo, come spazio non usato.
    """
    bands = 2 if legend.style == "stacked" else 0
    rows = -(-len(legend.entries) // legend.columns)
    heights: list[float] = []
    for row in range(rows):
        chunk = legend.entries[row * legend.columns : (row + 1) * legend.columns]
        lines = max((len(entry.lines) for entry in chunk), default=1)
        heights.append((bands + lines) * legend.line_step + legend.size * 0.55)
    return heights


def _legend_rows_height(
    line_counts: tuple[int, ...],
    *,
    columns: int,
    bands: int,
    line_step: float,
    margin: float,
) -> float:
    """Altezza di un blocco di voci impacchettate in righe di ``columns`` colonne.

    ``line_counts`` è il numero di righe di nome di ogni voce, nell'ordine in cui viene
    disegnata. Ogni riga è alta quanto la sua voce più alta, più una sola spaziatura.
    """
    total = 0.0
    for start in range(0, len(line_counts), columns):
        chunk = line_counts[start : start + columns]
        total += (bands + max(chunk, default=1)) * line_step + margin
    return total


def _legend_reserved_height(
    config: CalendarConfig,
    model: CalendarModel,
    *,
    columns: int,
    bands: int,
    line_step: float,
    margin: float,
    capacity: int,
    max_lines: int,
) -> float:
    """Quanto spazio serve davvero alla legenda, calcolato dalle ricorrenze.

    Non è il prodotto dei due casi peggiori (mese più affollato × voce più alta), che
    sovrastima: si simula il contenuto reale. Con un solo mese si prende il **massimo
    fra i mesi della configurazione**, così i dodici file di ``--per-month`` hanno la
    stessa altezza; con più mesi si considera la sequenza intera, perché voci di mesi
    diversi condividono la stessa riga.
    """
    named = {**config.holidays, **config.special_dates}
    per_month: dict[str, list[int]] = {}
    sequence: list[int] = []
    for key in sorted(named):
        item = named[key]
        if not item.name:
            continue
        count = len(_layout_name_lines(item.lines, capacity, max_lines))
        per_month.setdefault(key[:2], []).append(count)
        sequence.append(count)

    def height(counts: list[int]) -> float:
        return _legend_rows_height(
            tuple(counts), columns=columns, bands=bands, line_step=line_step, margin=margin
        )

    needed = max((height(counts) for counts in per_month.values()), default=0.0)
    if len(model.months) > 1:
        needed = max(needed, height(sequence))
    return needed


def _build_legend(
    config: CalendarConfig,
    model: CalendarModel,
    scale: float,
    *,
    x: float,
    y: float,
    width: float,
    day_column_width: float | None = None,
) -> _Legend | None:
    """Calcola l'ingombro riservato alla legenda.

    La legenda ha un numero di colonne configurabile (``layout.legend_columns``) e le
    righe del mese con più festività in configurazione. L'ingombro dipende quindi solo
    dalla configurazione, non da quali mesi si stanno disegnando: tutti i file di
    ``--per-month`` restano identici, marzo compreso quando non ha festività.

    Restituisce ``None`` solo se in configurazione non c'è nessuna festività con un
    nome: in quel caso non c'è niente da riservare.
    """
    names = _named_holidays(config)
    if not names or width <= 0:
        return None

    layout = config.layout
    font = config.font

    pad = layout.month_padding * scale
    size = font.legend_size * scale
    title_size = font.legend_title_size * scale
    line_step = size * 1.45

    columns = max(1, int(layout.legend_columns))
    style = layout.legend_style
    # In ``inline`` la voce parte dal bordo della colonna, quindi il pallino finirebbe
    # sul bordo della prima colonna dei giorni: lo si rientra fino a centrarlo sulla
    # colonna, come i numeri del calendario. Il rientro riduce lo spazio del testo.
    if style == "inline":
        radius, _, name_offset = _legend_inline_offsets(size)
        indent = max(0.0, day_column_width / 2 - radius) if day_column_width else 0.0
        name_width = (width - 2 * pad - indent) / columns - name_offset - size * 0.4
    else:
        indent = 0.0
        name_width = (width - 2 * pad) / columns - size
    max_lines = int(layout.legend_name_lines) or _UNLIMITED_LINES

    # Lo spazio riservato è quello che serve davvero, simulato dalle ricorrenze in
    # configurazione: non il prodotto dei due casi peggiori (mese più affollato per voce
    # più alta), che sovrastima quasi sempre.
    capacity = _char_capacity(name_width, size)
    bands = 2 if style == "stacked" else 0
    needed = _legend_reserved_height(
        config,
        model,
        columns=columns,
        bands=bands,
        line_step=line_step,
        margin=size * 0.55,
        capacity=capacity,
        max_lines=max_lines,
    )

    entries = _legend_entries(model)
    content_height = pad + (title_size * 2.0 if layout.legend_title else 0.0) + needed + pad

    return _Legend(
        x=x,
        y=y,
        width=width,
        height=content_height,
        pad=pad,
        size=size,
        title_size=title_size,
        title=layout.legend_title,
        line_step=line_step,
        columns=columns,
        style=style,
        indent=indent,
        entries=tuple(
            _LegendEntry(
                month=month,
                day=day,
                kind=kind,
                lines=_layout_name_lines(source, capacity, max_lines),
            )
            for month, day, kind, source in entries
        ),
    )


def _draw_legend(svg: _Svg, config: CalendarConfig, legend: _Legend) -> None:
    """Disegna la legenda, se ha qualcosa da mostrare.

    Con ``entries`` vuoto il mese non ha festività: lo spazio gli è stato riservato
    ma non si disegna nulla, così la pagina resta identica a quella degli altri mesi.
    """
    if not legend.entries:
        return

    font = config.font
    palette = config.palette

    svg.rect(
        legend.x,
        legend.y,
        legend.width,
        legend.height,
        fill=palette.month_background,
        stroke=palette.month_border,
        radius=legend.pad * 0.6,
    )

    left = legend.x + legend.pad
    cursor_y = legend.y + legend.pad

    if legend.title:
        svg.text(
            left,
            _baseline(cursor_y + legend.title_size, legend.title_size),
            legend.title.upper() if config.layout.uppercase_titles else legend.title,
            size=legend.title_size,
            fill=palette.title,
            weight=font.title_weight,
            family=font.title_stack,
            anchor="start",
        )
        cursor_y += legend.title_size * 2.0

    # Il rientro sposta l'inizio delle voci senza farle uscire dal riquadro: la
    # larghezza di colonna si riduce di altrettanto.
    column_width = (legend.width - 2 * legend.pad - legend.indent) / legend.columns
    inline = legend.style == "inline"
    radius, date_offset, name_offset = _legend_inline_offsets(legend.size)

    row_top = cursor_y
    for row, row_height in enumerate(_legend_row_heights(legend)):
        for column in range(legend.columns):
            index = row * legend.columns + column
            if index >= len(legend.entries):
                break

            entry = legend.entries[index]
            column_left = left + legend.indent + column * column_width

            if inline:
                # Pallino, data e nome sulla prima riga della voce, allineati a sinistra:
                # con una sola colonna il nome ha tutta la larghezza.
                first_line_y = row_top + legend.line_step / 2
                svg.circle(
                    column_left + radius,
                    first_line_y,
                    radius,
                    fill=_marker_badge(palette, entry.kind),
                )
                svg.text(
                    column_left + date_offset,
                    _baseline(first_line_y, legend.size),
                    f"{entry.day:02d}/{entry.month:02d}",
                    size=legend.size,
                    fill=palette.weekday,
                    weight=font.day_weight,
                    family=font.family,
                    anchor="start",
                )
                for line_index, line in enumerate(entry.lines):
                    svg.text(
                        column_left + name_offset,
                        _baseline(first_line_y + line_index * legend.line_step, legend.size),
                        line,
                        size=legend.size,
                        fill=palette.holiday_name,
                        weight=font.day_weight,
                        family=font.family,
                        anchor="start",
                    )
                continue

            # Impilato: pallino e data su due fasce, il nome sotto, tutto centrato sulla
            # verticale della colonna, come i numeri dei giorni.
            dot_y = row_top + legend.line_step / 2
            date_y = dot_y + legend.line_step
            axis = column_left + column_width / 2

            svg.circle(axis, dot_y, legend.size * 0.42, fill=_marker_badge(palette, entry.kind))
            svg.text(
                axis,
                _baseline(date_y, legend.size),
                f"{entry.day:02d}/{entry.month:02d}",
                size=legend.size,
                fill=palette.weekday,
                weight=font.day_weight,
                family=font.family,
                anchor="middle",
            )

            for line_index, line in enumerate(entry.lines):
                svg.text(
                    axis,
                    _baseline(date_y + (line_index + 1) * legend.line_step, legend.size),
                    line,
                    size=legend.size,
                    fill=palette.holiday_name,
                    weight=font.day_weight,
                    family=font.family,
                    anchor="middle",
                )

        row_top += row_height


def _grid_size(
    metrics: _Metrics,
    config: CalendarConfig,
    columns: int,
    rows: int,
    scale: float,
) -> tuple[float, float]:
    """Larghezza e altezza del blocco dei mesi, senza il padding di pagina."""
    layout = config.layout
    gap_x = layout.gap_x * scale
    gap_y = layout.gap_y * scale
    return (
        columns * metrics.month_w + (columns - 1) * gap_x,
        rows * metrics.month_h + (rows - 1) * gap_y,
    )


def calendar_block_size(
    model: CalendarModel,
    config: CalendarConfig,
    *,
    columns: int | None = None,
    scale: float = 1.0,
) -> tuple[float, float]:
    """Larghezza e altezza del blocco dei mesi.

    È la dimensione fissa del calendario: la legenda la usa come larghezza quando
    sta sotto la griglia.
    """
    if not model.months:
        raise ValueError("il modello non contiene mesi")

    scale = max(scale, 0.1)
    use_columns = max(1, min(columns or config.layout.columns, len(model.months)))
    rows = -(-len(model.months) // use_columns)
    return _grid_size(_metrics(config, model, scale, False), config, use_columns, rows, scale)


def render_calendar(
    model: CalendarModel,
    config: CalendarConfig,
    *,
    columns: int | None = None,
    scale: float = 1.0,
    title: str | None = None,
    show_holiday_names: bool | None = None,
    show_holiday_legend: bool | None = None,
) -> str:
    """Genera il documento SVG per ``model``.

    ``columns`` è il numero di mesi per riga, ``scale`` ingrandisce celle e
    caratteri (usato per la vista a mese singolo). Con ``show_holiday_legend``
    attivo lo specchietto delle festività viene disegnato sotto la griglia, staccato
    di ``layout.legend_gap``.
    """
    if not model.months:
        raise ValueError("il modello non contiene mesi")

    layout = config.layout
    palette = config.palette
    font = config.font
    scale = max(scale, 0.1)

    month_count = len(model.months)
    use_columns = max(1, min(columns or layout.columns, month_count))
    grid_rows = -(-month_count // use_columns)

    show_names = layout.show_holiday_names if show_holiday_names is None else show_holiday_names
    show_legend = layout.show_holiday_legend if show_holiday_legend is None else show_holiday_legend

    metrics = _metrics(config, model, scale, show_names)
    page_pad = layout.page_padding * scale
    title_height = layout.year_title_height * scale if title else 0.0
    legend_gap = layout.legend_gap * scale

    content_w, grid_h = _grid_size(metrics, config, use_columns, grid_rows, scale)
    grid_right = page_pad + content_w
    grid_bottom = page_pad + title_height + grid_h

    legend: _Legend | None = None
    if show_legend:
        # La legenda sta sempre sotto la griglia, larga quanto il blocco dei mesi.
        legend = _build_legend(
            config,
            model,
            scale,
            x=page_pad,
            y=grid_bottom + legend_gap,
            width=content_w,
            day_column_width=metrics.cell_w,
        )

    page_w = grid_right + page_pad
    if legend is None:
        page_h = grid_bottom + page_pad
    else:
        page_h = legend.y + legend.height + page_pad

    svg = _Svg(width=page_w, height=page_h)

    if title:
        svg.text(
            (page_pad + grid_right) / 2,
            _baseline(page_pad + title_height / 2, metrics.year_title_size),
            title.upper() if layout.uppercase_titles else title,
            size=metrics.year_title_size,
            fill=palette.title,
            weight=font.title_weight,
            family=font.title_stack,
            letter_spacing=font.title_letter_spacing * (metrics.year_title_size / font.year_title_size),
        )

    short_weekday_labels = metrics.cell_w < 56.0
    gap_x = layout.gap_x * scale
    gap_y = layout.gap_y * scale

    for index, month in enumerate(model.months):
        row, column = divmod(index, use_columns)
        origin_x = page_pad + column * (metrics.month_w + gap_x)
        origin_y = page_pad + title_height + row * (metrics.month_h + gap_y)
        _draw_month(
            svg,
            month,
            config,
            metrics,
            origin_x,
            origin_y,
            show_holiday_names=show_names,
            short_weekday_labels=short_weekday_labels,
        )

    if legend is not None:
        _draw_legend(svg, config, legend)

    return svg.to_string(palette.page_background)
