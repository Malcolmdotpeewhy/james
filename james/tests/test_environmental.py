"""
Tests for EnvironmentalLayer to ensure secure execution and correct handling of actions.
"""

import unittest
from unittest.mock import patch, MagicMock
from james.layers.environmental import EnvironmentalLayer

class TestEnvironmentalLayer(unittest.TestCase):
    def setUp(self):
        self.layer = EnvironmentalLayer()

    @patch("subprocess.run")
    def test_winget_install_command_injection_prevention(self, mock_run):
        """
        Verify that _winget_install uses shell=False and passes arguments as a list
        to prevent command injection via the package name.
        """
        # Configure the mock to return a successful result
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Successfully installed"
        mock_run.return_value = mock_result

        # Action simulating a potentially malicious package name
        malicious_package = "malicious_package_name & rm -rf /"
        action = {"type": "winget_install", "target": malicious_package}

        # Execute the layer action
        result = self.layer.execute(action)

        # Ensure the action was considered a success by the layer
        self.assertTrue(result.success)

        # Assert subprocess.run was called exactly once
        mock_run.assert_called_once()

        # Extract the arguments passed to subprocess.run
        args, kwargs = mock_run.call_args

        # Assert the command is passed as a list of arguments
        command_args = args[0]
        self.assertIsInstance(command_args, list, "Command must be passed as a list of arguments")

        # Assert shell=False is used
        self.assertFalse(kwargs.get("shell", True), "shell=False must be used to prevent command injection")

        # Assert the structure of the command arguments
        expected_command_args = [
            "winget", "install", "--id", malicious_package,
            "--accept-package-agreements", "--accept-source-agreements", "--silent"
        ]
        self.assertEqual(command_args, expected_command_args)

if __name__ == "__main__":
    unittest.main()
