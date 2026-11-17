# AIstro

Un agent **Microsoft Foundry Hosted Agent** qui transforme une date demandée en
vue astronomique Babylon.js. Première capacité : `generate_zodiac`. Le modèle
interprète la demande ; **NASA/JPL et Astropy**, pas le modèle, calculent les
positions.

L'architecture reprend les principes de
[davrous/blenderagent](https://github.com/davrous/blenderagent) : Agent Framework
Python, protocoles Responses et Activity, proxy Express avec identité serveur,
chat React/Vite, stockage d'artefacts et **widget Teams autonome**. Les capacités
Blender, la voix et les jobs vidéo ne sont pas embarqués.

## Architecture

```text
Chat React/Vite ── SSE ── Proxy Express ── Responses ── Hosted agent Python
                                                        │
                                                generate_zodiac(date)
                                                        │
                                           NASA/JPL Horizons + Astropy
                                                        │
                                               JSON + HTML + source
                                                        │
                                          Disque local / Blob privé
                                                        │
                           Viewer Babylon.js partagé ───┘

Teams ── Activity ── même agent et même tool
  └── message extendedmarkdown / html-widget
       └── bootstrap autonome + assets HTTPS
            └── tools/call → htmlwidget/calltool → lien Blob temporaire
                 └── même viewer Babylon.js, sans interface de chat
```

- [main.py](main.py) construit l'agent et sa liste de tools. Il utilise
  `FoundryChatClient`, et ne crée pas un agent `kind: prompt` à la place du hosted agent.
- [astronomy_tool.py](astronomy_tool.py) résout la date et orchestre le calcul.
- [zodiaque_tropical.py](zodiaque_tropical.py) contient le client NASA restauré.
- [zodiaque_tropical_3d.py](zodiaque_tropical_3d.py) produit les données communes et
  conserve les exports historiques Matplotlib et HTML.
- [artifact_storage.py](artifact_storage.py) publie des instantanés immuables,
  isolés par conversation. Le manifeste est écrit en dernier.
- [responses_host.py](responses_host.py) conserve le contexte fourni par le proxy
  pendant l'exécution et le streaming de l'agent.
- [activity_bridge.py](activity_bridge.py) gère les conversations Teams, leur
  historique durable, `/clear`, les réponses longues et les invokes du widget.
- [teams_widgets.py](teams_widgets.py) génère le bootstrap déterministe et
  autorise uniquement la lecture du rendu dans son contexte Teams authentifié.
- [ZodiacScene.ts](webchat/client/src/scene/ZodiacScene.ts) est le renderer commun
  au chat et au [widget autonome](webchat/client/widget/).

## Dates et rendu dynamique

- `2028-02-29` signifie **29 février 2028 à 12:00 UTC**.
- Un instant ISO avec fuseau est normalisé en UTC.
- `today` utilise la date UTC du jour à midi ; `now` utilise l'instant courant.
- L'agent demande l'année lorsqu'elle manque.
- Chaque nouvelle date demandée déclenche un appel réel à NASA/JPL et une
  transformation des étoiles et frontières par Astropy.
- La caméra, le zoom et les couches sont interactifs, mais ne font pas avancer
  le temps astronomique. Changer la date produit un nouvel instantané.
- Le chat récupère les artefacts publiés par le tool ; il ne fait confiance ni
  aux liens ni au HTML que pourrait écrire le modèle.

Les signes tropicaux sont douze secteurs de 30°, distincts des treize
constellations astronomiques concernées. Les distances et tailles ne sont pas à
l'échelle. Précession, nutation et aberration sont prises en compte ; mouvement
propre et parallaxe stellaires ne sont pas modélisés.

Le CLI historique conserve sa date par défaut du 3 décembre 2026 pour
compatibilité. **L'agent n'utilise pas cette valeur par défaut.**

## Démarrage local

Prérequis : Python 3.13 recommandé, `uv`, Node.js 22 et une identité Azure ayant
accès au modèle Foundry. Les dépendances Python utilisent le flux approuvé
`https://packagefeedproxy.microsoft.io/pypi/simple`, déclaré dans
[pyproject.toml](pyproject.toml).

La configuration locale `.env`, ignorée par Git, a été préparée pour le projet
Foundry sélectionné et le déploiement `gpt-5.4-mini`. Pour une autre installation,
partir de [.env.example](.env.example) et renseigner les vraies valeurs.
Les variables injectées par l'environnement restent prioritaires.

Terminal 1, depuis la racine :

```bash
uv sync --python 3.13
uv run python main.py
```

Le serveur écoute sur `127.0.0.1:8088` avec Responses et Activity.
`ENABLE_ACTIVITY=false` désactive explicitement Activity si nécessaire.

Terminal 2 :

```bash
cd webchat
npm ci
npm run dev
```

Ouvrir <http://localhost:5173>. Si Node 22 n'est pas le Node par défaut, le mode
isolé suivant évite de changer l'installation système :

```bash
npm exec --yes --package=node@22 -- npm --prefix webchat ci
npm exec --yes --package=node@22 -- npm --prefix webchat run dev
```

Ces deux commandes sont à lancer depuis la racine du projet.

Exemples :

- « Affiche le ciel du 3 décembre 2026. »
- « Change la date pour le 21 juin 2027 à 18 h UTC. »
- « Montre le zodiaque d'aujourd'hui. »

Le sélecteur conserve les rendus de la conversation. Le HTML interactif et la
réponse NASA sont téléchargeables. Les artefacts locaux sont dans
`.aistro/artifacts/zodiac/`. Les données du navigateur ne contiennent aucun
jeton Azure.

**Mode démo local, conformément au choix initial :** le proxy utilise son
identité serveur et écoute uniquement sur l'interface loopback. Il n'inclut pas
de connexion utilisateur Entra. Ne pas l'exposer publiquement sans ajouter
l'authentification et l'autorisation utilisateur.

### Débogage VS Code

F5 lance le véritable point d'entrée de l'agent avec le Python de `.venv` et
ouvre Foundry Toolkit Agent Inspector. Les configurations sont dans
[.vscode/](.vscode/). Le chat se lance séparément.

### Build et tests

```bash
uv run ruff check *.py devTools/*.py
uv run pytest -q
npm --prefix webchat test
npm --prefix webchat run build
```

Le build produit le chat, le proxy compilé et les assets autonomes du widget.
Babylon.js est importé par modules ; le widget n'importe pas React ni le chat.
L'avertissement Vite sur la taille du renderer WebGL n'est pas une erreur de build.

Pour tester le build du chat sans Vite :

```bash
CLIENT_ORIGIN=http://localhost:5174 npm --prefix webchat start
```

Puis ouvrir <http://localhost:5174>, avec l'agent toujours actif sur 8088.

## Préparation Foundry

Le dépôt contient [agent.yaml](agent.yaml), [Dockerfile](Dockerfile) et
[requirements.txt](requirements.txt) verrouillé. Aucun déploiement ni aucune
nouvelle ressource Azure n'ont été créés dans cette étape.

Avant le déploiement :

1. Réutiliser le projet Foundry choisi et le modèle `gpt-5.4-mini`.
2. Créer ou sélectionner un compte Blob et un conteneur **privé** `aistro`.
3. Renseigner les valeurs réelles de `PROJECT_ENDPOINT`,
   `MODEL_DEPLOYMENT_NAME`, `AZURE_STORAGE_ACCOUNT_NAME` et
   `TEAMS_WIDGET_ASSET_BASE_URL` dans la configuration de déploiement. Les
   marqueurs du manifeste ne sont pas des valeurs utilisables.
4. Utiliser `ARTIFACT_STORAGE=blob` sur l'agent et le proxy en mode Foundry.
5. Accorder à l'identité d'exécution de l'agent `Storage Blob Data Contributor`
   sur le conteneur et `Storage Blob Delegator` sur le compte, pour les liens
   temporaires en lecture seule. Accorder au proxy les droits de lecture des
   artefacts. Utiliser les identités réelles du déploiement, sans supposer que
   l'identité du projet est celle du hosted agent.
6. Vérifier la disponibilité d'Azure CLI et l'authentification avant d'exécuter
   le workflow Foundry. Azure CLI n'était pas présent sur cette machine.

Voir le
[workflow officiel Hosted Agents](https://learn.microsoft.com/azure/ai-foundry/agents/concepts/hosted-agents?view=foundry).
Les valeurs de connexion ne doivent pas être placées dans le navigateur.

Pour connecter le proxy à l'agent déployé, renseigner dans `webchat/.env` :

```dotenv
AGENT_MODE=foundry
AGENT_NAME=aistro-agent
ARTIFACT_STORAGE=blob
```

Ajouter `AGENT_FOUNDRY_URL` avec le véritable **endpoint de projet** et les
variables du stockage partagé. Le proxy crée une session hosted et une
conversation Responses par conversation navigateur. Le cache de ces
identifiants est en mémoire, comme dans la version démo de BlenderAgent :
une version multi-instance nécessite un stockage partagé.

## Teams et HTML Widget

Le widget est une interface dédiée, pas un iframe du chat complet :

- Message Activity `textFormat: extendedmarkdown` contenant un bloc `html-widget`.
- Handshake JSON-RPC `ui/initialize`, puis notification d'initialisation.
- Lecture via `tools/call` → invoke exact `htmlwidget/calltool`.
- Réponse `htmlwidget/calltoolresult` avec `content`, `structuredContent`, `isError`.
- Autorisation par tenant, bot, conversation et registre de rendus. Le modèle ne
  peut pas choisir les droits, le scope ou l'URL de stockage.
- Aucun SAS dans le HTML du message ; lien Blob en lecture seule valable
  quinze minutes obtenu lors du chargement. Recharger renouvelle le lien.
- Caméra et couches exécutées côté navigateur, sans tour LLM supplémentaire.
- Thèmes Teams, hauteur intrinsèque, mode agrandi si annoncé par l'hôte,
  suspension du rendu hors écran et libération du moteur.

### Publier les assets publics

Après le build, avec le **vrai Bot ID** associé à ce nouvel agent :

```text
node devTools/package_teams_widget.mjs BOT_ID REPERTOIRE_DE_SORTIE_NEUF
```

Le script ne provisionne rien. Il prépare un site statique contenant
`teams-widget/v1/widget.js`, `widget.css`, les licences et la configuration CORS.
Publier ce site sous une URL HTTPS publique, par exemple sur Azure Static Web
Apps, puis renseigner l'URL complète du dossier `teams-widget/v1` dans
`TEAMS_WIDGET_ASSET_BASE_URL`.

L'origine Teams calculée par le script est :

```text
https://SHA256("28:" + botId_en_minuscules)[0:32].widget-renderer.usercontent.microsoft
```

Ne pas hacher le GUID seul. Confirmer l'origine réelle dans Teams et ajouter une
règle CORS Blob pour cette origine exacte : `GET`, `HEAD`, `OPTIONS`, en-têtes
nécessaires et exposition de `Content-Length`, `Content-Type`, `ETag`. Conserver
les autres règles existantes et ne jamais rendre le conteneur public.

Le déploiement du conteneur Foundry **ne publie pas** les assets JavaScript/CSS.
Pour servir ces assets depuis le proxy au lieu d'un site statique, configurer
`TEAMS_WIDGET_RENDERER_ORIGIN` ; les APIs du chat ne doivent pas être exposées
publiquement dans ce mode démo.

### Package d'application Teams

[manifest.template.json](m365sideloadmanifest/manifest.template.json) reprend le
format custom-engine agent du dépôt Blender. Produire un ZIP avec :

```bash
uv run python devTools/package_teams.py --help
```

Le script exige les vrais App ID, Bot ID, URL des assets, compte de stockage,
nom du développeur et URL publiques de site, confidentialité et conditions.
Il génère les deux icônes PNG et refuse d'écraser un package existant.
Il ne crée ni bot, ni inscription Entra, ni publication Teams.

### Persistance et limites

L'historique Teams et les trente-deux derniers identifiants de widgets sont
persistés en SQLite sous `$HOME/.aistro` en mode Blob, ou sous
`AISTRO_STATE_DIR` si défini. Le volume `$HOME` doit être durable sur le host.
`/clear` efface l'historique et invalide les futurs chargements des anciens
widgets ; il ne révoque pas un SAS déjà délivré ni ne supprime physiquement les
artefacts. Configurer une politique de rétention Blob adaptée.

Les réponses longues utilisent une livraison proactive après trente secondes.
Un arrêt ou une mise en veille du runtime peut interrompre un travail en cours :
aucune exécution continue n'est promise pendant son arrêt.

**À valider après publication dans le tenant cible :** activation de la preview
HTML Widgets, transport des invokes via Foundry, CORS réels, WebGL,
réouverture après redémarrage, renouvellement des liens, `/clear`, ainsi que les
conversations personnelles, groupes et threads de canal. Les tests locaux ne
constituent pas une validation dans Teams.

## Ajouter une capacité

Définir un nouveau tool Agent Framework dans son propre module puis l'ajouter
à `tools=[generate_zodiac, ...]` dans [main.py](main.py). Aucun changement du
transport Responses/Activity n'est nécessaire. Une capacité produisant un
autre type d'artefact pourra ajouter son contrat et son viewer, sans coupler
sa logique au chat.

## Validation réalisée

- Tests Python : client NASA, dates/fuseaux, géométrie, transformations stellaires,
  publication du JSON/HTML, erreurs sans rendu de remplacement, isolation et
  invalidation des widgets.
- Tests TypeScript : streaming SSE coupé au milieu d'UTF-8 ou de CRLF, réponse
  incomplète et isolation des artefacts par navigateur/conversation.
- Build de production du proxy, du chat et du widget.
- Parcours navigateur réel avec `gpt-5.4-mini`, NASA/JPL et WebGL :
  `2026-12-03T12:00:00Z` → longitude `251.3261383°` ;
  `2027-06-21T18:00:00Z` → longitude `90.1518059°`.
- Build de production testé avec « 29 février 2028 à 13 h UTC+01:00 » :
  normalisation à `2028-02-29T12:00:00Z`, longitude `340.4272092°`.
- Rendu WebGL effectif et changement de géométrie visible lors du masquage
  des couches.
- Bundle du widget testé dans une fixture navigateur locale avec host JSON-RPC
  et lecture Blob simulés : initialisation, chargement, rendu et diagnostic de
  connexion. Cela ne remplace pas le test dans un vrai client Teams.

Le déploiement cloud, la construction d'image Docker et la validation dans un
vrai client Teams ne sont pas annoncés comme effectués. Le daemon Docker local
n'était pas disponible. Avant publication, utiliser F5, élargir l'évaluation
des demandes naturelles et des erreurs, puis déployer et effectuer les tests
Foundry/Teams dans le tenant cible.
