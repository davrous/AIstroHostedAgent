"""Ensure asset provisioning cannot overwrite unrelated Azure resources."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from infra.provision import (
    ProvisionError,
    provision,
    renderer_origin,
    verify_published_assets,
    verify_storage,
)


class ReadOnlyAzure:
    def __init__(self, *, unrelated=False):
        self.unrelated = unrelated
        self.methods = []

    def request(self, method, resource, _api, **_kwargs):
        self.methods.append(method)
        if "/providers/" not in resource:
            return {"name": "test-rg"}
        return {"tags": {"application": "another-app"}} if self.unrelated else None


def arguments():
    return SimpleNamespace(
        subscription_id="11111111-1111-4111-8111-111111111111",
        resource_group="test-rg",
        storage_name=None,
        site_name=None,
        apply=False,
    )


def test_dry_run_does_not_create_resources_or_require_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr("infra.provision.OUTPUT", tmp_path / "outputs.json")
    azure = ReadOnlyAzure()
    assert provision(azure, arguments()) == {}
    assert set(azure.methods) == {"GET"}
    assert not (tmp_path / "outputs.json").exists()


def test_provisioning_rejects_an_existing_resource_owned_by_another_app():
    azure = ReadOnlyAzure(unrelated=True)
    with pytest.raises(ProvisionError, match="unrelated resource"):
        provision(azure, arguments())
    assert set(azure.methods) == {"GET"}


@pytest.mark.parametrize("code", ["PublicAccessNotPermitted", "UnexpectedFailure"])
def test_storage_privacy_accepts_only_the_explicit_azure_denial_code(monkeypatch, code):
    service = MagicMock()
    service.__enter__.return_value = service
    container = service.get_container_client.return_value
    container.get_container_properties.return_value = {}
    probe = container.get_blob_client.return_value
    probe.url = "https://teststorage.blob.core.windows.net/aistro/validation/test"
    probe.blob_name = "validation/test"
    monkeypatch.setattr("infra.provision.BlobServiceClient", lambda *args, **kwargs: service)
    monkeypatch.setattr("infra.provision.generate_blob_sas", lambda **kwargs: "unit-test-only")
    client = MagicMock()
    client.get.side_effect = [
        httpx.Response(409, content=f"<Error><Code>{code}</Code></Error>".encode()),
        httpx.Response(200, content=b"aistro-private-storage-check"),
    ]
    azure = SimpleNamespace(credential=object(), http=client)
    if code == "PublicAccessNotPermitted":
        verify_storage(azure, {"storageAccountName": "teststorage"})
    else:
        with pytest.raises(ProvisionError, match="Anonymous access"):
            verify_storage(azure, {"storageAccountName": "teststorage"})
    probe.delete_blob.assert_called_once()


def test_widget_verification_waits_for_exact_cors_propagation(tmp_path, monkeypatch):
    assets = tmp_path / "webchat/client/dist/teams-widget/v1"
    assets.mkdir(parents=True)
    for name in ("widget.css", "widget.js", "viewer-licenses.txt"):
        (assets / name).write_bytes(name.encode())
    monkeypatch.setattr("infra.provision.ROOT", tmp_path)
    monkeypatch.setattr("infra.provision.time.sleep", lambda _: None)
    bot_id = "22222222-2222-4222-8222-222222222222"
    expected = renderer_origin(bot_id)
    css_requests = []

    def get(url, *, headers):
        assert headers["Origin"] == expected
        name = url.rsplit("/", 1)[-1]
        if name == "widget.css":
            css_requests.append(url)
        response_headers = {}
        if len(css_requests) > 1:
            response_headers["Access-Control-Allow-Origin"] = expected
        return httpx.Response(200, content=name.encode(), headers=response_headers)

    verify_published_assets(
        SimpleNamespace(http=SimpleNamespace(get=get)),
        {"widgetBaseUrl": "https://assets.example.test/teams-widget/v1"},
        bot_id=bot_id,
    )
    assert len(css_requests) == 2


def test_widget_verification_never_accepts_wildcard_cors(tmp_path, monkeypatch):
    assets = tmp_path / "webchat/client/dist/teams-widget/v1"
    assets.mkdir(parents=True)
    (assets / "widget.css").write_bytes(b"widget.css")
    monkeypatch.setattr("infra.provision.ROOT", tmp_path)
    response = httpx.Response(
        200,
        content=b"widget.css",
        headers={"Access-Control-Allow-Origin": "*"},
    )
    azure = SimpleNamespace(http=SimpleNamespace(get=lambda *args, **kwargs: response))
    with pytest.raises(ProvisionError, match="CORS origin"):
        verify_published_assets(
            azure,
            {"widgetBaseUrl": "https://assets.example.test"},
            bot_id=None,
            timeout=0,
        )
