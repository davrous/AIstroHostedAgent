"""Teams HTML Widgets: deterministic bootstrap and conversation-authorized reads."""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from azure.core.exceptions import AzureError
from microsoft_agents.hosting.core import TurnContext

from artifact_storage import RenderStore

LOGGER = logging.getLogger(__name__)
INVOKE_NAME = "htmlwidget/calltool"
_TEMPLATE = Path(__file__).parent / "webchat/client/widget/widget.html"


@dataclass(frozen=True)
class WidgetConfig:
    assets: str
    origin: str
    storage_origin: str


def configuration() -> WidgetConfig | None:
    assets = os.environ.get("TEAMS_WIDGET_ASSET_BASE_URL", "").strip().rstrip("/")
    if not assets:
        return None
    parsed = urlsplit(assets)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.hostname in {"localhost", "127.0.0.1"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.port not in {None, 443}
    ):
        raise ValueError("TEAMS_WIDGET_ASSET_BASE_URL must be a public HTTPS asset directory.")
    account = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME", "")
    if os.environ.get("ARTIFACT_STORAGE") != "blob" or not re.fullmatch(r"[a-z0-9]{3,24}", account):
        raise ValueError("Teams widgets require private Blob storage and a valid account name.")
    return WidgetConfig(
        assets, f"https://{parsed.netloc}", f"https://{account}.blob.core.windows.net"
    )


def conversation_binding(context: TurnContext) -> str:
    activity = context.activity
    channel = getattr(activity.channel_id, "channel", activity.channel_id)
    data = activity.channel_data or {}
    tenant_data = data.get("tenant", {}) if isinstance(data, dict) else {}
    if not isinstance(tenant_data, dict):
        raise ValueError("Invalid Teams tenant context.")
    tenant = tenant_data.get("id") or getattr(activity.conversation, "tenant_id", None)
    bot = getattr(activity.recipient, "id", None)
    conversation = getattr(activity.conversation, "id", None)
    if (
        getattr(context.identity, "is_authenticated", False) is not True
        or channel != "msteams"
        or not all(
            isinstance(item, str) and 0 < len(item) <= 2048 for item in (tenant, bot, conversation)
        )
    ):
        raise ValueError("An authenticated Teams tenant, bot and conversation are required.")
    return hashlib.sha256(json.dumps([tenant, bot, conversation]).encode()).hexdigest()


def widget_markdown(render_id: str, config: WidgetConfig) -> str:
    if not re.fullmatch(r"[a-f0-9]{32}", render_id):
        raise ValueError("Invalid widget render identifier.")
    bootstrap = (
        json.dumps(
            {
                "id": render_id,
                "storageOrigin": config.storage_origin,
            }
        )
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    document = _TEMPLATE.read_text(encoding="utf-8").replace("__CONFIG__", bootstrap)
    document = document.replace("__ASSET_BASE__", html.escape(config.assets, quote=True))
    payload = {
        "type": "widget/mcp-ui",
        "name": "AIstro · zodiaque 3D",
        "description": "Vue astronomique a la date demandee, calculee avec NASA/JPL.",
        "domain": config.origin,
        "correlationId": render_id,
        "html": document,
        "securityPolicy": {
            "connectDomains": [config.storage_origin],
            "resourceDomains": [config.origin],
            "frameDomains": [],
            "baseUriDomains": [],
        },
    }
    return "```html-widget\n" + json.dumps(payload) + "\n```"


def call_result(text: str, data: dict | None = None, *, error: bool = False) -> dict:
    return {
        "responseType": "htmlwidget/calltoolresult",
        "callToolResult": {
            "content": [{"type": "text", "text": text}],
            "structuredContent": data if data is not None else {},
            "isError": error,
        },
    }


def _snapshot(scope: str, render_id: str) -> dict:
    store = RenderStore()
    try:
        return store.signed_snapshot(scope, render_id)
    finally:
        store.close()


async def call_tool(context: TurnContext, allowed_ids: list[str]) -> dict:
    try:
        if configuration() is None:
            raise ValueError("Les widgets Teams ne sont pas configures sur cet agent.")
        scope = conversation_binding(context)
        value = context.activity.value
        name = value.get("name") if isinstance(value, dict) else None
        arguments = value.get("arguments") if isinstance(value, dict) else None
        render_id = arguments.get("id") if isinstance(arguments, dict) else None
        if name not in {"zodiac_widget_ping", "load_zodiac_snapshot"}:
            raise ValueError("Ce widget autorise uniquement la lecture du rendu astronomique.")
        if not isinstance(render_id, str) or not re.fullmatch(r"[a-f0-9]{32}", render_id):
            raise ValueError("Identifiant de rendu invalide.")
        if render_id not in allowed_ids:
            raise ValueError("Ce widget n'appartient pas a cette conversation ou a ete efface.")
        if name == "zodiac_widget_ping":
            return call_result("Connexion etablie.", {"version": 1, "id": render_id})
        async with asyncio.timeout(12):
            data = await asyncio.to_thread(_snapshot, scope, render_id)
        return call_result("Rendu disponible.", data)
    except ValueError as error:
        LOGGER.warning("Widget request rejected: %s", error)
        return call_result(str(error), error=True)
    except (AzureError, OSError, TimeoutError) as error:
        LOGGER.error("Widget storage request failed (%s).", type(error).__name__)
        return call_result(
            "Chargement impossible. Reessayez apres le reveil de l'agent.", error=True
        )
