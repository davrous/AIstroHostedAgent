"""Native Activity protocol, durable Teams history, and standalone HTML Widgets."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass

from agent_framework import Agent, Content, Message
from azure.ai.agentserver.activity import ActivityAgentServerHost
from microsoft_agents.activity import Activity
from microsoft_agents.hosting.core import TurnContext, TurnState

import teams_widgets as widgets
from artifact_storage import state_directory
from astronomy_tool import RenderContext, render_context
from responses_host import AstronomyResponsesHost

LOGGER = logging.getLogger(__name__)
_locks: dict[str, asyncio.Lock] = {}
_tasks: set[asyncio.Task] = set()


@dataclass
class Conversation:
    history: list[dict[str, str]]
    widgets: list[str]


class ConversationStore:
    def __init__(self) -> None:
        directory = state_directory()
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "teams.sqlite3"
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS conversations "
                "(scope TEXT PRIMARY KEY, history TEXT NOT NULL, widgets TEXT NOT NULL)",
            )

    def read(self, scope: str) -> Conversation:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT history, widgets FROM conversations WHERE scope=?",
                (scope,),
            ).fetchone()
        return Conversation(json.loads(row[0]), json.loads(row[1])) if row else Conversation([], [])

    def write(self, scope: str, value: Conversation) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO conversations VALUES (?, ?, ?) ON CONFLICT(scope) "
                "DO UPDATE SET history=excluded.history, widgets=excluded.widgets",
                (scope, json.dumps(value.history[-40:]), json.dumps(value.widgets[-32:])),
            )


class Delivery:
    def __init__(self, context: TurnContext) -> None:
        self.context = context
        self.detached = False
        self.lock = asyncio.Lock()
        self.reference = context.activity.get_conversation_reference()

    async def send(self, activity: Activity) -> None:
        async with self.lock:
            if not self.detached:
                await self.context.send_activity(activity)
                return
            continuation = self.reference.get_continuation_activity()
            continuation.id = None

            async def deliver(context: TurnContext) -> None:
                activity.apply_conversation_reference(self.reference)
                activity.id = None
                await context.send_activity(activity)

            await self.context.adapter.continue_conversation_with_claims(
                claims_identity=self.context.identity,
                continuation_activity=continuation,
                callback=deliver,
                audience=self.context.identity.get_token_audience(),
            )

    async def detach(self, task: asyncio.Task) -> None:
        async with self.lock:
            if task.done():
                return
            await self.context.send_activity(
                "Le calcul continue. Le resultat sera envoye dans cette conversation.",
            )
            self.detached = True


def build_host(agent: Agent):
    class AstronomyHost(ActivityAgentServerHost, AstronomyResponsesHost):
        pass

    host = AstronomyHost(agent=agent)
    store = ConversationStore()
    config = widgets.configuration()
    if config is None:
        LOGGER.warning(
            "Teams HTML Widgets disabled: configure Blob storage and HTTPS widget assets."
        )

    async def on_widget(context: TurnContext, _state: TurnState) -> None:
        try:
            scope = widgets.conversation_binding(context)
            async with _locks.setdefault(scope, asyncio.Lock()):
                result = await widgets.call_tool(context, store.read(scope).widgets)
        except ValueError as error:
            LOGGER.warning("Widget authentication rejected: %s", error)
            result = widgets.call_result(str(error), error=True)
        await context.send_activity(
            Activity(
                type="invokeResponse",
                value={"status": 200, "body": result},
            )
        )

    host.agent_app.add_route(
        lambda context: (
            context.activity.type == "invoke" and context.activity.name == widgets.INVOKE_NAME
        ),
        on_widget,
        is_invoke=True,
    )

    @host.agent_app.activity("message")
    async def on_message(context: TurnContext, _state: TurnState) -> None:
        scope = widgets.conversation_binding(context)
        text = (context.activity.text or "").strip()
        if not text or len(text) > 8000:
            await context.send_activity("Envoyez une demande textuelle de 1 a 8 000 caracteres.")
            return
        delivery = Delivery(context)

        async def run_turn() -> None:
            async with _locks.setdefault(scope, asyncio.Lock()):
                conversation = store.read(scope)
                if text.lower() == "/clear":
                    store.write(scope, Conversation([], []))
                    await delivery.send(
                        Activity(type="message", text="Historique et widgets effaces.")
                    )
                    return
                await delivery.send(Activity(type="typing"))
                captured = RenderContext(scope)
                token = render_context.set(captured)
                try:
                    messages = [
                        Message(role=entry["role"], contents=[Content.from_text(entry["text"])])
                        for entry in conversation.history
                    ]
                    messages.append(Message(role="user", contents=[Content.from_text(text)]))
                    async with asyncio.timeout(120):
                        response = await agent.run(messages)
                    answer = response.text
                    conversation.history.extend(
                        [
                            {"role": "user", "text": text},
                            {"role": "assistant", "text": answer[:16000]},
                        ]
                    )
                    if config:
                        conversation.widgets.extend(item["id"] for item in captured.renders)
                    store.write(scope, conversation)
                    await delivery.send(Activity(type="message", text=answer))
                    if config:
                        for item in captured.renders:
                            await delivery.send(
                                Activity(
                                    type="message",
                                    text=widgets.widget_markdown(item["id"], config),
                                    text_format="extendedmarkdown",
                                )
                            )
                    elif captured.renders:
                        await delivery.send(
                            Activity(
                                type="message",
                                text=(
                                    "Calcul termine. Configurez les assets HTTPS et le stockage "
                                    "Blob du widget Teams pour afficher la 3D ici."
                                ),
                            )
                        )
                except Exception as error:
                    LOGGER.error("Teams turn failed (%s).", type(error).__name__)
                    await delivery.send(
                        Activity(
                            type="message",
                            text=(
                                "La demande a echoue. Verifiez les journaux de l'agent "
                                "puis reessayez."
                            ),
                        )
                    )
                finally:
                    render_context.reset(token)

        task = asyncio.create_task(run_turn())
        _tasks.add(task)

        def finished(completed: asyncio.Task) -> None:
            _tasks.discard(completed)
            if not completed.cancelled() and completed.exception() is not None:
                LOGGER.error("Teams delivery failed (%s).", type(completed.exception()).__name__)

        task.add_done_callback(finished)
        done, _ = await asyncio.wait({task}, timeout=30)
        if done:
            await task
        else:
            await delivery.detach(task)

    return host
