"""Verify geocentric geometry and rendering without fetching network data."""

import json
import math
from pathlib import Path

import matplotlib
import numpy as np
import pytest

matplotlib.use("Agg")

from matplotlib import pyplot as plt

from zodiaque_tropical import SolarPosition, parse_date
from zodiaque_tropical_3d import (
    CONSTELLATIONS,
    constellation_figures,
    create_chart_3d,
    create_chart_babylon,
    create_parser,
    ecliptic_to_cartesian,
    sphere_mesh,
)


def test_given_2026_sun_when_figures_transformed_then_preserves_all_stars_and_paths() -> None:
    position = SolarPosition(parse_date("2026-12-03T12:00:00Z"), 251.3261383, -0.0000390, "", "")
    catalogue = json.loads(
        Path(__file__).with_name("zodiac_constellations.json").read_text(encoding="utf-8"),
    )
    raw_figures = {figure["id"]: figure for figure in catalogue["figures"]}
    raw_stars = {tuple(star["geometry"]["coordinates"]): star["id"] for star in catalogue["stars"]}

    figures, source, solar_region = constellation_figures(position)

    assert {figure["id"] for figure in figures} == set(CONSTELLATIONS)
    assert solar_region == "Ophiuchus"
    assert source == catalogue["source"]
    assert len({star["hip"] for figure in figures for star in figure["stars"]}) == 163
    for figure in figures:
        assert figure["paths"] == [
            [raw_stars[tuple(point)] for point in path]
            for path in raw_figures[figure["id"]]["geometry"]["coordinates"]
        ]
        stars = {star["hip"]: star for star in figure["stars"]}
        assert set(stars) == {hip for path in figure["paths"] for hip in path}
        for star in stars.values():
            assert 0 <= star["longitude"] < 360
            assert -90 <= star["latitude"] <= 90
            assert math.isfinite(star["magnitude"])


def test_given_catalogue_star_when_transformed_then_recovers_icrs_direction() -> None:
    import astropy.units as u
    from astropy.coordinates import GeocentricTrueEcliptic, SkyCoord
    from astropy.time import Time
    from astropy.utils import iers

    position = SolarPosition(parse_date("2026-12-03T12:00:00Z"), 251.3261383, 0, "", "")

    figures, _, _ = constellation_figures(position)
    hamal = next(star for star in figures[0]["stars"] if star["hip"] == 9884)
    with iers.conf.set_temp("auto_download", False):
        instant = Time(position.instant)
        recovered = SkyCoord(
            lon=hamal["longitude"] * u.deg, lat=hamal["latitude"] * u.deg,
            frame=GeocentricTrueEcliptic(equinox=instant, obstime=instant),
        ).icrs

    assert recovered.ra.degree == pytest.approx(31.7934, abs=1e-8)
    assert recovered.dec.degree == pytest.approx(23.4624, abs=1e-8)


def test_given_different_epochs_when_transformed_then_accounts_for_precession() -> None:
    current = SolarPosition(parse_date("2026-12-03T12:00:00Z"), 251.3261383, 0, "", "")
    old = SolarPosition(parse_date("2000-12-03T12:00:00Z"), 251.3261383, 0, "", "")

    now_figures, _, _ = constellation_figures(current)
    old_figures, _, _ = constellation_figures(old)
    now_hamal = next(star for star in now_figures[0]["stars"] if star["hip"] == 9884)
    old_hamal = next(star for star in old_figures[0]["stars"] if star["hip"] == 9884)

    assert 0.3 < now_hamal["longitude"] - old_hamal["longitude"] < 0.4


@pytest.mark.parametrize(
    ("hip", "longitude", "latitude"),
    [
        (80343, 247.92320773348163, 1.549630072601366),
        (80473, 248.81009369269336, -1.7608935921122935),
        (80763, 250.13497913558012, -4.573358347168112),
    ],
)
def test_given_skyfield_de421_reference_when_stars_rendered_then_matches_independent_positions(
    hip: int, longitude: float, latitude: float,
) -> None:
    """References: Skyfield 1.55, JPL DE421, fixed catalogue ICRS, 2026-12-03 12:00 UTC."""
    position = SolarPosition(parse_date("2026-12-03T12:00:00Z"), 251.3261383, -0.000039, "", "")

    figures, _, _ = constellation_figures(position)
    star = next(star for figure in figures for star in figure["stars"] if star["hip"] == hip)

    assert star["longitude"] == pytest.approx(longitude, abs=3e-8)
    assert star["latitude"] == pytest.approx(latitude, abs=3e-8)


def test_given_skyfield_sun_when_iau_classified_then_is_ophiuchus_not_scorpius() -> None:
    from skyfield.api import load_constellation_map, position_of_radec

    # Apparent geocentric Sun computed independently with Skyfield/JPL DE421.
    reference = position_of_radec(16.62490458876028, -22.08199227994636)

    region = load_constellation_map()(reference)

    assert region == "Oph"
    assert abs(251.32615122718153 - 251.3261383) * 3600 < 0.05


def test_given_iau_borders_when_projected_then_sun_is_inside_ophiuchus_only() -> None:
    position = SolarPosition(parse_date("2026-12-03T12:00:00Z"), 251.3261383, -0.000039, "", "")

    figures, _, _ = constellation_figures(position)
    containing = []
    for figure in figures:
        for ring in figure["boundaries"]:
            assert ring[0] == pytest.approx(ring[-1], abs=1e-12)
            assert all(0 <= lon < 360 and -90 <= lat <= 90 for lon, lat in ring)
        if figure["id"] not in {"Sco", "Oph", "Sgr"}:
            continue
        ring = [
            ((lon - position.longitude + 180) % 360 - 180, lat - position.latitude)
            for lon, lat in figure["boundaries"][0]
        ]
        inside = False
        for (x1, y1), (x2, y2) in zip(ring[:-1], ring[1:], strict=True):
            if (y1 > 0) != (y2 > 0) and x1 - y1 * (x2 - x1) / (y2 - y1) > 0:
                inside = not inside
        if inside:
            containing.append(figure["id"])

    assert containing == ["Oph"]


def test_given_solar_position_when_exported_then_embeds_exact_data_and_all_signs() -> None:
    position = SolarPosition(
        parse_date("2025-12-03T12:00:00Z"), 251.2, -0.0001, "NASA response", "https://example.test",
    )

    html = create_chart_babylon(position, elevation=35, azimuth=-110)
    payload = json.loads(
        html.split('<script id="zodiac-data" type="application/json">')[1].split("</script>")[0],
    )

    assert payload["instant"] == "2025-12-03T12:00:00+00:00"
    assert payload["longitude"] == position.longitude
    assert payload["latitude"] == position.latitude
    assert payload["requestUrl"] == position.request_url
    assert len(payload["signs"]) == len(payload["colors"]) == 12
    assert payload["elevation"] == 35
    assert payload["azimuth"] == -110
    assert len(payload["constellations"]) == 13
    assert "Copyright (c) 2015, Olaf Frohn" in payload["catalogueLicense"]
    assert "__ZODIAC_DATA__" not in html


def test_given_html_in_source_url_when_exported_then_cannot_close_data_script() -> None:
    position = SolarPosition(
        parse_date("2025-12-03T12:00:00Z"), 251.2, 0, "", "</script><script>alert(1)</script>",
    )

    html = create_chart_babylon(position)

    assert position.request_url not in html
    assert "\\u003c/script\\u003e" in html


@pytest.mark.parametrize("angle", [math.nan, math.inf])
def test_given_nonfinite_camera_angle_when_exported_then_raises(angle: float) -> None:
    position = SolarPosition(parse_date("2025-12-03T12:00:00Z"), 251.2, 0, "", "")

    with pytest.raises(ValueError, match="angles"):
        create_chart_babylon(position, elevation=angle)


def test_given_html_output_when_cli_runs_then_saves_chart_and_nasa_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zodiaque_tropical_3d as renderer

    position = SolarPosition(
        parse_date("2025-12-03T12:00:00Z"), 251.2, 0, "NASA response", "https://example.test",
    )
    output = tmp_path / "sky.html"
    monkeypatch.setattr("sys.argv", [
        "zodiaque_tropical_3d.py", "--date", "2025-12-03T12:00:00Z",
        "--output", str(output), "--no-show",
    ])
    monkeypatch.setattr(renderer, "fetch_sun_position", lambda instant: position)

    result = renderer.main()

    assert result == 0
    assert output.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert output.with_suffix(".horizons.txt").read_text(encoding="utf-8") == (
        "Request URL: https://example.test\n\nNASA response"
    )


@pytest.mark.parametrize(
    ("longitude", "latitude", "expected"),
    [
        (0, 0, (1, 0, 0)),
        (90, 0, (0, 1, 0)),
        (180, 0, (-1, 0, 0)),
        (270, 0, (0, -1, 0)),
        (0, 90, (0, 0, 1)),
        (0, -90, (0, 0, -1)),
    ],
)
def test_given_cardinal_angles_when_projected_then_matches_ecliptic_frame(
    longitude: float, latitude: float, expected: tuple[float, float, float],
) -> None:
    assert ecliptic_to_cartesian(longitude, latitude) == pytest.approx(expected, abs=1e-14)


@pytest.mark.parametrize(
    ("longitude", "latitude"),
    [(math.nan, 0), (0, math.inf), (0, 91), (0, -91)],
)
def test_given_invalid_coordinates_when_projected_then_raises(
    longitude: float, latitude: float,
) -> None:
    with pytest.raises(ValueError):
        ecliptic_to_cartesian(longitude, latitude)


def test_given_nasa_sun_when_projected_then_preserves_longitude_latitude_and_unit_radius() -> None:
    x, y, z = ecliptic_to_cartesian(251.3261383, -0.0000390)

    assert math.sqrt(x * x + y * y + z * z) == pytest.approx(1, abs=1e-14)
    assert math.degrees(math.atan2(y, x)) % 360 == pytest.approx(251.3261383, abs=1e-10)
    assert math.degrees(math.asin(z)) == pytest.approx(-0.0000390, abs=1e-12)


@pytest.mark.parametrize("start", range(0, 360, 30))
def test_given_sector_when_mesh_created_then_covers_exact_30_degrees_on_unit_sphere(
    start: int,
) -> None:
    x, y, z = sphere_mesh(start, start + 30)
    middle = x.shape[0] // 2

    np.testing.assert_allclose(x * x + y * y + z * z, 1, atol=1e-14)
    assert (x[middle, 0], y[middle, 0], z[middle, 0]) == pytest.approx(
        ecliptic_to_cartesian(start, 0),
    )
    assert (x[middle, -1], y[middle, -1], z[middle, -1]) == pytest.approx(
        ecliptic_to_cartesian(start + 30, 0),
    )


def test_given_default_arguments_when_parsed_then_uses_december_3_at_noon_utc() -> None:
    assert create_parser().parse_args([]).date == parse_date("2026-12-03T12:00:00Z")


@pytest.mark.parametrize("angle", ["nan", "inf", "bad-angle"])
def test_given_invalid_view_angle_when_parsed_then_reports_cli_error(angle: str) -> None:
    with pytest.raises(SystemExit) as error:
        create_parser().parse_args(["--azimuth", angle])
    assert error.value.code == 2


def test_given_nasa_position_when_rendered_then_centers_earth_and_preserves_solar_direction(
    tmp_path: Path,
) -> None:
    position = SolarPosition(
        parse_date("2026-12-03T12:00:00Z"), 251.3261383, -0.0000390, "NASA response", "url",
    )

    figure, axes = create_chart_3d(position)
    try:
        sectors = [
            item for item in axes.collections if (item.get_gid() or "").startswith("sector-")
        ]
        assert len(sectors) == 12
        sun = next(line for line in axes.lines if line.get_gid() == "sun")
        coordinates = tuple(float(values[0]) for values in sun.get_data_3d())
        assert coordinates == pytest.approx(
            ecliptic_to_cartesian(position.longitude, position.latitude), abs=1e-14,
        )
        line = next(line for line in axes.lines if line.get_gid() == "solar-direction")
        assert tuple(float(values[0]) for values in line.get_data_3d()) == (0, 0, 0)
        assert tuple(float(values[-1]) for values in line.get_data_3d()) == coordinates
        output = tmp_path / "sky.png"
        figure.savefig(output)
        assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    finally:
        plt.close(figure)
