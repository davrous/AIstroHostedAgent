"""Foundry hosted agent, using the same Responses/Activity split as BlenderAgent."""

from __future__ import annotations

import asyncio
import logging
import os
from urllib.parse import urlsplit

import truststore
from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

from astronomy_tool import generate_zodiac
from responses_host import AstronomyResponsesHost

INSTRUCTIONS = """
Tu es AIstro, un assistant de visualisation astronomique. Reponds en francais,
sauf si l'utilisateur choisit une autre langue.

Ta premiere capacite est generate_zodiac. Utilise ce tool pour produire ou
modifier une vue du zodiaque a une date demandee. D'autres tools seront ajoutes
ulterieurement ; ne pretends pas disposer de capacites qui ne sont pas enregistrees.

- Convertis les dates naturelles en YYYY-MM-DD ou en instant ISO avec fuseau.
  Une date sans heure utilise 12:00 UTC ; annonce toujours cette hypothese.
  Si l'annee manque, demande-la. Pour "aujourd'hui" utilise today ; pour
  "maintenant", now. Ne reutilise jamais la date fixe du 3 decembre 2026.
- Appelle le tool pour chaque nouvelle date demandee. Ne calcule ni n'invente
  les coordonnees astronomiques toi-meme. Ne simule jamais un succes si ok=false.
- Le client affiche automatiquement l'artefact produit. Ne genere pas de HTML,
  de JavaScript, d'URL ou de bloc JSON pour l'interface. Confirme seulement la
  date UTC, l'hypothese horaire, le signe tropical et la constellation obtenus.
- Distingue les 12 signes tropicaux de 30 degres des 13 constellations traversees
  par le Soleil, dont Ophiuchus. Le dessin est geocentrique et non a l'echelle.
- Le rendu represente l'instant demande, pas une animation de l'ecoulement du
  temps. Les mouvements de camera ne changent pas la date.
"""


async def main() -> None:
    truststore.inject_into_ssl()
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s: %(message)s")
    endpoint = os.environ.get("PROJECT_ENDPOINT", "").rstrip("/")
    model = os.environ.get("MODEL_DEPLOYMENT_NAME", "")
    parsed = urlsplit(endpoint)
    if parsed.scheme != "https" or not parsed.hostname or not model:
        raise ValueError("Configure PROJECT_ENDPOINT and MODEL_DEPLOYMENT_NAME in .env.")
    credential = DefaultAzureCredential()
    try:
        client = FoundryChatClient(project_endpoint=endpoint, model=model, credential=credential)
        agent = Agent(
            client=client,
            instructions=INSTRUCTIONS,
            tools=[generate_zodiac],
            default_options={"store": False, "allow_multiple_tool_calls": False},
        )
        if os.environ.get("ENABLE_ACTIVITY", "true").lower() == "true":
            from activity_bridge import build_host

            server = build_host(agent)
        else:
            server = AstronomyResponsesHost(agent=agent)
        await server.run_async(host=os.environ.get("AGENT_HOST", "127.0.0.1"))
    finally:
        credential.close()


if __name__ == "__main__":
    asyncio.run(main())
