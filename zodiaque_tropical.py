"""Solar ephemerides shared by the command-line charts and the agent."""

from __future__ import annotations

import argparse
import csv
import io
import math
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from urllib.request import urlopen

import truststore

DEFAULT_DATE = datetime(2026, 12, 3, 12, tzinfo=UTC)
SIGNS = (
    ("Bélier", "21 mars – 20 avril"),
    ("Taureau", "21 avril – 20 mai"),
    ("Gémeaux", "21 mai – 21 juin"),
    ("Cancer", "22 juin – 22 juillet"),
    ("Lion", "23 juillet – 22 août"),
    ("Vierge", "23 août – 22 septembre"),
    ("Balance", "23 septembre – 22 octobre"),
    ("Scorpion", "23 octobre – 22 novembre"),
    ("Sagittaire", "23 novembre – 21 décembre"),
    ("Capricorne", "22 décembre – 20 janvier"),
    ("Verseau", "21 janvier – 19 février"),
    ("Poissons", "20 février – 20 mars"),
)


@dataclass(frozen=True)
class SolarPosition:
    instant: datetime
    longitude: float
    latitude: float
    raw_response: str
    request_url: str


def parse_date(value: str) -> datetime:
    """Parse a timezone-aware ISO instant at whole-second precision."""
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(
            "Utilisez une date ISO avec heure et fuseau, par exemple 2026-12-03T12:00:00Z."
        ) from error
    if "T" not in value or instant.tzinfo is None or instant.microsecond:
        raise ValueError("L'heure et le fuseau sont obligatoires, sans fractions de seconde.")
    return instant.astimezone(UTC)


def build_request_url(instant: datetime) -> str:
    if instant.tzinfo is None or instant.microsecond:
        raise ValueError("Un instant avec fuseau et precision a la seconde est requis.")
    instant = instant.astimezone(UTC)
    parameters = {
        "format": "text",
        "COMMAND": "'10'",
        "EPHEM_TYPE": "'OBSERVER'",
        "CENTER": "'500@399'",
        "START_TIME": f"'{instant:%Y-%m-%d %H:%M:%S}'",
        "STOP_TIME": f"'{instant + timedelta(minutes=1):%Y-%m-%d %H:%M:%S}'",
        "STEP_SIZE": "'1 m'",
        "QUANTITIES": "'31'",
        "CSV_FORMAT": "'YES'",
        "TIME_DIGITS": "'SECONDS'",
        "CAL_FORMAT": "'CAL'",
    }
    return "https://ssd.jpl.nasa.gov/api/horizons.api?" + urlencode(parameters)


def parse_horizons_response(response: str) -> tuple[float, float]:
    if "ObsEcLon" not in response or "$$SOE" not in response or "$$EOE" not in response:
        raise ValueError("Reponse NASA/JPL sans ephemerides solaires valides.")
    rows = response.split("$$SOE", 1)[1].split("$$EOE", 1)[0].strip()
    if not rows:
        raise ValueError("La NASA/JPL n'a retourne aucune position.")
    try:
        row = next(csv.reader(io.StringIO(rows), skipinitialspace=True))
        longitude, latitude = float(row[3]), float(row[4])
    except (ValueError, IndexError, StopIteration) as error:
        raise ValueError("Coordonnees solaires NASA/JPL invalides.") from error
    if not (
        math.isfinite(longitude)
        and math.isfinite(latitude)
        and 0 <= longitude < 360
        and -90 <= latitude <= 90
    ):
        raise ValueError("Coordonnees solaires NASA/JPL hors limites.")
    return longitude, latitude


def fetch_sun_position(instant: datetime) -> SolarPosition:
    url = build_request_url(instant)
    with urlopen(
        url, timeout=30, context=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("La reponse NASA/JPL depasse la taille autorisee.")
    text = raw.decode("utf-8")
    longitude, latitude = parse_horizons_response(text)
    return SolarPosition(instant.astimezone(UTC), longitude, latitude, text, url)


def tropical_sign(longitude: float) -> tuple[str, float]:
    if not math.isfinite(longitude):
        raise ValueError("Longitude non finie.")
    longitude %= 360
    return SIGNS[int(longitude // 30)][0], longitude % 30


def create_chart(position: SolarPosition):
    """Keep the original two-dimensional chart interface available."""
    from matplotlib import pyplot as plt
    from matplotlib.patches import Rectangle

    figure, axes = plt.subplots(figsize=(16, 8))
    for index, (name, _) in enumerate(SIGNS):
        axes.add_patch(
            Rectangle(
                (index * 30, -90),
                30,
                180,
                facecolor=plt.get_cmap("tab20")(index),
                alpha=0.25,
            )
        )
        axes.text(index * 30 + 15, 75, name, ha="center")
    axes.scatter([position.longitude], [position.latitude], color="gold", edgecolor="black")
    axes.set(
        xlim=(0, 360),
        ylim=(-90, 90),
        xlabel="Longitude ecliptique (°)",
        ylabel="Latitude ecliptique (°)",
        title=position.instant.isoformat(),
    )
    return figure, axes


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=parse_date, default=DEFAULT_DATE)
    return parser
