"""Interfaccia a riga di comando di Mataresos."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from .builder import build_single_month, build_year
from .config import (
    LEGEND_STYLES,
    CalendarConfig,
    ConfigError,
    config_template,
    load_config,
)
from .models import HOLIDAY, SPECIAL, CalendarModel
from .svg import calendar_block_size, render_calendar

__all__ = ["app", "main"]

CONFIG_OPTION = typer.Option(
    "--config",
    "-c",
    help="File YAML di configurazione (default: valori integrati).",
)

app = typer.Typer(
    name="mataresos",
    help="Genera calendari SVG personalizzabili: nomi di mesi e giorni, festività, font e palette.",
    add_completion=False,
    no_args_is_help=False,
    rich_markup_mode="rich",
)


def _fail(message: str, code: int = 1) -> NoReturn:
    typer.secho(f"Errore: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code)


def _load(config_path: Path | None) -> CalendarConfig:
    try:
        return load_config(config_path)
    except ConfigError as exc:
        _fail(str(exc))


def _effective_config(
    config: CalendarConfig,
    *,
    legend_gap: float | None,
    legend_columns: int | None,
    legend_style: str | None,
) -> CalendarConfig:
    """Applica al volo le opzioni di layout passate da riga di comando."""
    changes: dict[str, object] = {}

    if legend_gap is not None:
        if legend_gap < 0:
            _fail("--legend-gap non può essere negativo")
        changes["legend_gap"] = legend_gap

    if legend_columns is not None:
        if legend_columns < 1:
            _fail("--legend-columns: atteso un intero da 1 in su")
        changes["legend_columns"] = legend_columns

    if legend_style is not None:
        normalised = legend_style.strip().casefold()
        if normalised not in LEGEND_STYLES:
            _fail(f"--legend-style: attesa una tra {', '.join(LEGEND_STYLES)}, trovato {legend_style!r}")
        changes["legend_style"] = normalised

    return replace(config, layout=replace(config.layout, **changes)) if changes else config


def _default_filename(year: int, month: int | None) -> str:
    return f"calendar-{year}.svg" if month is None else f"calendar-{year}-{month:02d}.svg"


def _resolve_output(output: Path | None, year: int, month: int | None) -> Path:
    if output is None:
        return Path(_default_filename(year, month))
    if output.is_dir():
        return output / _default_filename(year, month)
    if output.suffix.lower() != ".svg":
        return output.with_suffix(".svg")
    return output


def _resolve_output_dir(output: Path | None, year: int) -> Path:
    if output is None:
        return Path(f"calendar-{year}")
    if output.suffix.lower() == ".svg":
        _fail(f"--per-month scrive un file per mese: {output} deve essere una cartella, non un file .svg")
    return output


def _write_svg(destination: Path, svg: str, label: str = "Calendario") -> None:
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(svg, encoding="utf-8")
    except OSError as exc:
        _fail(f"impossibile scrivere {destination}: {exc}")
    typer.secho(f"{label} scritto in {destination}", fg=typer.colors.GREEN)


def _emit(
    destination: Path,
    model: CalendarModel,
    config: CalendarConfig,
    *,
    columns: int,
    scale: float,
    title: str | None,
    show_holiday_names: bool,
    include_legend: bool,
) -> None:
    """Scrive il calendario."""
    svg = render_calendar(
        model,
        config,
        columns=columns,
        scale=scale,
        title=title,
        show_holiday_names=show_holiday_names,
        show_holiday_legend=include_legend,
    )
    _write_svg(destination, svg)


@app.callback(invoke_without_command=True)
def generate(
    ctx: typer.Context,
    year: Annotated[
        int | None,
        typer.Option("--year", "-y", help="Anno da generare (default: anno corrente)."),
    ] = None,
    month: Annotated[
        int | None,
        typer.Option("--month", "-m", min=1, max=12, help="Genera un solo mese (1-12) invece dell'anno intero."),
    ] = None,
    per_month: Annotated[
        bool,
        typer.Option(
            "--per-month",
            help="Un file SVG per ogni mese dell'anno (pagina per pagina) in una cartella.",
        ),
    ] = False,
    config_path: Annotated[Path | None, CONFIG_OPTION] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="File o cartella di destinazione.")] = None,
    columns: Annotated[
        int | None,
        typer.Option("--columns", help="Colonne della griglia nella vista annuale (default dal file)."),
    ] = None,
    scale: Annotated[
        float | None,
        typer.Option("--scale", help="Fattore di ingrandimento nella vista a mese singolo."),
    ] = None,
    title: Annotated[
        str | None,
        typer.Option("--title", help="Titolo in alto; senza questa opzione non viene disegnato nulla."),
    ] = None,
    holiday_names: Annotated[
        bool | None,
        typer.Option("--holiday-names/--no-holiday-names", help="Mostra il nome delle festività dentro le celle."),
    ] = None,
    legend: Annotated[
        bool | None,
        typer.Option("--legend/--no-legend", help="Specchietto delle festività sotto il calendario."),
    ] = None,
    legend_gap: Annotated[
        float | None,
        typer.Option("--legend-gap", help="Spazio tra calendario e specchietto, in px."),
    ] = None,
    legend_columns: Annotated[
        int | None,
        typer.Option("--legend-columns", min=1, help="Colonne dello specchietto delle festività."),
    ] = None,
    legend_style: Annotated[
        str | None,
        typer.Option(
            "--legend-style",
            help="Voce dello specchietto: stacked (tre fasce) o inline (una riga).",
        ),
    ] = None,
) -> None:
    """Genera un calendario SVG per un anno intero o per un singolo mese."""
    if ctx.invoked_subcommand is not None:
        return

    config = _load(config_path)
    config = _effective_config(
        config,
        legend_gap=legend_gap,
        legend_columns=legend_columns,
        legend_style=legend_style,
    )

    if year is None:
        target_year = date.today().year
    else:
        target_year = year
    if not 1 <= target_year <= 9999:
        _fail(f"anno non valido: {target_year}")

    layout = config.layout
    show_names = layout.show_holiday_names if holiday_names is None else holiday_names
    show_legend = layout.show_holiday_legend if legend is None else legend
    month_scale = max(scale if scale is not None else layout.single_month_scale, 0.1)

    if per_month and month is not None:
        _fail("--per-month genera tutti i mesi: non usarlo insieme a --month")

    if per_month:
        directory = _resolve_output_dir(output, target_year)
        for month_number in range(1, 13):
            _emit(
                directory / _default_filename(target_year, month_number),
                build_single_month(target_year, month_number, config),
                config,
                columns=1,
                scale=month_scale,
                title=title,
                show_holiday_names=show_names,
                include_legend=show_legend,
            )
        return

    if month is None:
        model = build_year(target_year, config)
        render_columns = max(1, columns if columns is not None else layout.columns)
        render_scale = 1.0
    else:
        model = build_single_month(target_year, month, config)
        render_columns = 1
        render_scale = month_scale

    _emit(
        _resolve_output(output, target_year, month),
        model,
        config,
        columns=render_columns,
        scale=render_scale,
        title=title,
        show_holiday_names=show_names,
        include_legend=show_legend,
    )


@app.command("init-config")
def init_config(
    output: Annotated[Path, typer.Option("--output", "-o", help="Dove scrivere il file YAML.")] = Path("calendar.yaml"),
    force: Annotated[bool, typer.Option("--force", "-f", help="Sovrascrive un file esistente.")] = False,
) -> None:
    """Scrive un file di configurazione YAML con tutti i valori di default."""
    if output.exists() and not force:
        _fail(f"{output} esiste già (usa --force per sovrascrivere)")
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(config_template(), encoding="utf-8")
    except OSError as exc:
        _fail(f"impossibile scrivere {output}: {exc}")
    typer.secho(f"Configurazione scritta in {output}", fg=typer.colors.GREEN)


@app.command("holidays")
def holidays_command(
    config_path: Annotated[Path | None, CONFIG_OPTION] = None,
    year: Annotated[int | None, typer.Option("--year", "-y", help="Anno di riferimento.")] = None,
) -> None:
    """Elenca festività e date speciali con il giorno della settimana."""
    config = _load(config_path)
    target_year = date.today().year if year is None else year

    markers = {HOLIDAY: "", SPECIAL: "[speciale]"}
    rows: list[tuple[str, str, str]] = []
    for kind, dates in ((HOLIDAY, config.holidays), (SPECIAL, config.special_dates)):
        for key, item in dates.items():
            name = item.name
            month, day = (int(part) for part in key.split("-"))
            marker = markers[kind]
            label = " ".join(part for part in (marker, name) if part)
            try:
                when = date(target_year, month, day)
            except ValueError:
                rows.append((key, "-", f"{label} (data non valida nel {target_year})"))
                continue
            rows.append((when.strftime("%d/%m/%Y"), config.day_label(when.weekday()), label))

    if not rows:
        typer.echo("Nessuna ricorrenza configurata.")
        return

    typer.secho(f"Ricorrenze {target_year} ({len(rows)})", bold=True)
    for when, weekday, name in rows:
        suffix = f"  {name}" if name else ""
        typer.echo(f"  {when}  {weekday:<10}{suffix}")


@app.command("info")
def info_command(
    config_path: Annotated[Path | None, CONFIG_OPTION] = None,
) -> None:
    """Mostra la configurazione risolta (nomi, festività, font, palette, layout)."""
    config = _load(config_path)
    source = str(config.source) if config.source else "default integrati"

    typer.secho(f"Configurazione: {source}", bold=True)
    typer.echo(f"  Settimana inizia il: {config.day_names[config.week_start]}")
    typer.echo(f"  Fine settimana: {', '.join(config.day_names[i] for i in sorted(config.weekend))}")
    typer.echo(f"  Righe fisse da 6: {'sì' if config.fixed_weeks else 'no'}")
    typer.echo(f"  Festività configurate: {len(config.holidays)}")
    typer.echo(f"  Date speciali configurate: {len(config.special_dates)}")
    typer.echo(f"  Mesi: {', '.join(config.month_names)}")
    if config.has_month_second_names:
        second = [config.month_second_name(m) or '—' for m in range(1, 13)]
        typer.echo(f"  Secondi nomi: {', '.join(second)}")
        typer.echo(f"  Posizione secondo nome: {config.layout.month_second_position}")
    else:
        typer.echo("  Secondi nomi: non configurati")
    typer.echo(f"  Giorni: {', '.join(config.day_names)}")
    typer.echo(f"  Giorni (brevi): {', '.join(config.day_short_names)}")

    typer.secho("Font", bold=True)
    typer.echo(f"  famiglia: {config.font.family}")
    typer.echo(f"  titoli: {config.font.title_stack}")
    if config.has_month_second_names:
        typer.echo(f"  secondi nomi: {config.font.month_second_stack}")
    typer.echo(
        "  corpi: "
        f"titolo {config.font.year_title_size}, mese {config.font.month_title_size}, "
        f"giorni {config.font.weekday_size}, numeri {config.font.day_size}, "
        f"festività {config.font.holiday_size}"
    )

    typer.secho("Palette", bold=True)
    for field, value in asdict(config.palette).items():
        typer.echo(f"  {field}: {value}")

    typer.secho("Layout", bold=True)
    typer.echo(
        f"  colonne {config.layout.columns}, cella {config.layout.cell_width}x{config.layout.cell_height}, "
        f"scala mese singolo {config.layout.single_month_scale}, "
        f"linee griglia {'sì' if config.layout.grid_lines else 'no'}"
    )
    typer.echo(
        f"  nomi festività nelle celle: {'sì' if config.layout.show_holiday_names else 'no'}, "
        f"fino a {config.layout.holiday_name_lines} righe"
    )
    typer.echo(
        "  specchietto festività: "
        f"{'sì' if config.layout.show_holiday_legend else 'no'}, "
        f"{config.layout.legend_columns} colonne, stile {config.layout.legend_style}, "
        f"titolo {config.layout.legend_title!r}"
    )
    typer.echo(
        f"  stacco dallo specchietto: {config.layout.legend_gap} px, "
        f"righe per nome {config.layout.legend_name_lines or 'quante servono'}"
    )

    block = calendar_block_size(
        build_single_month(date.today().year, 1, config),
        config,
        columns=1,
        scale=config.layout.single_month_scale,
    )
    year_block = calendar_block_size(build_year(date.today().year, config), config)
    typer.echo(
        f"  blocco calendario: mese {round(block[0], 1)}x{round(block[1], 1)} px, "
        f"anno {round(year_block[0], 1)}x{round(year_block[1], 1)} px"
    )
    typer.echo(f"  righe vista a mese singolo: {config.layout.single_month_rows or 'auto'}")


def main() -> None:
    """Entry point del comando ``mataresos``."""
    app()
