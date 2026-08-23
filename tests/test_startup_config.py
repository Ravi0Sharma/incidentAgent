"""The public API must reject unsafe secure-mode configuration before binding."""

import unittest
from unittest.mock import patch

from scripts import start_api


class ApiStartupConfigTests(unittest.TestCase):
    def test_api_validates_runtime_before_starting_server(self):
        with (
            patch.object(start_api, "validate_runtime_config") as validate,
            patch.object(start_api.uvicorn, "run") as run,
        ):
            start_api.main()

        validate.assert_called_once_with(start_api.settings)
        run.assert_called_once()

    def test_api_does_not_bind_when_runtime_configuration_is_invalid(self):
        with (
            patch.object(
                start_api,
                "validate_runtime_config",
                side_effect=ValueError("unsafe production configuration"),
            ),
            patch.object(start_api.uvicorn, "run") as run,
        ):
            with self.assertRaisesRegex(ValueError, "unsafe production"):
                start_api.main()

        run.assert_not_called()
