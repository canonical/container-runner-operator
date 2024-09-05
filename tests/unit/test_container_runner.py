import unittest
from container_runner import _Docker, ContainerRunner
from unittest import mock
import subprocess

# TODO: Could these not be table tests?


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


class TestContainerRunner(unittest.TestCase):
    def setUp(self):
        self.container_runner = ContainerRunner(
            container_image="test_image", container_port=80, host_port=8080
        )

    @mock.patch("container_runner._Docker.run_container")
    def test_run_success(self, _mock_run_container):
        self.container_runner.run()
        _mock_run_container.assert_called_once_with("test_image", "managed_container", 8080, 80)

    @mock.patch("container_runner.ContainerRunner.running", new_callable=mock.PropertyMock)
    @mock.patch("container_runner._Docker.run_container")
    def test_run_already_running(self, _mock_run_container, _mock_running):
        _mock_running.return_value = True

        with self.assertLogs("container_runner", level="INFO") as log:
            self.container_runner.run()
        _mock_run_container.assert_not_called()
        self.assertIn(
            "INFO:container_runner:Managed container already running, skipping run command.",
            log.output,
        )

    @mock.patch("container_runner.ContainerRunner.running", new_callable=mock.PropertyMock)
    @mock.patch(
        "container_runner._Docker.run_container",
        side_effect=Exception("Failed to start container"),
    )
    def test_run_failure(self, _mock_run_container, _mock_running):
        _mock_running.return_value = False

        with self.assertRaises(Exception) as e:
            self.container_runner.run()
        self.assertEqual(str(e.exception), "Failed to start container")
        _mock_run_container.assert_called_once_with("test_image", "managed_container", 8080, 80)

    @mock.patch("container_runner.ContainerRunner.running", new_callable=mock.PropertyMock)
    @mock.patch("container_runner._Docker.stop_container")
    @mock.patch("container_runner._Docker.remove_container")
    @mock.patch("container_runner._Docker.run_container")
    def test_configure_success(
        self, _mock_run_container, _mock_remove_container, _mock_stop_container, _mock_running
    ):
        _mock_running.return_value = True

        self.container_runner.configure(env_vars={"ENV_VAR": "value"})

        _mock_stop_container.assert_called_once_with("managed_container")
        _mock_remove_container.assert_called_once_with("managed_container")
        _mock_run_container.assert_called_once_with(
            "test_image", "managed_container", 8080, 80, {"ENV_VAR": "value"}
        )

    @mock.patch("container_runner.ContainerRunner.running", new_callable=mock.PropertyMock)
    @mock.patch(
        "container_runner._Docker.stop_container",
        side_effect=Exception("Failed to stop container"),
    )
    @mock.patch("container_runner._Docker.remove_container")
    @mock.patch("container_runner._Docker.run_container")
    def test_configure_stop_failure(
        self, _mock_run_container, _mock_remove_container, _mock_stop_container, _mock_running
    ):
        _mock_running.return_value = True

        with self.assertRaises(Exception) as e:
            self.container_runner.configure(env_vars={"ENV_VAR": "value"})
        self.assertEqual(str(e.exception), "Failed to stop container")

        _mock_stop_container.assert_called_once_with("managed_container")
        _mock_remove_container.assert_not_called()
        _mock_run_container.assert_not_called()

    @mock.patch("container_runner.ContainerRunner.running", new_callable=mock.PropertyMock)
    @mock.patch("container_runner._Docker.stop_container")
    @mock.patch(
        "container_runner._Docker.remove_container",
        side_effect=Exception("Failed to remove container"),
    )
    @mock.patch("container_runner._Docker.run_container")
    def test_configure_remove_failure(
        self, _mock_run_container, _mock_remove_container, _mock_stop_container, _mock_running
    ):
        _mock_running.return_value = True

        with self.assertRaises(Exception) as e:
            self.container_runner.configure(env_vars={"ENV_VAR": "value"})
        self.assertEqual(str(e.exception), "Failed to remove container")

        _mock_stop_container.assert_called_once_with("managed_container")
        _mock_remove_container.assert_called_once_with("managed_container")
        _mock_run_container.assert_not_called()

    @mock.patch("container_runner.ContainerRunner.running", new_callable=mock.PropertyMock)
    @mock.patch("container_runner._Docker.stop_container")
    @mock.patch("container_runner._Docker.remove_container")
    @mock.patch(
        "container_runner._Docker.run_container",
        side_effect=Exception("Failed to re-run container"),
    )
    def test_configure_rerun_failure(
        self, _mock_run_container, _mock_remove_container, _mock_stop_container, _mock_running
    ):
        _mock_running.return_value = True

        with self.assertRaises(Exception) as e:
            self.container_runner.configure(env_vars={"ENV_VAR": "value"})
        self.assertEqual(str(e.exception), "Failed to re-run container")

        _mock_stop_container.assert_called_once_with("managed_container")
        _mock_remove_container.assert_called_once_with("managed_container")
        _mock_run_container.assert_called_once_with(
            "test_image", "managed_container", 8080, 80, {"ENV_VAR": "value"}
        )

    @mock.patch("container_runner.ContainerRunner.running", new_callable=mock.PropertyMock)
    @mock.patch("container_runner._Docker.run_container")
    def test_configure_no_stop_or_remove_when_not_running(
        self, _mock_run_container, _mock_running
    ):
        _mock_running.return_value = False

        self.container_runner.configure(env_vars={"ENV_VAR": "value"})

        _mock_run_container.assert_called_once_with(
            "test_image", "managed_container", 8080, 80, {"ENV_VAR": "value"}
        )

    @mock.patch("container_runner._Docker._run_command")
    def test_installed_success(self, _mock_run_command):
        _mock_run_command.side_effect = ["managed_image_details", "watchtower_image_details"]

        self.assertTrue(self.container_runner.installed)
        _mock_run_command.assert_has_calls(
            [mock.call("inspect", ["test_image"]), mock.call("inspect", ["containrrr/watchtower"])]
        )

    @mock.patch("container_runner._Docker._run_command")
    def test_installed_failure_inspection(self, _mock_run_command):
        _mock_run_command.side_effect = Exception("Failed to inspect image")

        self.assertFalse(self.container_runner.installed)
        _mock_run_command.assert_called_once_with("inspect", ["test_image"])

    @mock.patch("container_runner._Docker._run_command")
    def test_installed_partial_failure(self, _mock_run_command):
        _mock_run_command.side_effect = ["managed_image_details", None]

        self.assertFalse(self.container_runner.installed)
        _mock_run_command.assert_has_calls(
            [mock.call("inspect", ["test_image"]), mock.call("inspect", ["containrrr/watchtower"])]
        )

    @mock.patch("container_runner._Docker._run_command")
    def test_running_success(self, _mock_run_command):
        _mock_run_command.side_effect = ["true", "true"]

        self.assertTrue(self.container_runner.running)
        _mock_run_command.assert_has_calls(
            [
                mock.call("inspect", ["-f", "{{.State.Running}}", "managed_container"]),
                mock.call("inspect", ["-f", "{{.State.Running}}", "watchtower"]),
            ]
        )

    @mock.patch("container_runner._Docker._run_command")
    def test_running_failure_inspection(self, _mock_run_command):
        _mock_run_command.side_effect = Exception("Failed to inspect container")

        self.assertFalse(self.container_runner.running)
        _mock_run_command.assert_called_once_with(
            "inspect", ["-f", "{{.State.Running}}", "managed_container"]
        )

    @mock.patch("container_runner._Docker._run_command")
    def test_running_partial_failure(self, _mock_run_command):
        _mock_run_command.side_effect = ["true", "false"]

        self.assertFalse(self.container_runner.running)
        _mock_run_command.assert_has_calls(
            [
                mock.call("inspect", ["-f", "{{.State.Running}}", "managed_container"]),
                mock.call("inspect", ["-f", "{{.State.Running}}", "watchtower"]),
            ]
        )
