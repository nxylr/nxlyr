import unittest
from unittest.mock import patch, MagicMock
import os

from agent.kb_loader import load_kb


class TestKBLoader(unittest.TestCase):

    def setUp(self):
        load_kb.cache_clear()

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_env_vars_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            load_kb("nxlyr-demo")
        self.assertIn("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY", str(ctx.exception))

    @patch("requests.get")
    @patch.dict(
        os.environ,
        {
            "SUPABASE_URL": "https://fake.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "fake-key",
        },
    )
    def test_successful_kb_load_and_caching(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "id": "1c401a68-913d-49d9-844b-1db7e438a66f",
                "name": "Meridian Heights",
                "config": {
                    "fictional": True,
                    "project_name": "Meridian Heights",
                    "developer": "Aetheria Realty Group",
                },
                "tenants": {"slug": "nxlyr-demo"},
            }
        ]
        mock_get.return_value = mock_response

        # First call hits API
        kb1 = load_kb("nxlyr-demo")
        self.assertEqual(kb1["project_name"], "Meridian Heights")
        self.assertTrue(kb1["fictional"])
        self.assertEqual(mock_get.call_count, 1)

        # Verify correct parameters were passed to Supabase REST API
        endpoint_called, kwargs = mock_get.call_args
        self.assertEqual(endpoint_called[0], "https://fake.supabase.co/rest/v1/projects")
        self.assertEqual(kwargs["params"]["tenants.slug"], "eq.nxlyr-demo")

        # Second call returns cached result without hitting API again
        kb2 = load_kb("nxlyr-demo")
        self.assertEqual(kb2, kb1)
        self.assertEqual(mock_get.call_count, 1)

    @patch("requests.get")
    @patch.dict(
        os.environ,
        {
            "SUPABASE_URL": "https://fake.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "fake-key",
        },
    )
    def test_missing_tenant_slug_raises_value_error(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_get.return_value = mock_response

        with self.assertRaises(ValueError) as ctx:
            load_kb("non-existent-slug")
        self.assertIn("No project KB found in Supabase matching tenant slug 'non-existent-slug'", str(ctx.exception))

    @patch("requests.get")
    @patch.dict(
        os.environ,
        {
            "SUPABASE_URL": "https://fake.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "fake-key",
        },
    )
    def test_invalid_config_raises_value_error(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "id": "1c401a68-913d-49d9-844b-1db7e438a66f",
                "name": "Meridian Heights",
                "config": {},
                "tenants": {"slug": "nxlyr-demo"},
            }
        ]
        mock_get.return_value = mock_response

        with self.assertRaises(ValueError) as ctx:
            load_kb("nxlyr-demo")
        self.assertIn("config for tenant slug 'nxlyr-demo'", str(ctx.exception))
        self.assertIn("is empty or invalid", str(ctx.exception))

    @patch("requests.get")
    @patch.dict(
        os.environ,
        {
            "SUPABASE_URL": "https://fake.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "fake-key",
        },
    )
    def test_http_error_raises_runtime_error(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_get.return_value = mock_response

        with self.assertRaises(RuntimeError) as ctx:
            load_kb("nxlyr-demo")
        self.assertIn("HTTP 500", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
