import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from app.config import (
    DatabaseSettings,
    MissingPluggyCredentialsError,
    PluggySettings,
    Settings,
)
from app.database import _connect_args_for_database_url
from app.pluggy_client import PluggyClient, PluggyCredentialError


class SettingsTest(unittest.TestCase):
    def test_container_runtime_uses_sao_paulo_timezone(self):
        project_root = Path(__file__).resolve().parents[1]
        dockerfile = (project_root / "Dockerfile").read_text()
        compose = (project_root / "docker-compose.yml").read_text()
        production_compose = (project_root / "docker-compose.prod.yml").read_text()

        self.assertIn("ENV TZ=America/Sao_Paulo", dockerfile)
        self.assertIn("tzdata", dockerfile)
        self.assertIn("TZ: America/Sao_Paulo", compose)
        self.assertIn("TZ: America/Sao_Paulo", production_compose)

    def test_database_settings_load_without_pluggy_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)

        self.assertEqual(settings.database_url, "sqlite:///./openfinance.db")
        self.assertIsNone(settings.pluggy_client_id)
        self.assertIsNone(settings.pluggy_client_secret)

    def test_database_settings_are_separate_from_pluggy_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = DatabaseSettings(_env_file=None)

        self.assertEqual(settings.database_url, "sqlite:///./openfinance.db")

    def test_pluggy_settings_require_credentials_only_when_explicitly_validated(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = PluggySettings(_env_file=None)

        self.assertEqual(settings.pluggy_base_url, "https://api.pluggy.ai")
        with self.assertRaises(MissingPluggyCredentialsError):
            settings.require_credentials()

    def test_pluggy_client_requires_credentials_when_used(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("app.pluggy_client.get_pluggy_settings") as get_settings:
                get_settings.return_value = PluggySettings(_env_file=None)
                client = PluggyClient()
                with self.assertRaises(PluggyCredentialError):
                    client._credentials()

    def test_pluggy_client_reuses_connection_and_centralizes_pagination(self):
        requested_pages = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/auth":
                return httpx.Response(200, json={"apiKey": "test-api-key"})
            requested_pages.append(request.url.params["page"])
            page = int(request.url.params["page"])
            return httpx.Response(
                200,
                json={"results": [{"id": f"item-{page}"}], "totalPages": 2},
            )

        settings = PluggySettings(
            _env_file=None,
            pluggy_client_id="client-id",
            pluggy_client_secret="client-secret",
        )
        with httpx.Client(
            base_url="https://api.pluggy.test",
            transport=httpx.MockTransport(handler),
        ) as http_client:
            with patch("app.pluggy_client.get_pluggy_settings", return_value=settings):
                client = PluggyClient(http_client=http_client)
                items = client.list_items()

        self.assertEqual(items, [{"id": "item-1"}, {"id": "item-2"}])
        self.assertEqual(requested_pages, ["1", "2"])

    def test_pluggy_client_refreshes_an_expired_key_once(self):
        auth_calls = 0
        request_keys = []

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal auth_calls
            if request.url.path == "/auth":
                auth_calls += 1
                return httpx.Response(200, json={"apiKey": f"key-{auth_calls}"})
            request_keys.append(request.headers["X-API-KEY"])
            if request.headers["X-API-KEY"] == "key-1":
                return httpx.Response(401)
            return httpx.Response(200, json={"results": [], "totalPages": 1})

        settings = PluggySettings(
            _env_file=None,
            pluggy_client_id="client-id",
            pluggy_client_secret="client-secret",
        )
        with httpx.Client(
            base_url="https://api.pluggy.test",
            transport=httpx.MockTransport(handler),
        ) as http_client:
            with patch("app.pluggy_client.get_pluggy_settings", return_value=settings):
                client = PluggyClient(http_client=http_client)
                self.assertEqual(client.list_items(), [])

        self.assertEqual(auth_calls, 2)
        self.assertEqual(request_keys, ["key-1", "key-2"])

    def test_database_import_and_alembic_config_do_not_require_pluggy_credentials(self):
        env = os.environ.copy()
        env.pop("PLUGGY_CLIENT_ID", None)
        env.pop("PLUGGY_CLIENT_SECRET", None)
        env["DATABASE_URL"] = "sqlite:///./openfinance.db"

        script = (
            "from app.database import _alembic_config; "
            "cfg = _alembic_config(); "
            "assert cfg.get_main_option('sqlalchemy.url') == 'sqlite:///./openfinance.db'"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.getcwd(),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_sqlite_connect_args_are_sqlite_only(self):
        self.assertEqual(
            _connect_args_for_database_url("sqlite:///./openfinance.db"),
            {"check_same_thread": False},
        )
        self.assertEqual(
            _connect_args_for_database_url("postgresql://user:pass@localhost/db"),
            {},
        )


if __name__ == "__main__":
    unittest.main()
