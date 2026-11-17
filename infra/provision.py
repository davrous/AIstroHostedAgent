"""Provision only approved supporting assets; never deploy an agent or build an image."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from xml.etree import ElementTree

import httpx
import truststore
from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    generate_blob_sas,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(__file__).with_name("provisioned.json")
ARM = "https://management.azure.com"
DATA_CONTRIBUTOR = "ba92f5b4-2d11-453d-a403-e96b0029c9fe"
BLOB_DELEGATOR = "db58b8e5-c6ad-4a2a-8342-4190687cbf4a"


class ProvisionError(RuntimeError):
    pass


class Azure:
    def __init__(self) -> None:
        self.credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        self.http = httpx.Client(timeout=60)

    def close(self) -> None:
        self.http.close()
        self.credential.close()

    def request(self, method: str, resource: str, api: str, body=None, *, missing=False):
        response = self.http.request(
            method,
            ARM + resource,
            params={"api-version": api},
            headers={
                "Authorization": "Bearer "
                + self.credential.get_token(
                    "https://management.azure.com/.default",
                ).token
            },
            json=body,
        )
        if missing and response.status_code == 404:
            return None
        if not response.is_success:
            error = response.json().get("error", {})
            raise ProvisionError(
                f"Azure {method} {resource}: HTTP {response.status_code}, "
                f"{error.get('code', 'unknown')}: {error.get('message', '')[:1200]}",
            )
        return response.json() if response.content else {}

    def principal(self) -> tuple[str, str]:
        token = self.credential.get_token("https://management.azure.com/.default").token
        encoded = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        return str(uuid.UUID(claims["oid"])), "User" if claims.get("scp") else "ServicePrincipal"


def load_outputs() -> dict:
    if not OUTPUT.exists():
        raise ProvisionError("Provision supporting assets first.")
    value = json.loads(OUTPUT.read_text(encoding="utf-8"))
    if value.get("application") != "aistro":
        raise ProvisionError("The saved deployment context does not belong to AIstro.")
    return value


def save_outputs(value: dict) -> None:
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(OUTPUT)


def grant(azure: Azure, subscription: str, scope: str, principal: str, kind: str, role: str):
    definition = (
        f"/subscriptions/{subscription}/providers/Microsoft.Authorization/roleDefinitions/{role}"
    )
    role_info = azure.request("GET", definition, "2022-04-01")
    print(f"Granting {role_info['properties']['roleName']} at {scope}")
    name = uuid.uuid5(uuid.NAMESPACE_URL, f"{scope}/{principal}/{role}")
    resource = f"{scope}/providers/Microsoft.Authorization/roleAssignments/{name}"
    azure.request(
        "PUT",
        resource,
        "2022-04-01",
        {
            "properties": {
                "roleDefinitionId": definition,
                "principalId": principal,
                "principalType": kind,
            },
        },
    )


def provision(azure: Azure, args) -> dict:
    subscription = str(uuid.UUID(args.subscription_id))
    group = f"/subscriptions/{subscription}/resourceGroups/{args.resource_group}"
    azure.request("GET", group, "2021-04-01")
    suffix = hashlib.sha256(f"{subscription}/{args.resource_group}/aistro".encode()).hexdigest()[
        :10
    ]
    storage_name = args.storage_name or f"staistro{suffix}"
    site_name = args.site_name or "aistro-teams-widget"
    parameters = {
        "storageName": storage_name,
        "siteName": site_name,
        "location": "northcentralus",
        "siteLocation": "eastus2",
    }
    for kind, name, api in [
        ("Microsoft.Storage/storageAccounts", storage_name, "2023-05-01"),
        ("Microsoft.Web/staticSites", site_name, "2023-12-01"),
    ]:
        current = azure.request("GET", f"{group}/providers/{kind}/{name}", api, missing=True)
        if current and current.get("tags", {}).get("application") != "aistro":
            raise ProvisionError(f"Refusing to overwrite an unrelated resource: {name}")
    if OUTPUT.exists():
        current = load_outputs()
        if (
            current["subscriptionId"] != subscription
            or current["resourceGroup"] != args.resource_group
        ):
            raise ProvisionError(
                "The saved deployment targets another subscription/resource group."
            )
    print(
        json.dumps(
            {"subscriptionId": subscription, "resourceGroup": args.resource_group, **parameters}
        )
    )
    if not args.apply:
        print("Dry run: add --apply to provision.")
        return {}
    deployment = f"{group}/providers/Microsoft.Resources/deployments/aistro-assets"
    template = json.loads(Path(__file__).with_name("main.json").read_text())
    azure.request(
        "PUT",
        deployment,
        "2022-09-01",
        {
            "properties": {
                "mode": "Incremental",
                "template": template,
                "parameters": {key: {"value": value} for key, value in parameters.items()},
            }
        },
    )
    deadline = time.monotonic() + 900
    while True:
        result = azure.request("GET", deployment, "2022-09-01")["properties"]
        state = result["provisioningState"]
        print(f"ARM deployment: {state}", flush=True)
        if state == "Succeeded":
            break
        if state in {"Failed", "Canceled"}:
            raise ProvisionError(json.dumps(result.get("error", {"state": state})))
        if time.monotonic() > deadline:
            raise ProvisionError(
                "Timed out waiting for ARM deployment; inspect aistro-assets in Azure."
            )
        time.sleep(8)
    outputs = {key: item["value"] for key, item in result["outputs"].items()}
    outputs.update(
        {
            "application": "aistro",
            "subscriptionId": subscription,
            "resourceGroup": args.resource_group,
            "storageContainer": "aistro",
            "widgetBotId": None,
            "agentPrincipalId": None,
        }
    )
    if OUTPUT.exists():
        previous = load_outputs()
        for key in ("widgetBotId", "agentPrincipalId", "assetsPublished", "storageVerified"):
            if key in previous:
                outputs[key] = previous[key]
    save_outputs(outputs)
    principal, principal_type = azure.principal()
    container = outputs["storageResourceId"] + "/blobServices/default/containers/aistro"
    grant(azure, subscription, container, principal, principal_type, DATA_CONTRIBUTOR)
    grant(
        azure, subscription, outputs["storageResourceId"], principal, principal_type, BLOB_DELEGATOR
    )
    verify_storage(azure, outputs)
    outputs["storageVerified"] = True
    save_outputs(outputs)
    return outputs


def verify_storage(azure: Azure, outputs: dict) -> None:
    from datetime import UTC, datetime, timedelta

    account = outputs["storageAccountName"]
    origin = f"https://{account}.blob.core.windows.net"
    deadline = time.monotonic() + 240
    while True:
        try:
            with BlobServiceClient(origin, credential=azure.credential) as service:
                container = service.get_container_client("aistro")
                if container.get_container_properties().get("public_access"):
                    raise ProvisionError("The artifact container is public.")
                probe = container.get_blob_client(f"validation/{uuid.uuid4().hex}.txt")
                probe.upload_blob(b"aistro-private-storage-check", overwrite=False)
                try:
                    now = datetime.now(UTC)
                    key = service.get_user_delegation_key(
                        now - timedelta(minutes=5),
                        now + timedelta(minutes=10),
                    )
                    sas = generate_blob_sas(
                        account_name=account,
                        container_name="aistro",
                        blob_name=probe.blob_name,
                        user_delegation_key=key,
                        permission=BlobSasPermissions(read=True),
                        expiry=now + timedelta(minutes=10),
                        protocol="https",
                    )
                    anonymous = azure.http.get(probe.url)
                    signed = azure.http.get(f"{probe.url}?{sas}")
                    denied = anonymous.status_code in {401, 403, 404}
                    if anonymous.status_code == 409:
                        denied = (
                            ElementTree.fromstring(anonymous.content).findtext("Code")
                            == "PublicAccessNotPermitted"
                        )
                    if not denied:
                        raise ProvisionError(
                            "Anonymous access to private artifacts was not denied."
                        )
                    if (
                        signed.status_code != 200
                        or signed.content != b"aistro-private-storage-check"
                    ):
                        raise ProvisionError("Read-only user-delegation SAS verification failed.")
                finally:
                    probe.delete_blob()
            print("Private Blob read/write, anonymous denial and delegated SAS verified.")
            return
        except HttpResponseError as error:
            if error.status_code != 403 or time.monotonic() >= deadline:
                raise
            print("Waiting for storage RBAC propagation...", flush=True)
            time.sleep(15)


def run(command: list[str], *, env: dict | None = None, secret: str | None = None) -> None:
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=1200,
    )
    text = result.stdout + result.stderr
    if secret:
        text = text.replace(secret, "[REDACTED]")
    print(text, flush=True)
    if result.returncode:
        raise ProvisionError(f"Command failed with exit status {result.returncode}: {command[0]}")


def publish(azure: Azure, outputs: dict, *, bot_id: str | None) -> None:
    run(
        [
            "npm",
            "exec",
            "--yes",
            "--package=node@22",
            "--",
            "npm",
            "--prefix",
            "webchat",
            "--workspace",
            "@aistro/client",
            "run",
            "build:widget",
        ]
    )
    with tempfile.TemporaryDirectory(prefix="aistro-widget-") as directory:
        package = str(Path(directory) / "site")
        run(
            [
                "npm",
                "exec",
                "--yes",
                "--package=node@22",
                "--",
                "node",
                "devTools/package_teams_widget.mjs",
                bot_id or "--pending-bot",
                package,
            ]
        )
        secret_result = azure.request(
            "POST",
            outputs["widgetSiteResourceId"] + "/listSecrets",
            "2023-12-01",
        )
        token = secret_result["properties"]["apiKey"]
        if not token:
            raise ProvisionError("Azure did not return a Static Web Apps deployment credential.")
        environment = {
            **os.environ,
            "SWA_CLI_DEPLOYMENT_TOKEN": token,
            "NODE_USE_SYSTEM_CA": "1",
            "CI": "true",
        }
        run(
            [
                "npm",
                "exec",
                "--yes",
                "--package=node@22",
                "--package=npm@10",
                "--",
                "npm",
                "exec",
                "--yes",
                "--package=@azure/static-web-apps-cli@2.1.0",
                "--",
                "swa",
                "deploy",
                package,
                "--env",
                "production",
                "--no-use-keychain",
            ],
            env=environment,
            secret=token,
        )
    verify_published_assets(azure, outputs, bot_id=bot_id)
    outputs["assetsPublished"] = True
    outputs["widgetBotId"] = bot_id
    save_outputs(outputs)
    print(f"Verified public widget assets: {outputs['widgetBaseUrl']}")


def renderer_origin(bot_id: str) -> str:
    bot_id = str(uuid.UUID(bot_id))
    digest = hashlib.sha256(f"28:{bot_id}".encode()).hexdigest()[:32]
    return f"https://{digest}.widget-renderer.usercontent.microsoft"


def verify_published_assets(
    azure: Azure,
    outputs: dict,
    *,
    bot_id: str | None,
    timeout: float = 180,
) -> None:
    expected_origin = renderer_origin(bot_id) if bot_id else None
    deadline = time.monotonic() + timeout
    headers = {"Origin": expected_origin or "https://aistro-cors-probe.invalid"}
    while True:
        for name in ("widget.css", "widget.js", "viewer-licenses.txt"):
            local = ROOT / "webchat/client/dist/teams-widget/v1" / name
            response = azure.http.get(outputs["widgetBaseUrl"] + "/" + name, headers=headers)
            if (
                response.status_code != 200
                or hashlib.sha256(response.content).digest()
                != hashlib.sha256(local.read_bytes()).digest()
            ):
                problem = f"Published widget asset does not match the local build: {name}"
                break
            if response.headers.get("access-control-allow-origin") != expected_origin:
                problem = f"Published widget CORS origin is incorrect: {name}"
                break
        else:
            return
        if time.monotonic() >= deadline:
            raise ProvisionError(problem)
        print(f"Waiting for static-site propagation: {problem}", flush=True)
        time.sleep(5)


def activate(azure: Azure, args) -> None:
    outputs = load_outputs()
    if not args.apply:
        print("Dry run: add --apply to bind the actual Teams bot and agent identity.")
        return
    origin = renderer_origin(args.bot_id)
    principal = str(uuid.UUID(args.agent_principal_id))
    scope = outputs["storageResourceId"]
    grant(
        azure,
        outputs["subscriptionId"],
        scope + "/blobServices/default/containers/aistro",
        principal,
        "ServicePrincipal",
        DATA_CONTRIBUTOR,
    )
    grant(azure, outputs["subscriptionId"], scope, principal, "ServicePrincipal", BLOB_DELEGATOR)
    resource = scope + "/blobServices/default"
    service = azure.request("GET", resource, "2023-05-01")
    rules = service["properties"].get("cors", {}).get("corsRules", [])
    if not any(origin in rule.get("allowedOrigins", []) for rule in rules):
        if len(rules) >= 5:
            raise ProvisionError(
                "Blob CORS already has five rules; merge them explicitly before activation."
            )
        rules.append(
            {
                "allowedOrigins": [origin],
                "allowedMethods": ["GET", "HEAD", "OPTIONS"],
                "allowedHeaders": ["Range"],
                "exposedHeaders": ["Content-Length", "Content-Type", "ETag"],
                "maxAgeInSeconds": 3600,
            }
        )
    azure.request("PUT", resource, "2023-05-01", {"properties": {"cors": {"corsRules": rules}}})
    publish(azure, outputs, bot_id=str(uuid.UUID(args.bot_id)))
    outputs["agentPrincipalId"] = principal
    save_outputs(outputs)


def main() -> None:
    truststore.inject_into_ssl()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    create = commands.add_parser("provision")
    create.add_argument("--subscription-id", required=True)
    create.add_argument("--resource-group", required=True)
    create.add_argument("--storage-name")
    create.add_argument("--site-name")
    create.add_argument("--apply", action="store_true")
    upload = commands.add_parser("publish")
    upload.add_argument("--apply", action="store_true")
    bind = commands.add_parser("activate-teams")
    bind.add_argument("--bot-id", required=True)
    bind.add_argument("--agent-principal-id", required=True)
    bind.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    azure = Azure()
    try:
        if args.action == "provision":
            provision(azure, args)
        elif args.action == "activate-teams":
            activate(azure, args)
        elif args.apply:
            outputs = load_outputs()
            publish(azure, outputs, bot_id=outputs.get("widgetBotId"))
        else:
            print("Dry run: add --apply to publish only the public widget assets.")
    finally:
        azure.close()


if __name__ == "__main__":
    main()
