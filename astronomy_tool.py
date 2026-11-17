"""The agent's first capability: generate a real, dated astronomical scene."""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Annotated
from urllib.error import URLError

from agent_framework import tool
from azure.core.exceptions import AzureError

from artifact_storage import RenderManifest, RenderStore
from zodiaque_tropical import fetch_sun_position, parse_date, tropical_sign
from zodiaque_tropical_3d import chart_html, create_chart_data

LOGGER = logging.getLogger(__name__)


@dataclass
class RenderContext:
    scope: str
    renders: list[RenderManifest] = field(default_factory=list)


render_context: contextvars.ContextVar[RenderContext | None] = contextvars.ContextVar(
    "aistro_render_context",
    default=None,
)
_workers = asyncio.Semaphore(2)


def observation_instant(value: str) -> tuple[datetime, str]:
    if value == "now":
        return datetime.now(UTC).replace(microsecond=0), "Instant actuel en UTC."
    if value == "today":
        return datetime.combine(datetime.now(UTC).date(), time(12), UTC), "Date du jour, 12:00 UTC."
    if len(value) == 10:
        return datetime.combine(
            date.fromisoformat(value), time(12), UTC
        ), "Heure non fournie : 12:00 UTC."
    return parse_date(value), "Heure et fuseau fournis, normalises en UTC."


def render_observation(value: str, scope: str, store: RenderStore) -> RenderManifest:
    instant, assumption = observation_instant(value)
    position = fetch_sun_position(instant)
    data = create_chart_data(position)
    sign, degrees = tropical_sign(position.longitude)
    manifest: RenderManifest = {
        "version": 1,
        "id": uuid.uuid4().hex,
        "instant": instant.isoformat(),
        "createdAt": datetime.now(UTC).isoformat(),
        "sign": sign,
        "degrees": degrees,
        "longitude": position.longitude,
        "latitude": position.latitude,
        "solarConstellation": data["solarConstellation"],
        "timeAssumption": assumption,
        "dataSize": 0,
        "dataEtag": "",
    }
    store.save(
        scope,
        manifest,
        data,
        chart_html(data),
        f"Request URL: {position.request_url}\n\n{position.raw_response}",
    )
    return manifest


def _render(value: str, scope: str) -> RenderManifest:
    store = RenderStore()
    try:
        return render_observation(value, scope, store)
    finally:
        store.close()


@tool
async def generate_zodiac(
    observation_date: Annotated[
        str,
        "ISO date YYYY-MM-DD (12:00 UTC), timezone-aware ISO instant "
        "(e.g. 2026-12-03T13:00:00+01:00), 'today', or 'now'. "
        "Ask for the year if the user did not supply it.",
    ],
) -> str:
    """Generate an interactive Babylon.js zodiac scene using NASA/JPL and Astropy.

    Call once for each requested date. Never substitute a previously generated
    scene when the ephemeris service fails. The chat and Teams publish the saved
    artifact automatically; the model must not generate HTML, JavaScript or URLs.
    """
    context = render_context.get()
    try:
        if context is None:
            raise ValueError("This tool requires a Responses or Activity conversation.")
        async with _workers:
            manifest = await asyncio.to_thread(_render, observation_date, context.scope)
        context.renders.append(manifest)
        return json.dumps({"ok": True, **manifest}, ensure_ascii=False)
    except (ValueError, URLError, OSError, AzureError) as error:
        LOGGER.error("Astronomical generation failed (%s).", type(error).__name__)
        if isinstance(error, ValueError):
            message = str(error)
        elif isinstance(error, URLError):
            message = "NASA/JPL est inaccessible. Verifiez la connexion et les certificats TLS."
        else:
            message = (
                "Le stockage du rendu a echoue. Verifiez sa configuration et les droits Azure."
            )
        return json.dumps(
            {
                "ok": False,
                "error": message + " Aucun rendu de remplacement n'a ete cree.",
            }
        )
