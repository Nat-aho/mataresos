"""Test di base per la configurazione, la costruzione e il rendering."""

from __future__ import annotations

import re
from datetime import date
from xml.etree import ElementTree

import pytest
import yaml

from mataresos import (
    HOLIDAY,
    SPECIAL,
    build_month,
    build_single_month,
    build_year,
    calendar_block_size,
    config_template,
    load_config,
    render_calendar,
)
from mataresos.config import ConfigError, build_config, default_config


def test_default_config_matches_template() -> None:
    """Il template YAML scritto da ``init-config`` deve valere i default."""
    assert yaml.safe_load(config_template()) == default_config()


def test_default_config_is_not_shared() -> None:
    first = default_config()
    first["layout"]["columns"] = 99
    assert default_config()["layout"]["columns"] == 3


def test_partial_config_overrides_single_value(tmp_path) -> None:
    path = tmp_path / "calendar.yaml"
    path.write_text("palette:\n  day: '#123456'\n", encoding="utf-8")

    config = load_config(path)

    assert config.palette.day == "#123456"
    assert config.palette.title == "#1c1c1c"  # resto dei default intatto
    assert config.source == path


def test_holidays_replace_defaults(tmp_path) -> None:
    path = tmp_path / "calendar.yaml"
    path.write_text("holidays:\n  '12-24': Vigilia\n", encoding="utf-8")

    config = load_config(path)

    assert {key: holiday.name for key, holiday in config.holidays.items()} == {"12-24": "Vigilia"}
    assert config.holiday_on(12, 25) is None


def test_unknown_key_is_rejected() -> None:
    with pytest.raises(ConfigError, match="non riconosciuta"):
        build_config({"palette": {"not_a_colour": "#fff"}})


def test_bad_holiday_date_is_rejected() -> None:
    with pytest.raises(ConfigError, match="formato MM-GG"):
        build_config({"holidays": {"25/12/2026": "Natale"}})


def test_weekday_resolution_by_name() -> None:
    config = build_config({"calendar": {"week_start": "sunday", "weekend": ["sabato", "domenica"]}})
    assert config.week_start == 6
    assert config.weekend == frozenset({5, 6})
    assert config.weekday_order == (6, 0, 1, 2, 3, 4, 5)


def test_build_month_alignment() -> None:
    config = build_config(None)
    grid = build_month(2026, 1, config)  # gennaio 2026 inizia di giovedì

    assert grid.name == "Gennaio"
    assert grid.row_count == 6
    first_week = grid.weeks[0]
    assert [cell.day if cell else None for cell in first_week] == [None, None, None, 1, 2, 3, 4]
    # l'ultima settimana rispetta comunque le 7 colonne
    assert all(len(week) == 7 for week in grid.weeks)
    assert len(grid.days()) == 31


def test_single_month_reserves_rows_for_a_fixed_height() -> None:
    config = build_config(None)

    # febbraio 2026 inizia di domenica: 6 celle vuote + 28 giorni -> 5 righe
    assert build_single_month(2026, 2, config).months[0].row_count == 6  # default: altezza fissa
    assert build_month(2026, 2, config, rows=0).row_count == 5
    assert build_month(2026, 2, config, rows=None).row_count == 6  # fixed_weeks


def test_every_month_has_the_same_size() -> None:
    config = build_config(None)

    sizes = set()
    for month in range(1, 13):
        svg = render_calendar(
            build_single_month(2027, month, config), config, scale=2.0, show_holiday_legend=False
        )
        root = ElementTree.fromstring(svg)
        sizes.add((root.attrib["width"], root.attrib["height"]))

    # febbraio 2027 ha 4 settimane, dicembre 5: senza righe fisse differirebbero
    assert len(sizes) == 1


def test_single_month_rows_can_be_automatic() -> None:
    config = build_config({"layout": {"single_month_rows": 0}})

    heights = {
        ElementTree.fromstring(render_calendar(build_single_month(2027, month, config), config, scale=1.0)).attrib[
            "height"
        ]
        for month in (2, 12)
    }

    assert len(heights) == 2  # 4 settimane vs 5 -> altezze diverse, come prima


def test_weekend_and_holiday_flags() -> None:
    config = build_config(None)
    grid = build_month(2026, 12, config, rows=0)
    by_day = {cell.day: cell for cell in grid.days()}

    assert by_day[25].label == "Natale"
    assert by_day[25].kind == HOLIDAY
    assert by_day[25].has_marker
    assert by_day[6].weekend  # domenica
    assert not by_day[7].weekend  # lunedì
    assert by_day[7].kind is None
    assert not by_day[7].has_marker


def test_special_dates_get_their_own_kind() -> None:
    config = build_config({"special_dates": {"03-19": "Festa del papà"}})
    grid = build_month(2026, 3, config, rows=0)
    by_day = {cell.day: cell for cell in grid.days()}

    assert config.special_date_on(3, 19).name == "Festa del papà"
    assert by_day[19].kind == SPECIAL
    assert by_day[19].label == "Festa del papà"
    # le festività di default restano intatte
    assert by_day[1].kind is None


def test_special_dates_are_empty_by_default() -> None:
    config = build_config(None)

    assert dict(config.special_dates) == {}
    assert config.special_date_on(3, 19) is None


def test_a_special_date_wins_over_a_holiday() -> None:
    config = build_config(
        {
            "holidays": {"12-25": "Natale"},
            "special_dates": {"12-25": "Compleanno"},
        }
    )
    grid = build_month(2026, 12, config, rows=0)
    by_day = {cell.day: cell for cell in grid.days()}

    # un giorno porta un solo pallino, e la data speciale ha la precedenza
    assert by_day[25].kind == SPECIAL
    assert by_day[25].label == "Compleanno"


def test_special_date_lines_can_be_given_as_a_list() -> None:
    config = build_config({"special_dates": {"03-19": ["Festa", "del papà"]}})
    grid = build_month(2026, 3, config, rows=0)
    by_day = {cell.day: cell for cell in grid.days()}

    assert by_day[19].label == "Festa del papà"
    assert by_day[19].label_lines == ("Festa", "del papà")


def test_special_dates_use_the_special_colours() -> None:
    config = build_config(
        {
            "special_dates": {"03-19": "Festa del papà"},
            "palette": {
                "special_background": "#ffff00",
                "special_day": "#ff0000",
                "special_name": "#cc0000",
            },
            "layout": {"show_holiday_names": True},
        }
    )
    svg = render_calendar(build_single_month(2026, 3, config), config, scale=1.0, show_holiday_legend=False)

    assert "#ffff00" in svg  # pallino giallo
    assert "#ff0000" in svg  # numero rosso
    assert "#cc0000" in svg  # nome rosso


def test_special_dates_appear_in_the_legend_with_their_colour() -> None:
    config = build_config(
        {
            "special_dates": {"03-19": "Festa del papà"},
            "palette": {"special_background": "#ffff00"},
            "layout": {"cell_width": 100.0},  # una colonna larga: il nome sta su una riga
        }
    )
    svg = render_calendar(build_single_month(2026, 3, config), config, scale=1.0)

    assert "19/03" in _texts(svg)
    assert "Festa del papà" in _texts(svg)
    assert "#ffff00" in svg
    # la festività di default resta nel suo colore
    assert "#b5404a" in svg


def test_legend_names_share_the_holiday_colour() -> None:
    config = build_config(
        {
            "special_dates": {"03-19": "Festa del papà"},
            "palette": {"special_name": "#00ff00", "holiday_name": "#123456"},
            "layout": {"cell_width": 100.0},
        }
    )
    svg = render_calendar(build_single_month(2026, 3, config), config, scale=1.0)

    # in legenda il nome usa il colore dei nomi delle festività, qualunque sia il tipo
    assert "#123456" in svg
    # ``special_name`` vale solo per il nome dentro la cella, che qui è disattivato
    assert "#00ff00" not in svg


def test_invalid_special_date_is_rejected() -> None:
    with pytest.raises(ConfigError, match="special_dates"):
        build_config({"special_dates": {"19/03/2026": "Festa"}})


def test_special_dates_keep_their_own_list_separate_from_holidays() -> None:
    config = build_config({"special_dates": {"03-19": "Festa del papà"}})

    # sostituire le date speciali non tocca le festività, e viceversa
    assert config.holiday_on(12, 25).name == "Natale"
    assert config.special_date_on(3, 19).name == "Festa del papà"


def test_configurable_names_are_used() -> None:
    config = build_config(
        {
            "months": {"names": [f"M{i}" for i in range(1, 13)]},
            "days": {"names": [f"G{i}" for i in range(7)], "short": [f"g{i}" for i in range(7)]},
        }
    )
    grid = build_month(2026, 3, config)
    assert grid.name == "M3"
    assert config.day_label(0) == "G0"
    assert config.day_label(6, short=True) == "g6"


def test_render_year_is_valid_svg() -> None:
    config = build_config(None)
    model = build_year(2026, config)

    svg = render_calendar(model, config, columns=3, title="2026")

    assert svg.startswith("<?xml")
    root = ElementTree.fromstring(svg)
    assert root.tag.endswith("svg")
    assert root.attrib["width"] == "1178"
    # dodici titoli di mese
    texts = [element.text for element in root.iter() if element.tag.endswith("text")]
    assert texts.count("Gennaio") == 1
    assert texts.count("Dicembre") == 1


def test_render_single_month_scales_up() -> None:
    config = build_config(None)
    model = build_single_month(2026, 6, config)

    svg = render_calendar(model, config, columns=1, scale=2.0, title="Giugno 2026")

    root = ElementTree.fromstring(svg)
    # larghezza = 2 * (44 * 2) padding + (7 * 46 * 2) celle + 2 * (12 * 2) margini mese
    assert float(root.attrib["width"]) == 868
    assert "Giugno 2026" in "".join(element.text or "" for element in root.iter())


def test_holiday_names_can_be_hidden() -> None:
    config = build_config(None)
    model = build_single_month(2026, 12, config)

    with_names = render_calendar(model, config, scale=1.0, show_holiday_names=True, show_holiday_legend=False)
    without_names = render_calendar(model, config, scale=1.0, show_holiday_names=False, show_holiday_legend=False)

    assert "Natale" in with_names
    assert "Natale" not in without_names
    assert len(without_names) < len(with_names)


def test_weekend_colours_are_configurable() -> None:
    config = build_config({"palette": {"day_weekend": "#ff00ff", "holiday_background": "#00ff00"}})
    model = build_single_month(2026, 12, config)  # dicembre contiene 8 e 25

    svg = render_calendar(model, config, scale=1.0)

    assert "#ff00ff" in svg
    assert "#00ff00" in svg


def test_holiday_font_is_smaller_than_day_font() -> None:
    config = build_config(None)
    assert config.font.holiday_size < config.font.day_size


def _texts(svg: str) -> list[str]:
    return [element.text or "" for element in _root(svg).iter() if element.tag.endswith("text")]


def _root(svg: str) -> ElementTree.Element:
    return ElementTree.fromstring(svg)


def _legend_anchors(svg: str) -> list[tuple[float, float]]:
    """Posizioni delle date nello specchietto: una voce per festività."""
    return [
        (float(element.attrib["x"]), float(element.attrib["y"]))
        for element in _root(svg).iter()
        if element.tag.endswith("text") and re.fullmatch(r"\d{2}/\d{2}", element.text or "")
    ]


def _legend_box(root: ElementTree.Element) -> dict[str, str]:
    """Attributi del riquadro della legenda, disegnato dopo quello dei mesi."""
    boxes = [element.attrib for element in root.iter() if element.tag.endswith("rect") and "rx" in element.attrib]
    return boxes[-1]


def _box_height(svg: str) -> float:
    return float(_legend_box(_root(svg))["height"])


def _text_element(svg: str, content: str) -> dict[str, str]:
    """Attributi dell'elemento ``text`` con quel contenuto esatto."""
    return next(
        element.attrib
        for element in _root(svg).iter()
        if element.tag.endswith("text") and element.text == content
    )


def test_long_holiday_name_wraps_across_lines() -> None:
    config = build_config(None)
    model = build_single_month(2026, 4, config)  # 25 aprile: Festa della Liberazione

    texts = _texts(render_calendar(model, config, scale=2.0, show_holiday_names=True, show_holiday_legend=False))

    assert "Festa della" in texts
    assert "Liberazione" in texts
    # il nome non sta più su una sola riga
    assert "Festa della Liberazione" not in texts


def test_holiday_name_is_truncated_when_lines_run_out() -> None:
    name = "Solennità della Beata Vergine Immacolata Concezione"
    config = build_config({"holidays": {"03-01": name}, "layout": {"holiday_name_lines": 2}})
    model = build_single_month(2026, 3, config)

    texts = _texts(render_calendar(model, config, scale=1.0, show_holiday_names=True, show_holiday_legend=False))

    assert name not in texts
    assert any(text.endswith("\u2026") for text in texts), "l'eccedenza deve finire con i puntini"


def test_holiday_name_lines_limit_is_respected() -> None:
    config = build_config(
        {
            "holidays": {"05-01": "Festa del Lavoro dei Lavoratori Tutti"},
            "layout": {"holiday_name_lines": 3},
        }
    )
    model = build_single_month(2026, 5, config)

    texts = _texts(render_calendar(model, config, scale=1.0, show_holiday_names=True, show_holiday_legend=False))
    fragments = [text for text in texts if text.split(" ")[0] in {"Festa", "Lavoro", "dei", "Lavoratori", "Tutti", "del"}]

    assert 1 < len(fragments) <= 3


def test_legend_lists_the_holidays_of_the_rendered_months() -> None:
    config = build_config(None)
    model = build_year(2026, config)

    texts = _texts(render_calendar(model, config, columns=3, title="2026"))

    assert "Festività" in texts
    assert "01/01" in texts
    assert "Festa della Liberazione" in texts  # nome lungo, intero nello specchietto
    assert "25/12" in texts


def test_legend_only_covers_the_rendered_month() -> None:
    config = build_config(None)
    model = build_single_month(2026, 12, config)

    joined = " ".join(_texts(render_calendar(model, config, scale=2.0)))

    assert "25/12" in joined
    assert "01/01" not in joined
    assert "Liberazione" not in joined


def test_legend_is_skipped_without_named_holidays() -> None:
    config = build_config({"holidays": {}})
    model = build_single_month(2026, 12, config)

    svg = render_calendar(model, config, scale=2.0)

    assert "Festività" not in svg
    assert "circle" not in svg  # cala anche il pallino: nessuna festività


def test_legend_can_be_disabled() -> None:
    config = build_config(None)
    model = build_single_month(2026, 12, config)

    with_legend = render_calendar(model, config, scale=2.0)
    without_legend = render_calendar(model, config, scale=2.0, show_holiday_legend=False)

    assert "Festività" in with_legend
    assert "Festività" not in without_legend
    assert float(_root(without_legend).attrib["height"]) < float(_root(with_legend).attrib["height"])


def test_calendar_stays_clean_by_default() -> None:
    config = build_config(None)
    assert config.layout.show_holiday_names is False
    assert config.layout.show_holiday_legend is True

    root = _root(render_calendar(build_single_month(2026, 12, config), config, scale=1.0))

    def text_y(content: str) -> float:
        element = next(e for e in root.iter() if e.tag.endswith("text") and e.text == content)
        return float(element.attrib["y"])

    # 24 (giovedì) e 25 (venerdì, festivo) sono nella stessa riga: il festivo
    # non sposta il numero, che resta allineato a tutti gli altri giorni.
    assert text_y("24") == text_y("25")


def test_page_height_is_the_same_for_every_month() -> None:
    config = build_config(None)

    heights = {
        _root(render_calendar(build_single_month(2027, month, config), config, scale=1.0)).attrib["height"]
        for month in range(1, 13)
    }

    # l'ingombro della legenda dipende dalla configurazione, non dal mese disegnato
    assert len(heights) == 1


def test_legend_uses_five_columns() -> None:
    config = build_config(None)
    model = build_year(2026, config)

    anchors = _legend_anchors(render_calendar(model, config, columns=3, title="2026"))

    assert len(anchors) == 10  # una voce per festività
    assert len({x for x, _ in anchors}) == 5  # cinque colonne di default
    assert len({y for _, y in anchors}) == 2  # 10 voci su 5 colonne = 2 righe


def test_legend_columns_is_configurable() -> None:
    config = build_config({"layout": {"legend_columns": 2}})
    model = build_year(2026, config)

    anchors = _legend_anchors(render_calendar(model, config, columns=3, title="2026"))

    assert len({x for x, _ in anchors}) == 2
    assert len({y for _, y in anchors}) == 5  # 10 voci su 2 colonne = 5 righe


def test_invalid_legend_columns_is_rejected() -> None:
    with pytest.raises(ConfigError, match="legend_columns"):
        build_config({"layout": {"legend_columns": 0}})


def test_legend_grows_a_row_when_a_month_exceeds_five_entries() -> None:
    holidays = {f"05-0{day}": f"Voce {day}" for day in range(1, 8)}
    config = build_config({"holidays": holidays})
    model = build_single_month(2026, 5, config)

    anchors = _legend_anchors(render_calendar(model, config, scale=1.0))

    # sette voci non si perdono: si aggiunge una riga, le colonne restano cinque
    assert len(anchors) == 7
    assert len({x for x, _ in anchors}) == 5
    assert len({y for _, y in anchors}) == 2


def test_bottom_legend_follows_the_calendar_width() -> None:
    config = build_config(None)
    model = build_year(2026, config)
    content_w, _ = calendar_block_size(model, config, columns=3)

    root = _root(render_calendar(model, config, columns=3, title="2026"))

    assert float(_legend_box(root)["width"]) == pytest.approx(content_w)


def test_months_reserve_the_legend_even_without_holidays() -> None:
    config = build_config(None)

    with_holidays = _root(render_calendar(build_single_month(2026, 12, config), config, scale=2.0))
    without = _root(render_calendar(build_single_month(2026, 3, config), config, scale=2.0))

    # marzo non ha festività ma deve avere lo stesso ingombro di dicembre
    assert without.attrib["width"] == with_holidays.attrib["width"]
    assert without.attrib["height"] == with_holidays.attrib["height"]


def test_empty_legend_area_is_reserved_but_not_drawn() -> None:
    config = build_config(None)

    empty = render_calendar(build_single_month(2026, 3, config), config, scale=2.0)
    drawn = render_calendar(build_single_month(2026, 12, config), config, scale=2.0)

    def boxes(svg: str) -> int:
        return len([e for e in _root(svg).iter() if e.tag.endswith("rect") and "rx" in e.attrib])

    # marzo: solo il riquadro del mese. dicembre: mese + legenda.
    assert boxes(empty) == 1
    assert boxes(drawn) == 2
    assert "Festività" not in _texts(empty)
    assert "Festività" in _texts(drawn)


def test_legend_is_below_the_grid() -> None:
    config = build_config(None)
    model = build_single_month(2026, 12, config)

    root = _root(render_calendar(model, config, scale=1.0))
    boxes = [element.attrib for element in root.iter() if element.tag.endswith("rect") and "rx" in element.attrib]

    assert len(boxes) == 2  # riquadro del mese, poi la legenda
    assert boxes[1]["x"] == boxes[0]["x"]
    assert boxes[1]["width"] == boxes[0]["width"]
    assert float(boxes[1]["y"]) > float(boxes[0]["y"])


def test_legend_gap_is_configurable() -> None:
    def page_height(gap: float) -> float:
        config = build_config({"layout": {"legend_gap": gap}})
        model = build_single_month(2026, 12, config)
        return float(ElementTree.fromstring(render_calendar(model, config, scale=1.0)).attrib["height"])

    # come le altre misure di layout, lo stacco segue --scale (qui 1.0)
    assert page_height(80.0) - page_height(10.0) == pytest.approx(70.0)


def test_month_second_names_are_optional() -> None:
    config = build_config(None)

    assert config.month_second_names == ("",) * 12
    assert not config.has_month_second_names
    assert config.month_second_name(9) == ""


def test_second_month_name_is_drawn_below_the_main_one() -> None:
    config = build_config(
        {
            "months": {
                "names": [f"M{i}" for i in range(1, 13)],
                "second_names": [None] * 8 + ["Setembre", "Octubre", "Novembre", "Desembre"],
            }
        }
    )

    svg = render_calendar(build_single_month(2026, 9, config), config, scale=1.0)

    assert float(_text_element(svg, "Setembre")["y"]) > float(_text_element(svg, "M9")["y"])
    assert float(_text_element(svg, "Setembre")["font-size"]) < float(_text_element(svg, "M9")["font-size"])


def test_second_name_space_is_reserved_when_absent() -> None:
    config = build_config(
        {
            "months": {
                "names": [f"M{i}" for i in range(1, 13)],
                "second_names": [None] * 11 + ["Desembre"],
            }
        }
    )

    with_second = _root(render_calendar(build_single_month(2026, 12, config), config, scale=1.0))
    without = _root(render_calendar(build_single_month(2026, 9, config), config, scale=1.0))

    # settembre non ha secondo nome ma occupa lo stesso spazio di dicembre
    assert with_second.attrib["width"] == without.attrib["width"]
    assert with_second.attrib["height"] == without.attrib["height"]


def test_no_reserved_space_without_second_names() -> None:
    plain = build_config(None)
    with_second = build_config({"months": {"second_names": [None] * 8 + ["Setembre"] * 4}})

    assert not plain.has_month_second_names
    assert with_second.has_month_second_names

    flat = _root(render_calendar(build_single_month(2026, 9, plain), plain, scale=1.0))
    taller = _root(render_calendar(build_single_month(2026, 9, with_second), with_second, scale=1.0))

    # senza secondi nomi in configurazione la fascia del titolo resta quella di sempre
    assert float(taller.attrib["height"]) > float(flat.attrib["height"])


def test_second_names_length_is_validated() -> None:
    with pytest.raises(ConfigError, match="months.second_names"):
        build_config({"months": {"second_names": ["Setembre"]}})


def test_page_background_is_painted_by_default() -> None:
    config = build_config(None)
    svg = render_calendar(build_single_month(2026, 12, config), config, scale=1.0)

    origin = [
        element.attrib
        for element in _root(svg).iter()
        if element.tag.endswith("rect") and element.attrib.get("x") == "0" and element.attrib.get("y") == "0"
    ]

    assert len(origin) == 1
    assert origin[0]["fill"] == "#f6f6f3"


@pytest.mark.parametrize("colour", ["transparent", "none", "TRANSPARENT"])
def test_page_background_can_be_transparent(colour: str) -> None:
    config = build_config({"palette": {"page_background": colour}})
    svg = render_calendar(build_single_month(2026, 12, config), config, scale=1.0)

    origin = [
        element.attrib
        for element in _root(svg).iter()
        if element.tag.endswith("rect") and element.attrib.get("x") == "0" and element.attrib.get("y") == "0"
    ]

    # niente rettangolo di fondo: l'SVG si può sovrapporre ad altro
    assert origin == []
    assert "Festività" in _texts(svg)  # il resto è disegnato normalmente


def test_title_family_falls_back_to_the_body_family() -> None:
    config = build_config({"font": {"family": "BodyFont"}})

    svg = render_calendar(build_single_month(2026, 9, config), config, scale=1.0)

    assert _text_element(svg, "Settembre")["font-family"] == "BodyFont"


def test_title_family_can_differ_from_the_body() -> None:
    config = build_config({"font": {"family": "BodyFont", "title_family": "TitleFont"}})

    svg = render_calendar(build_single_month(2026, 9, config), config, scale=1.0)

    # il titolo usa la famiglia display, i giorni restano leggibili
    assert _text_element(svg, "Settembre")["font-family"] == "TitleFont"
    assert _text_element(svg, "1")["font-family"] == "BodyFont"


def test_month_second_name_can_use_its_own_family() -> None:
    config = build_config(
        {
            "months": {"names": [f"M{i}" for i in range(1, 13)], "second_names": [None] * 8 + ["Setembre"] * 4},
            "font": {"family": "BodyFont", "title_family": "TitleFont", "month_second_family": "SerifFont"},
        }
    )

    svg = render_calendar(build_single_month(2026, 9, config), config, scale=1.0)

    assert _text_element(svg, "M9")["font-family"] == "TitleFont"
    assert _text_element(svg, "Setembre")["font-family"] == "SerifFont"


def test_weekend_weight_defaults_to_the_day_weight() -> None:
    config = build_config({"font": {"day_weight": 300}})

    assert config.font.weekend_weight == 0
    assert config.font.weekend_text_weight == 300


def test_weekend_days_can_be_bold() -> None:
    config = build_config({"font": {"day_weight": 400, "weekend_weight": 700}})

    svg = render_calendar(build_single_month(2026, 9, config), config, scale=1.0)

    # settembre 2026: il 5 e il 6 sono sabato e domenica, il 7 lunedì
    assert _text_element(svg, "5")["font-weight"] == "700"
    assert _text_element(svg, "6")["font-weight"] == "700"
    assert _text_element(svg, "7")["font-weight"] == "400"
    # anche le sigle in intestazione seguono lo stesso peso
    assert _text_element(svg, "Sab")["font-weight"] == "700"
    assert _text_element(svg, "Lun")["font-weight"] == "400"


def test_weekend_weight_leaves_holidays_alone() -> None:
    config = build_config({"font": {"weekend_weight": 800}})

    svg = render_calendar(build_single_month(2026, 12, config), config, scale=1.0)

    # Natale cade di venerdì ma resta su holiday_weight, non su quello del weekend
    assert _text_element(svg, "25")["font-weight"] == "700"
    assert _text_element(svg, "27")["font-weight"] == "800"  # domenica


def test_holiday_name_lines_zero_means_as_many_as_fit() -> None:
    name = "Festa del Lavoro"  # a 46px di cella si spezza esattamente su due righe

    def render(lines: int) -> list[str]:
        config = build_config(
            {
                "holidays": {"03-01": name},
                "layout": {"show_holiday_names": True, "holiday_name_lines": lines},
            }
        )
        model = build_single_month(2026, 3, config)
        return _texts(render_calendar(model, config, scale=1.0, show_holiday_legend=False))

    # 0 = quante ne entrano: il nome sta su due righe senza troncature
    assert "Festa del" in render(0)
    assert "Lavoro" in render(0)
    assert not any(text.endswith("\u2026") for text in render(0))

    # un tetto esplicito di una riga invece tronca
    assert any(text.endswith("\u2026") for text in render(1))


def test_holiday_lines_can_be_given_as_a_list() -> None:
    config = build_config(
        {
            "holidays": {"09-29": ["Sant Miquel", "Patró de l'Alguer"]},
            "layout": {"show_holiday_names": True, "cell_width": 100.0},
        }
    )

    holiday = config.holidays["09-29"]
    assert holiday.lines == ("Sant Miquel", "Patró de l'Alguer")
    assert holiday.explicit_lines
    assert holiday.name == "Sant Miquel Patró de l'Alguer"

    svg = render_calendar(build_single_month(2026, 9, config), config, scale=1.0, show_holiday_legend=False)
    texts = _texts(svg)

    # le due righe indicate restano separate
    assert "Sant Miquel" in texts
    assert "Patró de l'Alguer" in texts


def test_holiday_lines_control_where_the_name_breaks() -> None:
    layout = {"show_holiday_names": True, "cell_width": 100.0}

    def texts_for(value: object) -> list[str]:
        config = build_config({"holidays": {"09-29": value}, "layout": layout})
        model = build_single_month(2026, 9, config)
        return _texts(render_calendar(model, config, scale=1.0, show_holiday_legend=False))

    # con la lista il punto di rottura lo decido io
    assert "Sant Miquel" in texts_for(["Sant Miquel", "Patró de l'Alguer"])
    # con la stringa lo sceglie il wrapping, e la riga cade altrove
    assert "Sant Miquel Patró de" in texts_for("Sant Miquel Patró de l'Alguer")
    assert "Sant Miquel" not in texts_for("Sant Miquel Patró de l'Alguer")


def test_holiday_list_value_is_validated() -> None:
    with pytest.raises(ConfigError, match="lista di righe"):
        build_config({"holidays": {"09-29": 42}})


def test_legend_respects_the_explicit_holiday_lines() -> None:
    config = build_config(
        {"holidays": {"09-29": ["Sant Miquel", "Patró de l'Alguer"]}, "layout": {"cell_width": 100.0}}
    )
    model = build_single_month(2026, 9, config)

    texts = _texts(render_calendar(model, config, scale=1.0))

    # ogni voce della lista sta su una riga propria anche nella legenda
    assert "Sant Miquel" in texts
    assert "Patró de l'Alguer" in texts
    assert "Sant Miquel Patró de l'Alguer" not in texts


def test_legend_entry_is_centred_on_its_column() -> None:
    config = build_config({"holidays": {"06-01": "Prova"}, "layout": {"cell_width": 100.0}})
    model = build_single_month(2026, 6, config)

    svg = render_calendar(model, config, scale=1.0)
    dots = [element.attrib for element in _root(svg).iter() if element.tag.endswith("circle")]
    date = _text_element(svg, "01/06")
    name = _text_element(svg, "Prova")

    # pallino, data e nome sulla stessa verticale
    assert dots[-1]["cx"] == date["x"] == name["x"]
    # e in quest'ordine, dall'alto verso il basso
    assert float(dots[-1]["cy"]) < float(date["y"]) < float(name["y"])


def test_legend_columns_are_uniform() -> None:
    config = build_config({"layout": {"cell_width": 100.0}})
    model = build_year(2026, config)

    xs = sorted({x for x, _ in _legend_anchors(render_calendar(model, config, columns=3, title="2026"))})
    steps = [end - start for start, end in zip(xs, xs[1:])]

    # cinque colonne equidistanti, a meno dell'arrotondamento delle coordinate SVG
    assert len(xs) == 5
    assert max(steps) - min(steps) < 0.05


def test_legend_box_is_as_wide_as_the_calendar_block() -> None:
    config = build_config({"layout": {"cell_width": 100.0}})
    model = build_year(2026, config)

    root = _root(render_calendar(model, config, columns=3, title="2026"))
    content_w, _ = calendar_block_size(model, config, columns=3)

    assert float(_legend_box(root)["width"]) == pytest.approx(content_w)


def test_second_month_name_can_be_beside_the_title() -> None:
    months = {"names": [f"M{i}" for i in range(1, 13)], "second_names": [None] * 11 + ["Desembre"]}

    def page(position: str) -> ElementTree.Element:
        config = build_config({"months": months, "layout": {"month_second_position": position}})
        return _root(render_calendar(build_single_month(2026, 12, config), config, scale=1.0))

    beside = page("beside")
    spans = [element.attrib for element in beside.iter() if element.tag.endswith("tspan")]

    # la barra e il secondo nome sono due porzioni distinte
    assert [element.text for element in beside.iter() if element.tag.endswith("tspan")] == [" | ", "Desembre"]
    # la barra ha il corpo del titolo principale, il secondo nome il suo
    assert float(spans[0]["font-size"]) > float(spans[1]["font-size"])
    # affiancato non usa una seconda riga, quindi la pagina resta più bassa
    assert float(beside.attrib["height"]) < float(page("below").attrib["height"])


def test_beside_titles_keep_the_months_uniform() -> None:
    config = build_config(
        {
            "months": {"second_names": [None] * 8 + ["Setembre", "Octubre", "Novembre", "Desembre"]},
            "layout": {"month_second_position": "beside"},
        }
    )

    heights = {
        _root(render_calendar(build_single_month(2027, month, config), config, scale=1.0)).attrib["height"]
        for month in range(1, 13)
    }

    assert len(heights) == 1


def test_invalid_month_second_position_is_rejected() -> None:
    with pytest.raises(ConfigError, match="month_second_position"):
        build_config({"layout": {"month_second_position": "inside"}})


def test_legend_inline_puts_each_entry_on_one_row() -> None:
    name = "Mig Agost - Assumpció de Maria N.S. de basa-peus"

    def rendered(style: str) -> tuple[str, ElementTree.Element]:
        config = build_config(
            {"holidays": {"08-15": name}, "layout": {"legend_columns": 1, "legend_style": style}}
        )
        svg = render_calendar(build_single_month(2026, 8, config), config, scale=1.0)
        return svg, _root(svg)

    svg, root = rendered("inline")
    circles = [element.attrib for element in root.iter() if element.tag.endswith("circle")]
    date = _text_element(svg, "15/08")
    # una sola colonna: il nome ha tutta la larghezza e resta su una riga
    label = _text_element(svg, name)
    size = float(date["font-size"])

    # pallino, data e nome sulla stessa riga: la linea di base del testo sta 0,35 corpi
    # sotto il centro del pallino, che è esattamente come ``_baseline`` centra il testo
    assert float(date["y"]) == pytest.approx(float(circles[-1]["cy"]) + 0.35 * size, abs=0.6)
    assert label["y"] == date["y"]
    # e in quest'ordine da sinistra
    assert float(circles[-1]["cx"]) < float(date["x"]) < float(label["x"])
    # una riga sola rende il riquadro più basso delle tre fasce impilate
    assert float(_legend_box(root)["height"]) < float(_legend_box(rendered("stacked")[1])["height"])


def test_legend_reserves_only_what_the_months_need() -> None:
    holidays = {
        "08-15": ["uno", "due", "tre"],  # mese poco affollato, ma nome alto
        "12-25": "quattro",                 # mese affollato, ma nomi bassi
        "12-26": "cinque",
        "12-27": "sei",
    }
    config = build_config(
        {
            "holidays": holidays,
            # titolo vuoto: così l'altezza dipende solo dalle voci
            "layout": {"legend_columns": 1, "legend_style": "inline", "legend_title": ""},
        }
    )

    heights = {
        _box_height(render_calendar(build_single_month(2026, month, config), config, scale=1.0))
        for month in (8, 12)
    }

    # dicembre chiede più spazio: 3 voci da una riga con 0,55 corpi di spaziatura l'una,
    # cioè 3 x (1,45 + 0,55) x 8 = 48, più i margini del riquadro (12 sopra e sotto).
    # Prima si riservava 3 righe x l'altezza della voce da 3 righe: 141,6.
    assert len(heights) == 1  # tutti i mesi restano della stessa altezza
    assert next(iter(heights)) == pytest.approx(72.0)


def test_legend_content_stays_inside_the_box() -> None:
    config = build_config({"layout": {"legend_columns": 3, "legend_style": "inline"}})
    model = build_year(2026, config)

    root = _root(render_calendar(model, config, columns=3, title="2026"))
    box = _legend_box(root)
    bottom = float(box["y"]) + float(box["height"])
    ys = [float(element.attrib["y"]) for element in root.iter() if element.tag.endswith("text")]

    # la vista annuale concatena le voci di tutti i mesi: nessuna deve uscire dal riquadro
    assert max(ys) < bottom


def test_legend_dot_aligns_with_the_first_day_column() -> None:
    config = build_config({"layout": {"legend_columns": 1, "legend_style": "inline"}})
    model = build_single_month(2026, 6, config)  # giugno 2026 inizia di lunedì

    svg = render_calendar(model, config, scale=1.0)
    dots = [element.attrib for element in _root(svg).iter() if element.tag.endswith("circle")]
    day_one = _text_element(svg, "1")

    # il pallino della legenda sta sotto il numero del giorno della prima colonna
    assert float(dots[-1]["cx"]) == pytest.approx(float(day_one["x"]))


def test_legend_inline_content_fits_after_the_indent() -> None:
    config = build_config({"layout": {"legend_columns": 3, "legend_style": "inline"}})
    model = build_year(2026, config)

    root = _root(render_calendar(model, config, columns=3, title="2026"))
    box = _legend_box(root)
    right = float(box["x"]) + float(box["width"])
    starts = [
        float(element.attrib["x"])
        for element in root.iter()
        if element.tag.endswith("text") and element.attrib.get("text-anchor") == "start"
    ]

    # il rientro non spinge il testo fuori dal riquadro
    assert starts
    assert max(starts) < right


def test_invalid_legend_style_is_rejected() -> None:
    with pytest.raises(ConfigError, match="legend_style"):
        build_config({"layout": {"legend_style": "sideways"}})


def test_wrapping_disabled_leaves_numbers_centred() -> None:
    config = build_config(None)
    model = build_single_month(2026, 12, config)

    without = ElementTree.fromstring(render_calendar(model, config, scale=2.0, show_holiday_names=False))
    with_names = ElementTree.fromstring(render_calendar(model, config, scale=2.0, show_holiday_names=True))

    def circle_y(root: ElementTree.Element) -> float:
        return float(next(element for element in root.iter() if element.tag.endswith("circle")).attrib["cy"])

    # con i nomi visibili il pallino sale per lasciare spazio al testo
    assert circle_y(with_names) < circle_y(without)


def test_empty_model_is_rejected() -> None:
    from mataresos.models import CalendarModel

    config = build_config(None)
    with pytest.raises(ValueError):
        render_calendar(CalendarModel(year=2026, months=()), config)


def test_holiday_keys_reject_impossible_months() -> None:
    with pytest.raises(ConfigError, match="mese fuori intervallo"):
        build_config({"holidays": {"13-01": "Impossibile"}})


@pytest.mark.parametrize("month", [1, 6, 12])
def test_every_month_renders(month: int) -> None:
    config = build_config(None)
    model = build_single_month(2026, month, config)
    root = ElementTree.fromstring(render_calendar(model, config, scale=1.5))
    assert root.attrib["height"] != "0"
    assert date(2026, month, 1).year == 2026
