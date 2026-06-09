import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from app.config import (
    DatabaseSettings,
    MissingPluggyCredentialsError,
    PluggySettings,
    Settings,
)
from app.database import _connect_args_for_database_url
from app.pluggy_client import PluggyClient, PluggyCredentialError


class SettingsTest(unittest.TestCase):
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
