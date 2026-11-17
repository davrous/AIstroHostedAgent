#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
"""Show a geocentric 3D tropical zodiac using NASA/JPL solar ephemerides.

Usage:
    .venv/bin/python zodiaque_tropical_3d.py
    .venv/bin/python zodiaque_tropical_3d.py --no-show
    .venv/bin/python zodiaque_tropical_3d.py --elevation 35 --azimuth -110
    .venv/bin/python zodiaque_tropical_3d.py --date 2026-12-03T12:00:00Z \
        --output zodiaque_2026.html --no-show

The default date is December 3, 2026 at 12:00 UTC. A live NASA/JPL Horizons
request is required; no approximate or hardcoded solar position is used.
The companion zodiaque_tropical.py supplies the shared ephemeris client.

This is an external view of a celestial sphere centered on Earth. Its sectors
are conventional 30-degree tropical longitudes of date, anchored to the March
equinox, NOT constellation boundaries. Latitude runs from -90 to +90 degrees.
The Sun is projected onto the sphere: distances and symbol sizes are not to
scale. The blue central globe is schematic, not a geographic Earth model.

An interactive Matplotlib window supports mouse rotation and zoom. PNG, SVG
and PDF exports are static. The raw NASA response is saved alongside the image.
An .html output instead exports an interactive Babylon.js celestial sphere.
Open it in a WebGL-capable browser; internet access loads Babylon.js from a CDN.
Solar coordinates and source URL are embedded, with no browser-side NASA request.
HTML also includes 13 zodiac constellation figures (including Ophiuchus) from
D3-Celestial's Hipparcos catalogue. Astropy transforms the fixed ICRS/J2000
directions into apparent geocentric true ecliptic coordinates at the given date.
Precession, nutation and aberration are included; stellar proper motion and
parallax are not modeled. Connecting lines are conventional figures, not IAU
boundaries. The HTML can show sampled IAU borders around the solar constellation,
using catalogue polygons interpolated in their original B1875 equatorial frame.
The catalogue's BSD license and provenance are embedded in the HTML.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import webbrowser
from pathlib import Path
from typing import TypedDict
from urllib.error import URLError

import matplotlib
import numpy as np
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d import Axes3D
from numpy.typing import NDArray

from zodiaque_tropical import (
    DEFAULT_DATE,
    SIGNS,
    SolarPosition,
    fetch_sun_position,
    parse_date,
    tropical_sign,
)

LOGGER = logging.getLogger(__name__)
BACKGROUND = "#09162b"
FOREGROUND = "#edf3fc"
GOLD = "#ffd366"
COLORS = (
    "#ff9292", "#ffc078", "#ffe082", "#bcdb83",
    "#6cd4ae", "#72dce4", "#89b7ff", "#ac9cff",
    "#d6a0ff", "#fa9fc6", "#c8b6a0", "#c0d4df",
)
CONSTELLATIONS = {
    "Ari": "Bélier", "Tau": "Taureau", "Gem": "Gémeaux", "Cnc": "Cancer",
    "Leo": "Lion", "Vir": "Vierge", "Lib": "Balance", "Sco": "Scorpion",
    "Oph": "Ophiuchus", "Sgr": "Sagittaire", "Cap": "Capricorne",
    "Aqr": "Verseau", "Psc": "Poissons",
}


class ConstellationStar(TypedDict):
    """Catalogue identifier, magnitude and apparent ecliptic direction."""

    hip: int
    magnitude: float
    longitude: float
    latitude: float


class ConstellationFigure(TypedDict):
    """Named stellar figure with paths referencing its Hipparcos stars."""

    id: str
    name: str
    stars: list[ConstellationStar]
    paths: list[list[int]]
    boundaries: list[list[tuple[float, float]]]
    longitude: float
    latitude: float


class ChartData(TypedDict):
    instant: str
    longitude: float
    latitude: float
    requestUrl: str
    signs: tuple[tuple[str, str], ...]
    colors: tuple[str, ...]
    elevation: float
    azimuth: float
    constellations: list[ConstellationFigure]
    solarConstellation: str
    catalogueSource: str
    catalogueLicense: str


def ecliptic_to_cartesian(longitude: float, latitude: float) -> tuple[float, float, float]:
    """Convert ecliptic degrees to a unit vector in a right-handed frame.

    Args:
        longitude: Longitude measured from the March equinox toward 90 degrees.
        latitude: Latitude relative to the ecliptic plane.

    Returns:
        Unit vector (x, y, z), with z toward the north ecliptic pole.

    Raises:
        ValueError: Nonfinite angle or latitude outside [-90, 90].
    """
    if not math.isfinite(longitude) or not math.isfinite(latitude) or abs(latitude) > 90:
        raise ValueError("Coordonnées écliptiques invalides.")
    lon, lat = math.radians(longitude), math.radians(latitude)
    return math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)


def sphere_mesh(
    start: float, stop: float, radius: float = 1,
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Sample a spherical longitude sector, including its two meridian boundaries."""
    longitude, latitude = np.meshgrid(
        np.deg2rad(np.linspace(start, stop, 13)),
        np.deg2rad(np.linspace(-90, 90, 37)),
    )
    return (
        radius * np.cos(latitude) * np.cos(longitude),
        radius * np.cos(latitude) * np.sin(longitude),
        radius * np.sin(latitude),
    )


def create_chart_3d(
    position: SolarPosition, *, elevation: float = 28, azimuth: float = -65,
) -> tuple[Figure, Axes3D]:
    """Draw Earth, all tropical sectors, and the exact apparent solar direction."""
    from matplotlib import pyplot as plt

    figure = plt.figure(figsize=(16, 10), facecolor=BACKGROUND)
    axes = figure.add_subplot(121, projection="3d", computed_zorder=False)
    axes.set_position((0.015, 0.18, 0.65, 0.68))
    axes.set_facecolor(BACKGROUND)
    axes.set_proj_type("ortho")
    axes.set_box_aspect((1, 1, 1), zoom=1.45)
    axes.set_xlim(-1.35, 1.35)
    axes.set_ylim(-1.35, 1.35)
    axes.set_zlim(-1.35, 1.35)
    axes.view_init(elev=elevation, azim=azimuth)
    axes.set_axis_off()

    for index, ((name, _), color) in enumerate(zip(SIGNS, COLORS, strict=True)):
        start = index * 30
        x, y, z = sphere_mesh(start, start + 30)
        surface = axes.plot_surface(
            x, y, z, color=color, alpha=0.09, linewidth=0, shade=False, zorder=1,
        )
        surface.set_gid(f"sector-{index}")
        latitude = np.deg2rad(np.linspace(-90, 90, 100))
        longitude = math.radians(start)
        axes.plot(
            np.cos(latitude) * math.cos(longitude),
            np.cos(latitude) * math.sin(longitude),
            np.sin(latitude), color=color, alpha=0.5, linewidth=0.8, zorder=2,
        )
        arc = np.deg2rad(np.linspace(start, start + 30, 40))
        axes.plot(np.cos(arc), np.sin(arc), np.zeros_like(arc), color=color, linewidth=4)
        label = ecliptic_to_cartesian(start + 15, 18)
        axes.text(
            *[1.07 * coordinate for coordinate in label], str(index + 1),
            color=color, fontsize=12, ha="center", va="center",
        )

    for latitude_degrees in (-60, -30, 30, 60):
        arc = np.deg2rad(np.linspace(0, 360, 181))
        lat = math.radians(latitude_degrees)
        axes.plot(
            math.cos(lat) * np.cos(arc), math.cos(lat) * np.sin(arc),
            np.full_like(arc, math.sin(lat)), color=FOREGROUND, alpha=0.15, linewidth=0.6,
        )

    earth = axes.plot_surface(
        *sphere_mesh(0, 360, radius=0.13),
        color="#238bc2", alpha=1, linewidth=0.25, edgecolor="#71c9e2", zorder=4,
    )
    earth.set_gid("earth")
    axes.text(0, 0, 0.21, "TERRE", color=FOREGROUND, fontsize=11, ha="center")
    axes.quiver(0, 0, 0, 1.25, 0, 0, color=FOREGROUND, linewidth=1, arrow_length_ratio=0.08)
    axes.text(1.28, 0, 0, "0°\nÉquinoxe de mars", color=FOREGROUND, fontsize=9)
    axes.text(0, 0, 1.14, "Pôle nord\nécliptique", color=FOREGROUND, ha="center", fontsize=10)

    sun_x, sun_y, sun_z = ecliptic_to_cartesian(position.longitude, position.latitude)
    sightline, = axes.plot(
        [0, sun_x], [0, sun_y], [0, sun_z],
        color=GOLD, linestyle="--", linewidth=1.7, zorder=5,
    )
    sightline.set_gid("solar-direction")
    sun, = axes.plot(
        [sun_x], [sun_y], [sun_z], marker="o", markersize=16,
        color=GOLD, markeredgecolor="white", linestyle="none", zorder=6,
    )
    sun.set_gid("sun")
    axes.text(
        sun_x * 1.16, sun_y * 1.16, sun_z - 0.12, "SOLEIL",
        color=GOLD, fontsize=12, ha="center", zorder=7,
    )

    name, degrees = tropical_sign(position.longitude)
    stamp = position.instant.strftime("%d/%m/%Y à %H:%M:%S UTC")
    figure.suptitle(
        "ZODIAQUE TROPICAL — VUE 3D CENTRÉE SUR LA TERRE",
        color=FOREGROUND, fontsize=20, y=0.97,
    )
    figure.text(0.5, 0.92, stamp, color=FOREGROUND, fontsize=14, ha="center")
    figure.text(
        0.675, 0.84, f"SOLEIL : {name}\n"
        f"λ = {position.longitude:.7f}°\nβ = {position.latitude:.7f}°\n"
        f"{degrees:.4f}° dans le signe",
        color=GOLD, fontsize=13, linespacing=1.5,
    )
    figure.text(
        0.675, 0.69, "SECTEURS TROPICAUX • DATES USUELLES",
        color=FOREGROUND, fontsize=11,
    )
    for index, ((sign, dates), color) in enumerate(zip(SIGNS, COLORS, strict=True)):
        figure.text(
            0.675, 0.655 - index * 0.035,
            f"{index + 1:2}. {sign} [{index * 30}°–{(index + 1) * 30}°]",
            color=color, fontsize=10,
        )
        figure.text(0.845, 0.655 - index * 0.035, dates, color=FOREGROUND, fontsize=9)
    figure.text(
        0.5, 0.16,
        "Les signes sont des secteurs conventionnels de 30°, "
        "pas les constellations astronomiques.\n"
        "Les arcs colorés suivent l'écliptique (β = 0°) ; "
        "les méridiens délimitent les secteurs sur toute la sphère.",
        color=FOREGROUND, fontsize=11, ha="center", linespacing=1.6,
    )
    figure.text(
        0.5, 0.095,
        "Vue extérieure d'une sphère céleste géocentrique. Soleil projeté sur la sphère ; "
        "tailles et distances non à l'échelle.\n"
        "Dates indicatives : les transitions varient selon l'année et le fuseau. "
        "Rotation et zoom dans la fenêtre interactive.",
        color="#adbdce", fontsize=10, ha="center", linespacing=1.6,
    )
    figure.text(
        0.5, 0.03,
        "Source solaire : NASA/JPL Horizons • quantité 31 • coordonnées apparentes "
        "écliptiques de date • centre de la Terre\nhttps://ssd.jpl.nasa.gov/horizons/",
        color="#72dce4", fontsize=10, ha="center",
    )
    return figure, axes


def finite_angle(value: str) -> float:
    """Validate a finite camera angle from the command line."""
    try:
        angle = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("L'angle doit être numérique.") from error
    if not math.isfinite(angle):
        raise argparse.ArgumentTypeError("L'angle doit être fini.")
    return angle


def constellation_figures(position: SolarPosition) -> tuple[list[ConstellationFigure], str, str]:
    """Transform the bundled stellar figures and identify the Sun's IAU region.

    Returns:
        Figures in apparent ecliptic-of-date coordinates, source URL, and the
        French name of the IAU constellation containing the solar direction.

    Raises:
        ValueError: Incomplete catalogue or a path without a matching star.
    """
    import astropy.units as u
    from astropy.coordinates import FK5, GeocentricTrueEcliptic, SkyCoord
    from astropy.time import Time
    from astropy.utils import iers

    catalogue = json.loads(
        Path(__file__).with_name("zodiac_constellations.json").read_text(encoding="utf-8"),
    )
    raw_stars = catalogue["stars"]
    raw_figures = {figure["id"]: figure for figure in catalogue["figures"]}
    raw_boundaries = {boundary["id"]: boundary for boundary in catalogue["boundaries"]}
    if (
        set(raw_figures) != set(CONSTELLATIONS)
        or set(raw_boundaries) != set(CONSTELLATIONS) or not raw_stars
    ):
        raise ValueError("Le catalogue doit contenir les 13 constellations du zodiaque.")
    equatorial = np.array([star["geometry"]["coordinates"] for star in raw_stars], dtype=float)
    for right_ascension, declination in equatorial:
        ecliptic_to_cartesian(float(right_ascension), float(declination))
    with iers.conf.set_temp("auto_download", False):
        instant = Time(position.instant)
        frame = GeocentricTrueEcliptic(equinox=instant, obstime=instant)
        transformed = SkyCoord(
            ra=equatorial[:, 0] * u.deg, dec=equatorial[:, 1] * u.deg, frame="icrs",
        ).transform_to(frame)
        solar_region = SkyCoord(
            lon=position.longitude * u.deg, lat=position.latitude * u.deg, frame=frame,
        ).get_constellation(short_name=True)
        boundaries: dict[str, list[list[tuple[float, float]]]] = {}
        for identifier, raw_boundary in raw_boundaries.items():
            boundaries[identifier] = []
            for ring in raw_boundary["geometry"]["coordinates"]:
                if len(ring) < 4 or ring[0] != ring[-1]:
                    raise ValueError(f"Frontière non fermée pour {identifier}.")
                equatorial_border = SkyCoord(
                    ring, unit=u.deg, frame=FK5(equinox="J2000"),
                ).transform_to(FK5(equinox=Time("B1875")))
                samples = []
                for index in range(len(ring) - 1):
                    ra = float(equatorial_border.ra.degree[index])
                    dec = float(equatorial_border.dec.degree[index])
                    delta_ra = (
                        float(equatorial_border.ra.degree[index + 1]) - ra + 180
                    ) % 360 - 180
                    delta_dec = float(equatorial_border.dec.degree[index + 1]) - dec
                    steps = max(1, math.ceil(max(abs(delta_ra), abs(delta_dec)) * 2))
                    # IAU edges follow B1875 meridians/parallels, not great circles.
                    samples.extend(
                        (ra + delta_ra * step / steps, dec + delta_dec * step / steps)
                        for step in range(steps)
                    )
                samples.append(samples[0])
                ecliptic_border = SkyCoord(
                    samples, unit=u.deg, frame=FK5(equinox=Time("B1875")),
                ).transform_to(frame)
                boundaries[identifier].append([
                    (float(lon), float(lat))
                    for lon, lat in zip(
                        ecliptic_border.lon.degree, ecliptic_border.lat.degree, strict=True,
                    )
                ])
    stars: dict[tuple[float, float], ConstellationStar] = {}
    for index, raw_star in enumerate(raw_stars):
        magnitude = float(raw_star["properties"]["mag"])
        if not math.isfinite(magnitude):
            raise ValueError("Magnitude stellaire non finie dans le catalogue.")
        stars[tuple(equatorial[index])] = {
            "hip": int(raw_star["id"]), "magnitude": magnitude,
            "longitude": float(transformed.lon.degree[index]),
            "latitude": float(transformed.lat.degree[index]),
        }
    figures: list[ConstellationFigure] = []
    for identifier, name in CONSTELLATIONS.items():
        paths: list[list[int]] = []
        figure_stars: dict[int, ConstellationStar] = {}
        for path in raw_figures[identifier]["geometry"]["coordinates"]:
            if len(path) < 2:
                raise ValueError(f"Tracé incomplet pour {identifier}.")
            indices = []
            for point in path:
                key = tuple(point)
                if key not in stars:
                    raise ValueError(f"Étoile absente du catalogue : {identifier}, {point}.")
                star = stars[key]
                figure_stars[star["hip"]] = star
                indices.append(star["hip"])
            paths.append(indices)
        if not figure_stars:
            raise ValueError(f"Constellation sans étoiles : {identifier}.")
        center = np.mean([
            ecliptic_to_cartesian(star["longitude"], star["latitude"])
            for star in figure_stars.values()
        ], axis=0)
        figures.append({
            "id": identifier, "name": name, "stars": list(figure_stars.values()), "paths": paths,
            "boundaries": boundaries[identifier],
            "longitude": math.degrees(math.atan2(center[1], center[0])) % 360,
            "latitude": math.degrees(math.atan2(center[2], math.hypot(center[0], center[1]))),
        })
    return (
        figures, str(catalogue["source"]),
        CONSTELLATIONS.get(str(solar_region), str(solar_region)),
    )


def create_chart_data(
    position: SolarPosition, *, elevation: float = 28, azimuth: float = -65,
) -> ChartData:
    """Build the same dated scene data for HTML, web chat and Teams."""
    ecliptic_to_cartesian(position.longitude, position.latitude)
    if not math.isfinite(elevation) or not math.isfinite(azimuth):
        raise ValueError("Les angles de vue doivent être finis.")
    figures, catalogue_source, solar_constellation = constellation_figures(position)
    return {
        "instant": position.instant.isoformat(),
        "longitude": position.longitude,
        "latitude": position.latitude,
        "requestUrl": position.request_url,
        "signs": SIGNS,
        "colors": COLORS,
        "elevation": elevation,
        "azimuth": azimuth,
        "constellations": figures,
        "solarConstellation": solar_constellation,
        "catalogueSource": catalogue_source,
        "catalogueLicense": Path(__file__).with_name(
            "zodiac_constellations.LICENSE.txt",
        ).read_text(encoding="utf-8"),
    }


def chart_html(data: ChartData) -> str:
    """Embed scene data without allowing JSON to terminate its script element."""
    payload = json.dumps(
        data, ensure_ascii=True, allow_nan=False,
    ).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    template = Path(__file__).with_name("zodiaque_tropical_babylon.template.html")
    return template.read_text(encoding="utf-8").replace("__ZODIAC_DATA__", payload)


def create_chart_babylon(
    position: SolarPosition, *, elevation: float = 28, azimuth: float = -65,
) -> str:
    """Export a standalone interactive snapshot of the requested instant."""
    return chart_html(create_chart_data(position, elevation=elevation, azimuth=azimuth))


def create_parser() -> argparse.ArgumentParser:
    """Build the 3D renderer CLI with a timezone-aware observation instant."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=parse_date, default=DEFAULT_DATE)
    parser.add_argument(
        "--output", type=Path, default=Path("zodiaque_tropical_3d.png"),
        help="Sortie .png, .svg, .pdf (Matplotlib) ou .html (Babylon.js).",
    )
    parser.add_argument("--no-show", action="store_true", help="Exporter sans fenêtre interactive.")
    parser.add_argument("--elevation", type=finite_angle, default=28, help="Élévation de vue en °.")
    parser.add_argument("--azimuth", type=finite_angle, default=-65, help="Azimut de vue en °.")
    return parser


def main() -> int:
    """Fetch NASA data, persist the chart and provenance, and open the 3D view."""
    parser = create_parser()
    args = parser.parse_args()
    if args.output.suffix.lower() not in {".png", ".svg", ".pdf", ".html"}:
        parser.error("--output exige une extension .png, .svg, .pdf ou .html")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if args.no_show:
        matplotlib.use("Agg")
    try:
        position = fetch_sun_position(args.date)
        LOGGER.info(
            "NASA/JPL : longitude %.7f°, latitude %.7f°.",
            position.longitude, position.latitude,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        source_path = args.output.with_suffix(".horizons.txt")
        source_path.write_text(
            f"Request URL: {position.request_url}\n\n{position.raw_response}", encoding="utf-8",
        )
        if args.output.suffix.lower() == ".html":
            args.output.write_text(
                create_chart_babylon(position, elevation=args.elevation, azimuth=args.azimuth),
                encoding="utf-8",
            )
            if not args.no_show and not webbrowser.open(args.output.resolve().as_uri()):
                LOGGER.warning("Ouverture automatique impossible : ouvrez le fichier HTML.")
        else:
            figure, _ = create_chart_3d(
                position, elevation=args.elevation, azimuth=args.azimuth,
            )
            figure.savefig(args.output, dpi=160, facecolor=BACKGROUND)
            from matplotlib import pyplot as plt

            if not args.no_show:
                plt.show()
            plt.close(figure)
        LOGGER.info("Vue 3D : %s", args.output.resolve())
        LOGGER.info("Données NASA : %s", source_path.resolve())
    except (URLError, OSError, ValueError, OverflowError) as error:
        LOGGER.error("Impossible de produire la vue 3D : %s", error)
        return 1
    except KeyboardInterrupt:
        LOGGER.error("Interrompu.")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
