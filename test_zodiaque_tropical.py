"""Focused tests for NASA response parsing, time handling and sky geometry."""

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import matplotlib
import pytest

matplotlib.use("Agg")

from matplotlib import pyplot as plt

from zodiaque_tropical import (
    SolarPosition,
    build_request_url,
    create_chart,
    create_parser,
    parse_date,
    parse_horizons_response,
    tropical_sign,
)

NASA_SAMPLE = (
    "Date__(UT)__HR:MN, , , ObsEcLon, ObsEcLat,\n"
    "$$SOE\n"
    "2026-Dec-03 12:00, , , 251.3261383, -0.0000390,\n"
    "2026-Dec-03 12:01, , , 251.3268426, -0.0000391,\n"
    "$$EOE\n"
)


def test_given_nasa_response_when_parsed_then_returns_first_solar_position() -> None:
    assert parse_horizons_response(NASA_SAMPLE) == (251.3261383, -0.0000390)


@pytest.mark.parametrize(
    "response",
    [
        "API ERROR: target not found",
        "ObsEcLon $$SOE\n2026-Dec-03 12:00, , , 251, 0",
        "ObsEcLon $$SOE\n$$EOE",
        NASA_SAMPLE.replace("251.3261383", "n.a."),
        NASA_SAMPLE.replace("251.3261383", "nan"),
        NASA_SAMPLE.replace("251.3261383", "360"),
        NASA_SAMPLE.replace("-0.0000390", "91"),
    ],
)
def test_given_invalid_response_when_parsed_then_raises(response: str) -> None:
    with pytest.raises(ValueError):
        parse_horizons_response(response)


def test_given_timezone_offset_when_parsed_then_preserves_utc_instant() -> None:
    assert parse_date("2026-12-03T13:00:00+01:00") == datetime(
        2026, 12, 3, 12, tzinfo=UTC,
    )


@pytest.mark.parametrize(
    "value",
    ["2026-12-03", "2026-12-03T12:00:00", "bad-date", "2026-12-03T12:00:00.123Z"],
)
def test_given_invalid_date_when_cli_parses_then_fails(value: str) -> None:
    with pytest.raises(SystemExit) as error:
        create_parser().parse_args(["--date", value])
    assert error.value.code == 2


def test_given_default_cli_when_parsed_then_uses_requested_december_instant() -> None:
    assert create_parser().parse_args([]).date == parse_date("2026-12-03T12:00:00Z")


def test_given_utc_instant_when_request_built_then_uses_geocentric_sun_and_quantity31() -> None:
    url = build_request_url(parse_date("2026-12-03T12:34:56Z"))
    parameters = parse_qs(urlparse(url).query)

    assert parameters["COMMAND"] == ["'10'"]
    assert parameters["CENTER"] == ["'500@399'"]
    assert parameters["QUANTITIES"] == ["'31'"]
    assert parameters["START_TIME"] == ["'2026-12-03 12:34:56'"]
    assert parameters["STOP_TIME"] == ["'2026-12-03 12:35:56'"]


@pytest.mark.parametrize(
    ("longitude", "name", "degrees"),
    [
        (0, "Bélier", 0),
        (29.999, "Bélier", 29.999),
        (30, "Taureau", 0),
        (240, "Sagittaire", 0),
        (251.3261383, "Sagittaire", 11.3261383),
        (270, "Capricorne", 0),
        (360, "Bélier", 0),
        (-1, "Poissons", 29),
    ],
)
def test_given_longitude_when_classified_then_respects_half_open_sectors(
    longitude: float, name: str, degrees: float,
) -> None:
    actual_name, actual_degrees = tropical_sign(longitude)

    assert actual_name == name
    assert actual_degrees == pytest.approx(degrees)


def test_given_nasa_sun_when_chart_created_then_plots_equal_sectors_and_exact_point(
    tmp_path: Path,
) -> None:
    position = SolarPosition(
        parse_date("2026-12-03T12:00:00Z"), 251.3261383, -0.0000390, NASA_SAMPLE, "url",
    )

    figure, axes = create_chart(position)
    try:
        assert len(axes.patches) == 12
        assert [patch.get_width() for patch in axes.patches] == [30] * 12
        assert [patch.get_x() for patch in axes.patches] == list(range(0, 360, 30))
        assert axes.collections[0].get_offsets()[0].tolist() == [
            position.longitude, position.latitude,
        ]
        assert axes.get_xlim() == (0, 360)
        assert axes.get_ylim() == (-90, 90)
        output = tmp_path / "chart.png"
        figure.savefig(output)
        assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    finally:
        plt.close(figure)
