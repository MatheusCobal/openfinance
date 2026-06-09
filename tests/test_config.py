import os
import unittest
from unittest.mock import patch

from app.config import Settings
from app.pluggy_client import PluggyClient, PluggyCredentialError


class SettingsTest(unittest.TestCase):
    def test_database_settings_load_without_pluggy_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)

        self.assertEqual(settings.database_url, "sqlite:///./openfinance.db")
        self.assertIsNone(settings.pluggy_client_id)
        self.assertIsNone(settings.pluggy_client_secret)

    def test_pluggy_client_requires_credentials_when_used(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("app.pluggy_client.settings", Settings(_env_file=None)):
                client = PluggyClient()
                with self.assertRaises(PluggyCredentialError):
                    client._credentials()


if __name__ == "__main__":
    unittest.main()
