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

**Parcours de lecture**

- Première utilisation : [démarrage local](#démarrage-local).
- Nouvelle souscription ou nouveau projet : [guide de déploiement complet](#déployer-dans-un-nouvel-environnement).
- Installation de référence : [ressources Azure provisionnées](#ressources-azure-provisionnées).
- Intégration du client Teams : [Teams et HTML Widget](#teams-et-html-widget).
- En cas d'échec : [diagnostic du déploiement](#diagnostic-du-déploiement).

## Déployer dans un nouvel environnement

Ce guide est destiné à un humain **ou à un agent de développement**. Il utilise
un projet Foundry, un modèle, un ACR, un stockage privé et un site statique.
Les noms, identifiants et URL de l'installation de référence plus bas ne doivent
pas être réutilisés aveuglément.

Utiliser une copie de travail séparée par environnement. `.azure/`, `.env` et
`infra/provisioned.json` sont locaux à une installation. Si une archive contient
ces fichiers, les mettre de côté **dans la nouvelle copie uniquement** avant
de commencer ; ne pas effacer l'état d'une installation active.

### 1. Prérequis et autorisations

- Python **3.13**, `uv`, Node.js **22** et npm **10** recommandés.
- Azure CLI **2.93.0** et azd **1.37.2** ont été utilisés pour cette installation.
  Installer l'extension Foundry avec `azd extension install microsoft.foundry`.
- Un accès réseau HTTPS à Azure, au flux Python autorisé, à npm et à
  `https://ssd.jpl.nasa.gov/api/horizons.api`.
- Des droits de création sur le groupe de ressources et
  `Microsoft.Authorization/roleAssignments/write` pour les attributions RBAC.
  `Contributor` seul ne suffit pas pour donner des rôles aux identités.
- Le modèle choisi doit être disponible et disposer de quota dans la région.
  Le profil vérifié utilise `northcentralus` ; le site statique est en `eastus2`.
- Docker local n'est **pas** nécessaire : la construction s'effectue dans ACR.
- Faire approuver les coûts avant création : modèle, ACR et calcul hébergé sont
  facturables ; le stockage est à l'usage et le site du widget utilise Free.

Guides officiels :
[Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli),
[azd](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd),
[Hosted Agents](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent).

Option testée pour installer Azure CLI sans modifier le Python du projet :
dans un répertoire d'outillage **neuf**, créer un venv, y installer `pip`, puis
`azure-cli==2.93.0` avec `pip` depuis le flux approuvé. Utiliser `pip` pour cette
installation évite le retour silencieux d'anciens résolveurs uv vers Azure CLI
2.0 lorsque des dépendances beta épinglées ne sont pas sélectionnées.
Ajouter ensuite le `bin` de cet environnement au `PATH` du terminal.
Sur cette machine, le chemin est
`$HOME/.local/share/aistro-tools/azure-cli/bin`. Vérifier `az version` et
`python -m pip check` dans ce venv avant de poursuivre.

Les connexions interactives suivantes sont à réaliser **manuellement par
l'humain**, pas à déclencher automatiquement par un agent :

```bash
az login
azd auth login
az account show
```

Le compte Azure CLI et le compte azd doivent viser le bon tenant. Dans les
commandes suivantes, conserver `--subscription` pour éviter de dépendre d'une
souscription globale sélectionnée sur une machine partagée.

Depuis la racine du dépôt :

```bash
uv sync --python 3.13
npm --prefix webchat ci
uv run pytest -q
npm --prefix webchat test
```

Le flux Python configuré est `https://packagefeedproxy.microsoft.io/pypi/simple`.
S'il n'est pas accessible dans l'organisation cible, choisir un flux approuvé
et adapter aussi l'URL de `pip install` dans le Dockerfile, puis reconstruire
l'image. Ne pas supprimer la vérification TLS ; les clients Python de
l'application utilisent les certificats système via `truststore`.

### 2. Définir les paramètres de l'environnement

Renseigner ces variables avec de **vraies valeurs de l'environnement cible** :

| Variable | Signification |
|---|---|
| `SUBSCRIPTION_ID` | GUID de la souscription |
| `TENANT_ID` | GUID du tenant Entra |
| `RG` | Groupe de ressources dédié à cette installation |
| `FOUNDRY_ACCOUNT` | Nom globalement unique du compte Foundry |
| `PROJECT_NAME` | Nom du projet Foundry |
| `MODEL_DEPLOYMENT` | Nom du déploiement du modèle ; `gpt-5.4-mini` pour le profil courant |
| `ACR_NAME` | Nom globalement unique du registre, alphanumérique |
| `ENV_NAME` | Nom local azd, par exemple `aistro` |

```bash
LOCATION=northcentralus
MODEL_NAME=gpt-5.4-mini
ENV_NAME=aistro
```

Pour une autre région, vérifier d'abord le support des Hosted Agents et du
modèle, puis adapter la région du stockage dans `infra/provision.py` et
`infra/main.json`. Une région de modèle indisponible ne doit pas être remplacée
silencieusement.

### 3. Créer ou réutiliser Foundry et son modèle

**Si ces ressources existent :** ne pas les recréer. Relever le véritable
`PROJECT_ID` ARM et `PROJECT_ENDPOINT` dans Foundry/Azure, vérifier le déploiement
du modèle, puis passer à l'étape 4. Ne pas déduire un ID ARM du nom d'hôte.

**Pour un nouveau groupe, compte et projet :**

Dans une souscription vierge, faire enregistrer au préalable les providers
suivants par un principal autorisé au niveau de la souscription :

```bash
for NS in Microsoft.CognitiveServices Microsoft.ContainerRegistry Microsoft.Storage \
  Microsoft.Web Microsoft.BotService Microsoft.ManagedIdentity; do
  az provider register --namespace "$NS" --subscription "$SUBSCRIPTION_ID" --wait
done
```

```bash
az group create --name "$RG" --location "$LOCATION" \
  --subscription "$SUBSCRIPTION_ID"

az cognitiveservices account create --name "$FOUNDRY_ACCOUNT" \
  --resource-group "$RG" --location "$LOCATION" --kind AIServices --sku S0 \
  --custom-domain "$FOUNDRY_ACCOUNT" --assign-identity \
  --allow-project-management true --subscription "$SUBSCRIPTION_ID" --yes

PROJECT_ID="$(az cognitiveservices account project create \
  --name "$FOUNDRY_ACCOUNT" --project-name "$PROJECT_NAME" \
  --resource-group "$RG" --location "$LOCATION" --assign-identity \
  --subscription "$SUBSCRIPTION_ID" --query id -o tsv)"
```

Relever ensuite le `PROJECT_ENDPOINT` réel affiché pour ce projet dans Foundry,
ou utiliser la propriété ARM réellement renvoyée :

```bash
PROJECT_ENDPOINT="$(az resource show --ids "$PROJECT_ID" --api-version 2025-06-01 \
  --subscription "$SUBSCRIPTION_ID" --query 'properties.endpoints."AI Foundry API"' -o tsv)"
```

Pour préparer le modèle :

```bash
az cognitiveservices account list-models --name "$FOUNDRY_ACCOUNT" \
  --resource-group "$RG" --subscription "$SUBSCRIPTION_ID" -o json
```

Choisir dans ce catalogue une version réellement disponible du modèle et une
capacité compatible avec le quota, puis renseigner `MODEL_VERSION` et
`MODEL_CAPACITY`. Ne pas inventer une version :

```bash
: "${MODEL_VERSION:?Renseigner une version disponible du modele}"
: "${MODEL_CAPACITY:?Renseigner la capacite approuvee}"
az cognitiveservices account deployment create --name "$FOUNDRY_ACCOUNT" \
  --resource-group "$RG" --deployment-name "$MODEL_DEPLOYMENT" \
  --model-format OpenAI --model-name "$MODEL_NAME" --model-version "$MODEL_VERSION" \
  --sku-name GlobalStandard --sku-capacity "$MODEL_CAPACITY" \
  --subscription "$SUBSCRIPTION_ID"
```

Vérifier que le déploiement est `Succeeded`. Le principal de déploiement doit
aussi avoir accès aux opérations de données du projet, par exemple
`Foundry User` (anciennement Azure AI User), ID
`53ca6127-db72-4b80-b1b0-d745d6d5456d`. La création d'un projet par CLI ne
garantit pas cette attribution au développeur.

Pour un développeur connecté en tant qu'utilisateur, après vérification des
attributions existantes :

```bash
DEPLOYER_OBJECT_ID="$(az ad signed-in-user show --query id -o tsv)"
az role assignment create --assignee-object-id "$DEPLOYER_OBJECT_ID" \
  --assignee-principal-type User \
  --role 53ca6127-db72-4b80-b1b0-d745d6d5456d --scope "$PROJECT_ID" \
  --subscription "$SUBSCRIPTION_ID"
```

En CI, utiliser le véritable object ID du principal du pipeline et le type
`ServicePrincipal`, pas la commande `signed-in-user` ni un secret commité.

### 4. Préparer l'ACR et sa connexion Foundry

Réutiliser un registre déjà connecté si approprié. Sinon :

```bash
az acr create --name "$ACR_NAME" --resource-group "$RG" --location "$LOCATION" \
  --sku Basic --admin-enabled false --role-assignment-mode rbac \
  --subscription "$SUBSCRIPTION_ID"
```

Relever `ACR_ID` et `ACR_LOGIN_SERVER` :

```bash
ACR_ID="$(az acr show --name "$ACR_NAME" --subscription "$SUBSCRIPTION_ID" --query id -o tsv)"
ACR_LOGIN_SERVER="$(az acr show --name "$ACR_NAME" \
  --subscription "$SUBSCRIPTION_ID" --query loginServer -o tsv)"
PROJECT_MI="$(az resource show --ids "$PROJECT_ID" --api-version 2025-06-01 \
  --subscription "$SUBSCRIPTION_ID" --query identity.principalId -o tsv)"

az role assignment create --assignee-object-id "$PROJECT_MI" \
  --assignee-principal-type ServicePrincipal --role AcrPull --scope "$ACR_ID" \
  --subscription "$SUBSCRIPTION_ID"
```

Dans Foundry, créer une connexion **Container Registry / Managed Identity**
vers `ACR_LOGIN_SERVER`, avec le Resource ID `ACR_ID`. Cette connexion est
distincte de l'attribution `AcrPull` : les deux doivent être correctes.
La connexion de référence possède la forme ARM non secrète suivante :

```json
{
  "properties": {
    "category": "ContainerRegistry",
    "authType": "ManagedIdentity",
    "target": "ACR_LOGIN_SERVER",
    "isSharedToAll": false,
    "metadata": { "ResourceId": "ACR_ID" }
  }
}
```

Remplacer les deux valeurs symboliques par les valeurs réelles et enregistrer
ce JSON, puis utiliser :

```bash
az cognitiveservices account connection create --name "$FOUNDRY_ACCOUNT" \
  --resource-group "$RG" --connection-name "acr-$ACR_NAME" \
  --file "$CONNECTION_FILE" --subscription "$SUBSCRIPTION_ID"
```

Vérifier la connexion dans le projet cible. Le profil ci-dessus utilise le mode
ACR RBAC classique ; pour un ACR ABAC existant, utiliser les rôles repository
adaptés plutôt que supposer qu'`AcrPull` suffit.

### 5. Provisionner le stockage et le site du widget

Depuis une copie sans ancien `infra/provisioned.json` :

```bash
uv run python infra/provision.py provision \
  --subscription-id "$SUBSCRIPTION_ID" --resource-group "$RG" --apply
uv run python infra/provision.py publish --apply
```

Le script crée StorageV2 Standard LRS et le conteneur privé `aistro`, un site
Static Web Apps Free, attribue au développeur les rôles nécessaires et vérifie
écriture/lecture/SAS/refus anonyme. Il ne crée pas de projet, modèle ou ACR.
`publish` ne publie que le widget autonome, pas le chat ni les données privées.

À ce stade, le Bot ID n'existe pas encore : l'absence de CORS permissifs est
volontaire. Les URL réelles sont dans `infra/provisioned.json`.

### 6. Construire l'image et configurer azd

```bash
IMAGE_TAG="$(date -u +%Y%m%d-%H%M%S)"
az acr build --registry "$ACR_NAME" --image "aistro-agent:$IMAGE_TAG" \
  --platform linux/amd64 --file Dockerfile --timeout 1800 \
  --subscription "$SUBSCRIPTION_ID" .
export AISTRO_AGENT_IMAGE="$ACR_LOGIN_SERVER/aistro-agent:$IMAGE_TAG"
```

Attendre le statut **Succeeded**, pas seulement un numéro de build. Ne pas
réutiliser un tag d'une ancienne image défectueuse. Le Dockerfile conserve l'UID
par défaut et ne force pas `$HOME` : le volume persistant `/home/session` de
Foundry doit être accessible en écriture. Ne pas contourner une erreur de
permissions en déplaçant l'état Teams vers `/tmp`.

Le dépôt contient déjà `azure.yaml` : **ne pas relancer `azd ai agent init`**,
qui pourrait créer une seconde définition ou un agent suffixé `-2`.
Exporter le véritable `AZURE_AI_PROJECT_ENDPOINT` avant les commandes azd :

```bash
export AZURE_AI_PROJECT_ENDPOINT="$PROJECT_ENDPOINT"
azd env new "$ENV_NAME" --subscription "$SUBSCRIPTION_ID" \
  --location "$LOCATION" --no-prompt
azd env set AZURE_RESOURCE_GROUP "$RG"
azd env set AZURE_TENANT_ID "$TENANT_ID"
azd env set AZURE_AI_PROJECT_ID "$PROJECT_ID"
azd env set AZURE_AI_PROJECT_ENDPOINT "$PROJECT_ENDPOINT"
azd env set AZURE_AI_MODEL_DEPLOYMENT_NAME "$MODEL_DEPLOYMENT"
azd env set AZURE_CONTAINER_REGISTRY_NAME "$ACR_NAME"
azd env set AZURE_CONTAINER_REGISTRY_ENDPOINT "$ACR_LOGIN_SERVER"
azd env set AZURE_CONTAINER_REGISTRY_RESOURCE_ID "$ACR_ID"
azd env set AISTRO_AGENT_IMAGE "$AISTRO_AGENT_IMAGE"
```

Lire `storageAccountName` et `widgetBaseUrl` dans `infra/provisioned.json` et
renseigner :

```bash
azd env set AZURE_STORAGE_ACCOUNT_NAME "$STORAGE_ACCOUNT_NAME"
azd env set TEAMS_WIDGET_ASSET_BASE_URL "$WIDGET_BASE_URL"
```

Ne pas copier les valeurs de `agent.yaml` de l'installation de référence.
`azure.yaml` utilise les valeurs de l'environnement azd ; son image et son
endpoint de projet sont paramétrés. Conserver `imagePassthrough: true` et
`remoteBuild: false` : l'image a déjà été construite à l'étape précédente.

### 7. Déployer, relever les vrais identifiants et attribuer les droits

```bash
azd deploy aistro-agent --no-prompt
azd ai agent show aistro-agent --output json
```

Relever `instance_identity.principal_id` dans la réponse. C'est
`AGENT_PRINCIPAL_ID` : **pas** l'identité du projet, pas le blueprint, pas une
valeur déduite d'un nom. Le statut `active` prouve l'enregistrement de la
version, pas encore son démarrage effectif.

Après vérification des rôles déjà présents, attribuer si nécessaire
`Foundry User` au principal réel sur `PROJECT_ID` :

```bash
az role assignment create --assignee-object-id "$AGENT_PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role 53ca6127-db72-4b80-b1b0-d745d6d5456d --scope "$PROJECT_ID" \
  --subscription "$SUBSCRIPTION_ID"
```

Lire `TEAMS_APP_SETUP.md` généré par azd et vérifier le Bot ID dans la
ressource Azure Bot. Ne pas supposer que Bot ID et principal ID sont toujours
identiques. Une fois les deux vraies valeurs relevées :

```bash
uv run python infra/provision.py activate-teams \
  --bot-id "$BOT_ID" --agent-principal-id "$AGENT_PRINCIPAL_ID" --apply
```

Cette commande donne `Storage Blob Data Contributor` sur le seul conteneur et
`Storage Blob Delegator` sur le compte, ajoute les CORS Blob pour le MRI exact,
et republie le widget. Elle attend la propagation des headers du site, qui peut
prendre quelques dizaines de secondes. Vérifier les rôles par **object ID** :

```bash
az role assignment list --assignee-object-id "$AGENT_PRINCIPAL_ID" --all \
  --subscription "$SUBSCRIPTION_ID" -o table
```

### 8. Prouver le fonctionnement distant

```bash
azd ai agent sessions create aistro-agent "$AGENT_VERSION" --output json
azd ai agent invoke aistro-agent --protocol responses \
  --session-id "$SESSION_ID" --timeout 360 \
  "Genere le zodiaque du 29 fevrier 2028 a 12 h UTC."
```

Utiliser les identifiants réellement renvoyés. Une session est déjà liée à sa
version : ne pas combiner `--version` et `--session-id` dans `invoke`.
Pour un succès complet :

1. La session atteint l'état prêt, sans `session_not_ready`.
2. L'agent appelle son tool et confirme la bonne date UTC.
3. Le stockage privé contient `data.json`, `chart.html`, `source.txt`,
   `manifest.json` sous un nouveau préfixe `zodiac/`.
4. Les dates et coordonnées du JSON correspondent au résultat demandé.
5. Un accès anonyme reste refusé ; les SAS temporaires et les CORS sont exacts.

Ne pas annoncer un déploiement fonctionnel sur la seule base du Playground,
du statut `active` ou d'une réponse générique « bonjour ».
Arrêter les sessions de test dont on n'a plus besoin, sans supprimer leurs
fichiers :

```bash
azd ai agent sessions stop "$SESSION_ID"
```

### 9. Brancher les clients

- **Chat local vers Foundry :** configurer `webchat/.env` avec
  `AGENT_MODE=foundry`, le véritable endpoint de **projet**, `AGENT_NAME`,
  `ARTIFACT_STORAGE=blob` et le compte/conteneur partagés. L'identité du proxy
  doit pouvoir lire les artefacts et invoquer l'agent. Le proxy reste local
  tant qu'une authentification utilisateur Entra n'a pas été ajoutée.
- **Teams :** produire le ZIP avec `devTools/package_teams.py --help`, les vrais
  IDs et URL légales, puis sideloader l'application. Le guide généré par azd
  explique la connexion au bot. Tester le widget dans le tenant cible : le
  succès Responses ne valide pas à lui seul Activity ou les politiques Teams.
- **Évaluation :** facultative après le smoke test ; ne pas lancer de génération
  ou d'évaluation payante sans accord.

### Diagnostic du déploiement

```bash
azd ai agent doctor --output json
azd ai agent sessions list --output json
azd ai agent monitor aistro-agent --session-id "$SESSION_ID" --tail 120
azd ai agent monitor aistro-agent --session-id "$SESSION_ID" --type system --tail 120
```

| Symptôme | Vérification / correction |
|---|---|
| `active` mais invocation bloquée | Créer une session explicite et examiner les logs du conteneur |
| `session_not_ready` / `/readiness` non disponible | Vérifier le bind `0.0.0.0:8088`, les imports et le démarrage |
| `PermissionError: /home/session/.aistro` | Ne pas forcer un UID incompatible avec le volume Foundry ; conserver le Dockerfile validé |
| Échec de pull de l'image | Vérifier l'image, la connexion ACR et les droits de l'identité du projet |
| Modèle en 403 | Vérifier `Foundry User`, l'identité réellement utilisée et le bon endpoint de projet |
| Blob en 403 | Vérifier l'object ID du runtime et attendre la propagation RBAC ; ne pas utiliser de clé partagée |
| Lecture Blob OK, SAS impossible | Vérifier `Storage Blob Delegator` au niveau du compte |
| Widget en erreur CORS | Utiliser le hash de `28:<bot-id>` en minuscules, pas le GUID seul, et attendre la propagation |
| Erreur TLS | Utiliser les CA système/autorisées ; ne pas désactiver la validation |
| Nouveau déploiement avec ancienne image | Reconstruire avec un nouveau tag et mettre à jour `AISTRO_AGENT_IMAGE` |
| `--version` incompatible avec `--session-id` | Choisir la version lors de la création de session ; `invoke` reçoit ensuite seulement son ID |
| Préfixe Blob inattendu après un test CLI | `--input-file` de Responses peut transmettre le fichier comme texte utilisateur ; un JSON cité dans le prompt n'est pas une métadonnée technique |

**Consignes supplémentaires pour un agent :** lire `AGENTS.md`, réutiliser les
ressources fournies, ne jamais exposer de token dans les commandes/logs/fichiers,
ne pas changer de souscription/région implicitement, conserver les fichiers
existants, relever les identités réelles et vérifier une génération distante
avant de conclure. Les ressources et modèles ne doivent pas être recréés lors
d'un simple redéploiement.

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
uv run ruff check *.py devTools/*.py infra/*.py
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

## Installation Foundry de référence

L'agent `aistro-agent`, **version 2**, est déployé et son tool a été vérifié à
distance. La définition de déploiement est [azure.yaml](azure.yaml), liée à
l'environnement azd local `aistro`. Le code reste à la racine du dépôt.
L'image a été construite dans ACR, sans daemon Docker local.

### Ressources Azure provisionnées

Dans `davrousai-rg`, sur la souscription sélectionnée :

| Ressource | Configuration |
|---|---|
| Stockage `staistrob4e7de1847` | StorageV2, Standard LRS, Hot, `northcentralus` |
| Conteneur `aistro` | Privé ; accès anonyme et clés partagées désactivés |
| Site `aistro-teams-widget` | Static Web Apps Free, `eastus2`, widget public uniquement |
| Projet et modèle existants | `proj-dav`, `gpt-5.4-mini`, inchangés |
| Agent `aistro-agent` | Version 2, Responses + Activity, 2 vCPU / 4 GiB |
| Image ACR | `crmxizn3gmvwobg.azurecr.io/aistro-agent:20261117-uid0` |
| Bot Azure | `aistro-agent-bot-ba85c04e`, canal Microsoft Teams activé |

Les identifiants et URL exacts sont conservés sans secrets dans
[infra/provisioned.json](infra/provisioned.json). Le manifeste de l'agent est
renseigné avec ces valeurs. La configuration `.env` du développement local est
conservée : elle ne bascule pas implicitement vers le stockage cloud.

Le compte de développement dispose de `Storage Blob Data Contributor` sur le
conteneur et `Storage Blob Delegator` sur le compte. L'écriture, la lecture,
le refus d'accès anonyme et un SAS de lecture à délégation utilisateur ont été
vérifiés, puis la donnée temporaire de contrôle a été supprimée.

Le site public est à
<https://brave-hill-09694fc0f.3.azurestaticapps.net/>. Les bundles sont servis sous
`/teams-widget/v1/`. Ils ne contiennent ni conversation, ni rendu privé, ni secret.
Les CORS du site et du Blob autorisent maintenant l'origine exacte :
`https://089443573bcfd09af14089dfb529eeb0.widget-renderer.usercontent.microsoft`.

L'identité d'exécution réelle est
`a0616668-9fea-4875-8679-e114471f584f` (`ServiceIdentity`),
distincte de l'identité système du projet. Elle dispose de :

- `Foundry User` sur `proj-dav` ;
- `Storage Blob Data Contributor` sur le conteneur `aistro` uniquement ;
- `Storage Blob Delegator` sur le compte de stockage.

Le Bot ID relevé dans la ressource Azure Bot et dans
[TEAMS_APP_SETUP.md](TEAMS_APP_SETUP.md) est ici
`a0616668-9fea-4875-8679-e114471f584f`. Cette égalité avec le principal ID a été
constatée, pas supposée. La preuve du test et le digest de l'image sont dans
[infra/deployment-verification.json](infra/deployment-verification.json),
un fichier local non secret.

Le [template ARM](infra/main.json) et le [script](infra/provision.py) permettent
de reproduire les deux ressources, sans Azure CLI et sans créer de modèle,
d'agent, d'ACR ou d'image :

```bash
uv run python infra/provision.py provision \
  --subscription-id 480af19d-6138-460b-962c-e2a0b5aca925 \
  --resource-group davrousai-rg --apply
uv run python infra/provision.py publish --apply
```

Sans `--apply`, le script ne provisionne ni ne publie. Il refuse de remplacer
une ressource portant le nom attendu mais appartenant à une autre application.
La publication emploie un jeton de déploiement transitoire, sans l'écrire dans
les fichiers ou le trousseau, puis compare les empreintes des fichiers distants.
La CLI Static Web Apps utilise un environnement Node 22/npm 10 isolé.

Pour redéployer cette installation, **réutiliser** son projet, modèle, ACR,
stockage et site. Construire une nouvelle image, mettre à jour
`AISTRO_AGENT_IMAGE` dans l'environnement azd et lancer
`azd deploy aistro-agent --no-prompt`. Relever à nouveau l'identité réelle et ne
réattribuer les droits que si nécessaire.

La commande de raccordement déjà utilisée reste disponible pour un nouveau bot
ou une nouvelle identité :

```bash
uv run python infra/provision.py activate-teams \
  --bot-id "$BOT_ID" --agent-principal-id "$AGENT_PRINCIPAL_ID" --apply
```

Cette étape ajoute les rôles de stockage à l'identité de l'agent, préserve les
règles CORS Blob existantes, puis republie le widget avec l'origine exacte
dérivée du MRI du bot. Elle n'est pas exécutée avec des identifiants inventés.

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

- Image Linux/amd64 construite dans ACR, version 2 active et session hébergée
  prête après correction de l'UID du conteneur.
- Appel du tool dans Foundry réussi en environ 5,5 secondes :
  `2028-02-29T13:00:00+01:00` → `2028-02-29T12:00:00Z`, Poissons / Verseau.
  Les quatre fichiers privés ont été trouvés dans Blob et le JSON embarqué
  dans le HTML correspond exactement à `data.json`.
- Rôles du véritable principal et CORS du véritable bot vérifiés.

Le test dans un vrai client Teams et son sideload restent à réaliser dans le
tenant cible. L'évaluation a été différée au choix de l'utilisateur. Le projet
dispose d'Application Insights ; les traces peuvent prendre 1 à 5 minutes à
apparaître. Les avertissements d'instrumentation d'un SDK OpenAI Agents absent
ne doivent pas être confondus avec une erreur fatale de l'agent Microsoft Agent
Framework : lire le statut de session et les véritables exceptions de démarrage.
