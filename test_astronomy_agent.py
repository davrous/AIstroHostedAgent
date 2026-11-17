"""Focused tests for dated artifacts and the Teams read-only widget contract."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.error import URLError

import pytest
from microsoft_agents.activity import Activity, ChannelAccount, ConversationAccount

import astronomy_tool
import teams_widgets
from activity_bridge import Conversation, ConversationStore, Delivery
from astronomy_tool import RenderContext, generate_zodiac, observation_instant, render_context
from zodiaque_tropical import SolarPosition


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2028-02-29", datetime(2028, 2, 29, 12, tzinfo=UTC)),
        ("2027-06-22T00:30:00+09:00", datetime(2027, 6, 21, 15, 30, tzinfo=UTC)),
    ],
)
def test_observation_dates_preserve_noon_default_and_timezone(value, expected):
    assert observation_instant(value)[0] == expected


@pytest.mark.parametrize("value", ["3 decembre", "2026-02-30", "2026-12-03T12:00:00"])
def test_ambiguous_or_invalid_dates_are_not_replaced_with_december_3(value):
    with pytest.raises(ValueError):
        observation_instant(value)


@pytest.mark.parametrize(
    ("value", "longitude"),
    [("2026-12-03", 251.3261383), ("2027-06-21T18:00:00Z", 90.1518059)],
)
def test_tool_publishes_exact_requested_date_in_json_and_html(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    value: str,
    longitude: float,
):
    monkeypatch.setenv("AISTRO_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("ARTIFACT_STORAGE", "local")
    expected, _ = observation_instant(value)
    requested = []

    def fetch(instant):
        requested.append(instant)
        return SolarPosition(instant, longitude, 0, "NASA fixture", "https://example.test")

    monkeypatch.setattr(astronomy_tool, "fetch_sun_position", fetch)
    context = RenderContext("a" * 64)
    token = render_context.set(context)
    try:
        contents = asyncio.run(generate_zodiac.invoke(arguments={"observation_date": value}))
        result = json.loads(contents[0].text)
    finally:
        render_context.reset(token)

    assert requested == [expected]
    assert result["ok"] is True
    assert len(context.renders) == 1
    directory = tmp_path / "artifacts/zodiac" / context.scope / result["id"]
    data = json.loads((directory / "data.json").read_text())
    html = (directory / "chart.html").read_text()
    embedded = json.loads(
        html.split('<script id="zodiac-data" type="application/json">')[1].split("</script>")[0],
    )
    assert data == embedded
    assert data["instant"] == expected.isoformat()
    assert data["longitude"] == longitude
    assert (directory / "source.txt").read_text().endswith("NASA fixture")


def test_nasa_failure_does_not_publish_a_successful_or_stale_artifact(tmp_path, monkeypatch):
    monkeypatch.setenv("AISTRO_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("ARTIFACT_STORAGE", "local")

    def unavailable(_instant):
        raise URLError("NASA unavailable")

    monkeypatch.setattr(astronomy_tool, "fetch_sun_position", unavailable)
    context = RenderContext("a" * 64)
    token = render_context.set(context)
    try:
        contents = asyncio.run(
            generate_zodiac.invoke(arguments={"observation_date": "2028-02-29"}),
        )
        result = json.loads(contents[0].text)
    finally:
        render_context.reset(token)
    assert result["ok"] is False
    assert context.renders == []
    assert not (tmp_path / "artifacts").exists()


def teams_context(conversation="thread-one", *, authenticated=True, name="zodiac_widget_ping"):
    return SimpleNamespace(
        identity=SimpleNamespace(is_authenticated=authenticated),
        activity=SimpleNamespace(
            channel_id="msteams",
            channel_data={"tenant": {"id": "test-tenant"}},
            recipient=SimpleNamespace(id="28:test-bot"),
            conversation=SimpleNamespace(id=conversation),
            value={"name": name, "arguments": {"id": "b" * 32}},
        ),
    )


def configure_widget(monkeypatch):
    monkeypatch.setenv("ARTIFACT_STORAGE", "blob")
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_NAME", "teststorage")
    monkeypatch.setenv("TEAMS_WIDGET_ASSET_BASE_URL", "https://assets.example.test/teams-widget/v1")


def test_widget_context_survives_restart_but_not_clear_or_another_thread(tmp_path, monkeypatch):
    monkeypatch.setenv("AISTRO_STATE_DIR", str(tmp_path))
    configure_widget(monkeypatch)
    context = teams_context()
    scope = teams_widgets.conversation_binding(context)
    store = ConversationStore()
    store.write(scope, Conversation([{"role": "user", "text": "2028-02-29"}], ["b" * 32]))
    reopened = ConversationStore()
    allowed = reopened.read(scope).widgets
    result = asyncio.run(teams_widgets.call_tool(context, allowed))
    assert result["callToolResult"]["isError"] is False
    other_scope = teams_widgets.conversation_binding(teams_context("thread-two"))
    assert reopened.read(other_scope).widgets == []
    rejected = asyncio.run(teams_widgets.call_tool(teams_context("thread-two"), []))
    assert rejected["callToolResult"]["isError"] is True
    reopened.write(scope, Conversation([], []))
    cleared = asyncio.run(teams_widgets.call_tool(context, reopened.read(scope).widgets))
    assert cleared["callToolResult"]["isError"] is True


@pytest.mark.parametrize(
    "context",
    [teams_context(authenticated=False), teams_context(name="execute_python")],
)
def test_widget_rejects_unauthenticated_or_mutating_invokes(monkeypatch, context):
    configure_widget(monkeypatch)
    result = asyncio.run(teams_widgets.call_tool(context, ["b" * 32]))
    assert result["responseType"] == "htmlwidget/calltoolresult"
    assert result["callToolResult"]["isError"] is True
    assert result["callToolResult"]["structuredContent"] == {}


def test_widget_bootstrap_has_no_private_link_and_uses_standalone_assets(monkeypatch):
    configure_widget(monkeypatch)
    markdown = teams_widgets.widget_markdown("b" * 32, teams_widgets.configuration())
    payload = json.loads(markdown.split("\n", 1)[1].rsplit("\n", 1)[0])
    assert payload["type"] == "widget/mcp-ui"
    assert "__CONFIG__" not in payload["html"]
    assert "widget.js" in payload["html"]
    assert "sig=" not in payload["html"]
    assert payload["securityPolicy"]["connectDomains"] == [
        "https://teststorage.blob.core.windows.net",
    ]


def test_detached_delivery_uses_a_fresh_sdk_context_and_keeps_the_conversation():
    fresh_send = AsyncMock()

    async def continue_conversation(**kwargs):
        assert kwargs["continuation_activity"].id is None
        assert kwargs["continuation_activity"].conversation.id == "thread-one"
        await kwargs["callback"](SimpleNamespace(send_activity=fresh_send))

    context = SimpleNamespace(
        activity=Activity(
            type="message",
            id="user-message",
            channel_id="msteams",
            service_url="https://example.test",
            recipient=ChannelAccount(id="28:test-bot"),
            conversation=ConversationAccount(id="thread-one"),
        ),
        identity=SimpleNamespace(get_token_audience=lambda: "test-audience"),
        adapter=SimpleNamespace(continue_conversation_with_claims=continue_conversation),
        send_activity=AsyncMock(),
    )
    delivery = Delivery(context)
    delivery.detached = True
    asyncio.run(
        delivery.send(Activity(type="message", text="Widget", text_format="extendedmarkdown"))
    )
    context.send_activity.assert_not_called()
    sent = fresh_send.call_args.args[0]
    assert sent.conversation.id == "thread-one"
    assert sent.text_format == "extendedmarkdown"


def test_a_completed_teams_turn_does_not_send_a_late_working_message():
    async def verify():
        send = AsyncMock()
        context = SimpleNamespace(
            activity=Activity(
                type="message",
                channel_id="msteams",
                service_url="https://example.test",
                recipient=ChannelAccount(id="28:test-bot"),
                conversation=ConversationAccount(id="thread-one"),
            ),
            send_activity=send,
        )
        delivery = Delivery(context)
        task = asyncio.create_task(asyncio.sleep(0))
        await task
        await delivery.detach(task)
        send.assert_not_called()
        assert delivery.detached is False

    asyncio.run(verify())
