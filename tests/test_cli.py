"""Test dei comandi a riga di comando."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

import pytest
from typer.testing import CliRunner

from mataresos import app


def _output(result) -> str:
    """Output combinato, indipendente da come la versione di click separa stderr."""
    return result.output + (getattr(result, "stderr", "") or "")


def _size(path: Path) -> tuple[int, int]:
    root = ElementTree.fromstring(path.read_text(encoding="utf-8"))
    return int(float(root.attrib["width"])), int(float(root.attrib["height"]))


def _texts_of(path: Path) -> list[str]:
    root = ElementTree.fromstring(path.read_text(encoding="utf-8"))
    return [element.text or "" for element in root.iter() if element.tag.endswith("text")]


def test_per_month_writes_one_file_per_month(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["--year", "2027", "--per-month", "-o", str(tmp_path)])

    assert result.exit_code == 0, _output(result)
    assert sorted(path.name for path in tmp_path.glob("*.svg")) == [
        f"calendar-2027-{month:02d}.svg" for month in range(1, 13)
    ]


def test_per_month_files_sort_chronologically(tmp_path: Path) -> None:
    CliRunner().invoke(app, ["--year", "2027", "--per-month", "-o", str(tmp_path)])

    names = sorted(path.name for path in tmp_path.glob("*.svg"))

    # lo zero iniziale rende l'ordine alfabetico uguale a quello cronologico
    assert names[0] == "calendar-2027-01.svg"
    assert names[11] == "calendar-2027-12.svg"


def test_per_month_uses_default_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["--year", "2027", "--per-month"])

    assert result.exit_code == 0, _output(result)
    assert len(sorted((tmp_path / "calendar-2027").glob("*.svg"))) == 12


def test_per_month_pages_are_full_months(tmp_path: Path) -> None:
    from xml.etree import ElementTree

    CliRunner().invoke(app, ["--year", "2027", "--per-month", "-o", str(tmp_path)])

    root = ElementTree.fromstring((tmp_path / "calendar-2027-02.svg").read_text(encoding="utf-8"))
    texts = [element.text for element in root.iter() if element.tag.endswith("text")]

    assert "Febbraio" in texts
    assert "2027" not in texts  # nessun titolo automatico


def test_title_is_drawn_only_when_requested(tmp_path: Path) -> None:
    plain = tmp_path / "plain.svg"
    titled = tmp_path / "titled.svg"

    first = CliRunner().invoke(app, ["--year", "2027", "--month", "2", "-o", str(plain)])
    second = CliRunner().invoke(app, ["--year", "2027", "--month", "2", "--title", "2027", "-o", str(titled)])

    assert first.exit_code == 0, _output(first)
    assert second.exit_code == 0, _output(second)
    assert "2027" not in _texts_of(plain)
    assert "2027" in _texts_of(titled)
    assert _size(titled)[1] > _size(plain)[1]  # il titolo occupa spazio in alto


def test_per_month_conflicts_with_month_option(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["--per-month", "--month", "3", "-o", str(tmp_path)])

    assert result.exit_code == 1
    assert "--month" in _output(result)


def test_per_month_rejects_svg_file_target(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["--per-month", "-o", str(tmp_path / "uscita.svg")])

    assert result.exit_code == 1
    assert "cartella" in _output(result)


def test_month_option_still_writes_a_single_file(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["--year", "2027", "--month", "12", "-o", str(tmp_path)])

    assert result.exit_code == 0, _output(result)
    assert sorted(path.name for path in tmp_path.glob("*.svg")) == ["calendar-2027-12.svg"]


def test_no_legend_flag_writes_a_single_file(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["--year", "2027", "--month", "12", "--no-legend", "-o", str(tmp_path)])

    assert result.exit_code == 0, _output(result)
    assert sorted(path.name for path in tmp_path.glob("*.svg")) == ["calendar-2027-12.svg"]


def test_legend_gap_flag_overrides_the_config(tmp_path: Path) -> None:
    close = tmp_path / "vicino.svg"
    far = tmp_path / "lontano.svg"

    CliRunner().invoke(app, ["--year", "2027", "--month", "12", "--legend-gap", "0", "-o", str(close)])
    CliRunner().invoke(app, ["--year", "2027", "--month", "12", "--legend-gap", "100", "-o", str(far)])

    # la vista a mese singolo usa scale 2.0, quindi lo stacco raddoppia
    assert _size(far)[1] - _size(close)[1] == 200


def test_legend_columns_flag_overrides_the_config(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app, ["--year", "2027", "--month", "12", "--legend-columns", "2", "-o", str(tmp_path)]
    )

    assert result.exit_code == 0, _output(result)
    dates = [
        element.attrib["x"]
        for element in ElementTree.fromstring((tmp_path / "calendar-2027-12.svg").read_text(encoding="utf-8")).iter()
        if element.tag.endswith("text") and element.text and "/" in element.text and len(element.text) == 5
    ]

    assert len(set(dates)) == 2  # dicembre ha 3 voci, su 2 colonne


def test_invalid_legend_columns_flag_fails(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["--month", "12", "--legend-columns", "0", "-o", str(tmp_path)])

    assert result.exit_code != 0


def test_legend_style_flag_overrides_the_config(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["--year", "2027", "--month", "12", "--legend-columns", "1", "--legend-style", "inline", "-o", str(tmp_path)],
    )

    assert result.exit_code == 0, _output(result)
    svg = (tmp_path / "calendar-2027-12.svg").read_text(encoding="utf-8")

    # in linea: pallino e data condividono la linea di base del nome
    assert 'text-anchor="start"' in svg


def test_invalid_legend_style_flag_fails(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app, ["--month", "12", "--legend-style", "sideways", "-o", str(tmp_path)]
    )

    assert result.exit_code == 1
    assert "inline" in _output(result)


def test_per_month_calendars_are_identical(tmp_path: Path) -> None:
    CliRunner().invoke(app, ["--year", "2027", "--per-month", "-o", str(tmp_path)])

    calendars = sorted(tmp_path.glob("calendar-2027-??.svg"))

    assert len(calendars) == 12
    # marzo non ha festività, ma lo spazio della legenda è riservato lo stesso
    assert len({_size(path) for path in calendars}) == 1
