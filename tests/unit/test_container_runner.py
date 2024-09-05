import unittest
from container_runner import _Docker
from unittest.mock import patch, call
from unittest import mock
import subprocess
import time


class TestDocker(unittest.TestCase):
    def setUp(self):
        self.docker = _Docker()

    @mock.patch("charms.operator_libs_linux.v1.snap.hold_refresh")
    @mock.patch("charms.operator_libs_linux.v1.snap.SnapCache")
    def test_install_docker(self, _mock_snap_cache, _mock_hold_refresh):
        mock_docker = mock.Mock()
        _mock_snap_cache.return_value = {"docker": mock_docker}

        self.docker.install()

        mock_docker.ensure.assert_called_once_with(mock.ANY, channel="stable")
        _mock_hold_refresh.assert_called_once()

    @mock.patch("charms.operator_libs_linux.v1.snap.hold_refresh")
    @mock.patch("charms.operator_libs_linux.v1.snap.SnapCache")
    def test_error_when_fail_to_install_docker(self, _mock_snap_cache, _mock_hold_refresh):
        mock_docker = mock.Mock()
        mock_docker.ensure.side_effect = Exception("Snap installation failed")
        _mock_snap_cache.return_value = {"docker": mock_docker}

        with self.assertRaises(Exception) as e:
            self.docker.install()

        self.assertEqual(str(e.exception), "Snap installation failed")
        _mock_hold_refresh.assert_not_called()

    @mock.patch("time.sleep", return_value=None)
    @mock.patch("subprocess.check_output")
    def test_wait_for_docker_success(self, _mock_check_output, _mock_sleep):
        self.docker._wait_for_docker()
        _mock_check_output.assert_called_once_with(["docker", "info"], universal_newlines=True)
        _mock_sleep.assert_not_called()

    @mock.patch("time.sleep", return_value=None)
    @mock.patch(
        "subprocess.check_output", side_effect=subprocess.CalledProcessError(1, "docker info")
    )
    def test_error_when_cant_check_output_of_docker_info(self, _mock_check_output, _mock_sleep):
        # Simulate Docker daemon not being ready
        with self.assertRaises(Exception) as e:
            self.docker._wait_for_docker(retries=3, delay=1)
        self.assertEqual(str(e.exception), "Docker daemon did not become ready in time")
        self.assertEqual(_mock_check_output.call_count, 3)
        _mock_sleep.assert_called()

    @mock.patch("subprocess.run")
    def test_run_command_success(self, _mock_subprocess_run):
        mock_result = mock.Mock()
        mock_result.stdout = "Command output"
        _mock_subprocess_run.return_value = mock_result
        result = self.docker._run_command("pull", ["ubuntu"])
        _mock_subprocess_run.assert_called_once_with(
            ["docker", "pull", "ubuntu"], check=True, text=True, capture_output=True
        )
        self.assertEqual(result, "Command output")

    @mock.patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "docker run"))
    def test_run_command_failure(self, _mock_subprocess_run):
        with self.assertRaises(subprocess.CalledProcessError):
            self.docker._run_command("run", ["-d", "ubuntu"])
        _mock_subprocess_run.assert_called_once_with(
            ["docker", "run", "-d", "ubuntu"], check=True, text=True, capture_output=True
        )

    @mock.patch.object(_Docker, "_run_command")
    def test_pull_image(self, _mock_run_command):
        self.docker.pull_image("ubuntu")
        _mock_run_command.assert_called_once_with("pull", ["ubuntu"])

    @mock.patch.object(
        _Docker, "_run_command", side_effect=subprocess.CalledProcessError(1, "docker pull")
    )
    def test_pull_image_failure(self, _mock_run_command):
        with self.assertRaises(subprocess.CalledProcessError):
            self.docker.pull_image("ubuntu")
        _mock_run_command.assert_called_once_with("pull", ["ubuntu"])

    @mock.patch.object(_Docker, "_run_command")
    def test_run_watchtower(self, _mock_run_command):
        self.docker.run_watchtower("watchtower", "app_container")
        expected_args = [
            "-d",
            "--name",
            "watchtower",
            "--restart",
            "unless-stopped",
            "-v",
            "/var/run/docker.sock:/var/run/docker.sock",
            "containrrr/watchtower",
        ]
        _mock_run_command.assert_called_once_with("run", expected_args)

    @mock.patch.object(
        _Docker, "_run_command", side_effect=subprocess.CalledProcessError(1, "docker run")
    )
    def test_run_watchtower_failure(self, _mock_run_command):
        with self.assertRaises(subprocess.CalledProcessError):
            self.docker.run_watchtower("watchtower", "app_container")
        expected_args = [
            "-d",
            "--name",
            "watchtower",
            "--restart",
            "unless-stopped",
            "-v",
            "/var/run/docker.sock:/var/run/docker.sock",
            "containrrr/watchtower",
        ]
        _mock_run_command.assert_called_once_with("run", expected_args)

    @mock.patch.object(_Docker, "_run_command")
    def test_run_container(self, _mock_run_command):
        self.docker.run_container("ubuntu", "test_container", 8080, 80)
        expected_args = ["-d", "--name", "test_container", "-p", "8080:80", "ubuntu"]
        _mock_run_command.assert_called_once_with("run", expected_args)

    @mock.patch.object(
        _Docker, "_run_command", side_effect=subprocess.CalledProcessError(1, "docker run")
    )
    def test_run_container_failure(self, _mock_run_command):
        with self.assertRaises(subprocess.CalledProcessError):
            self.docker.run_container("ubuntu", "test_container", 8080, 80)
        expected_args = ["-d", "--name", "test_container", "-p", "8080:80", "ubuntu"]
        _mock_run_command.assert_called_once_with("run", expected_args)

    @mock.patch.object(_Docker, "_run_command")
    def test_run_container_with_env_vars(self, _mock_run_command):
        env_vars = {"ENV_VAR": "value"}
        self.docker.run_container("ubuntu", "test_container", 8080, 80, env_vars)
        expected_args = [
            "-d",
            "--name",
            "test_container",
            "-p",
            "8080:80",
            "-e",
            "ENV_VAR=value",
            "ubuntu",
        ]
        _mock_run_command.assert_called_once_with("run", expected_args)

    @mock.patch.object(
        _Docker, "_run_command", side_effect=subprocess.CalledProcessError(1, "docker run")
    )
    def test_run_container_with_env_vars_failure(self, _mock_run_command):
        env_vars = {"ENV_VAR": "value"}
        with self.assertRaises(subprocess.CalledProcessError):
            self.docker.run_container("ubuntu", "test_container", 8080, 80, env_vars)
        expected_args = [
            "-d",
            "--name",
            "test_container",
            "-p",
            "8080:80",
            "-e",
            "ENV_VAR=value",
            "ubuntu",
        ]
        _mock_run_command.assert_called_once_with("run", expected_args)

    @mock.patch.object(_Docker, "_run_command")
    def test_stop_container(self, _mock_run_command):
        self.docker.stop_container("test_container")
        _mock_run_command.assert_has_calls(
            [
                mock.call("stop", ["test_container"]),
                mock.call("wait", ["test_container"]),
            ]
        )

    @mock.patch.object(
        _Docker, "_run_command", side_effect=subprocess.CalledProcessError(1, "docker stop")
    )
    def test_stop_container_failure(self, _mock_run_command):
        with self.assertRaises(subprocess.CalledProcessError):
            self.docker.stop_container("test_container")
        _mock_run_command.assert_called_once_with("stop", ["test_container"])

    @mock.patch.object(_Docker, "_run_command")
    def test_remove_container(self, _mock_run_command):
        self.docker.remove_container("test_container")
        _mock_run_command.assert_called_once_with("rm", ["test_container"])

    @mock.patch.object(
        _Docker, "_run_command", side_effect=subprocess.CalledProcessError(1, "docker rm")
    )
    def test_remove_container_failure(self, _mock_run_command):
        with self.assertRaises(subprocess.CalledProcessError):
            self.docker.remove_container("test_container")
        _mock_run_command.assert_called_once_with("rm", ["test_container"])
