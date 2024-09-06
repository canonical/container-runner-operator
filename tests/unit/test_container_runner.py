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
        test_cases = [
            {
                "name": "successful docker installation",
            },
            {
                "name": "failed docker installation",
                "expected_exception": "Snap installation failed",
            },
        ]
        for case in test_cases:
            with self.subTest(case=case["name"]):
                # Setup
                mock_docker = mock.Mock()
                if case.get("expected_exception", None):
                    mock_docker.ensure.side_effect = Exception(case["expected_exception"])
                _mock_snap_cache.return_value = {"docker": mock_docker}

                # Run test
                if case.get("expected_exception", None):
                    with self.assertRaises(Exception) as e:
                        self.docker.install()
                    self.assertEqual(str(e.exception), case["expected_exception"])
                else:
                    self.docker.install()
                mock_docker.ensure.assert_called_once_with(mock.ANY, channel="stable")

                # Assertions
                if case.get("expected_exception", None):
                    _mock_hold_refresh.assert_not_called()
                else:
                    _mock_hold_refresh.assert_called_once()

                # Reset the mocks for the next test case
                _mock_hold_refresh.reset_mock()
                mock_docker.reset_mock()

    @mock.patch("time.sleep", return_value=None)
    @mock.patch("subprocess.check_output")
    def test_wait_for_docker(self, _mock_check_output, _mock_sleep):
        test_cases = [
            {
                "name": "docker is found in wait command",
            },
            {
                "name": "docker not available after retries in wait command",
                "check_output_side_effect": subprocess.CalledProcessError(1, "docker info"),
                "expected_exception": "Docker daemon did not become ready in time",
            },
        ]
        for case in test_cases:
            with self.subTest(case=case["name"]):
                # Setup
                if case.get("check_output_side_effect", None):
                    _mock_check_output.side_effect = case["check_output_side_effect"]

                # Test execution
                if case.get("expected_exception", None):
                    with self.assertRaises(Exception) as e:
                        self.docker._wait_for_docker(retries=3, delay=1)
                    self.assertEqual(str(e.exception), case["expected_exception"])
                    self.assertEqual(_mock_check_output.call_count, 3)
                    self.assertEqual(_mock_sleep.call_count, 3)
                else:
                    self.docker._wait_for_docker()

                # Reset mocks for the next test case
                _mock_check_output.reset_mock()
                _mock_sleep.reset_mock()

    @mock.patch("subprocess.run")
    def test_run_command(self, _mock_subprocess_run):
        test_cases = [
            {
                "name": "run command called",
                "expected_output": "Command output",
            },
            {
                "name": "run command fails",
                "subprocess_side_effect": subprocess.CalledProcessError(1, "docker run"),
                "expected_exception": subprocess.CalledProcessError,
            },
        ]
        for case in test_cases:
            with self.subTest(case=case["name"]):
                # Setup
                if case.get("subprocess_side_effect", None):
                    _mock_subprocess_run.side_effect = case["subprocess_side_effect"]
                else:
                    mock_result = mock.Mock()
                    mock_result.stdout = case["expected_output"]
                    _mock_subprocess_run.return_value = mock_result

                # Test execution
                if case.get("expected_exception", None):
                    with self.assertRaises(case["expected_exception"]):
                        self.docker._run_command("run", ["-v", "ubuntu"])
                else:
                    result = self.docker._run_command("run", ["-v", "ubuntu"])
                    self.assertEqual(result, case["expected_output"])

                # Assertions
                _mock_subprocess_run.assert_called_once_with(
                    ["docker", "run", "-v", "ubuntu"],
                    check=True,
                    text=True,
                    capture_output=True,
                )

                # Reset mock for the next test case
                _mock_subprocess_run.reset_mock()

    @mock.patch.object(_Docker, "_run_command")
    def test_pull_image(self, _mock_run_command):
        test_cases = [
            {
                "name": "successful image pull",
            },
            {
                "name": "image pull failure",
                "run_command_side_effect": subprocess.CalledProcessError(1, "docker pull"),
                "expected_exception": subprocess.CalledProcessError,
            },
        ]

        for case in test_cases:
            with self.subTest(case=case["name"]):
                # Setup
                _mock_run_command.side_effect = case.get("run_command_side_effect", None)

                # Test execution
                if case.get("expected_exception", None):
                    with self.assertRaises(case["expected_exception"]):
                        self.docker.pull_image("ubuntu")
                else:
                    self.docker.pull_image("ubuntu")

                # Assertions
                _mock_run_command.assert_called_once_with("pull", ["ubuntu"])

                # Reset mock for the next test case
                _mock_run_command.reset_mock()

    @mock.patch.object(_Docker, "_run_command")
    def test_run_watchtower(self, _mock_run_command):
        test_cases = [
            {
                "name": "successful watchtower run",
            },
            {
                "name": "watchtower run failure",
                "run_command_side_effect": subprocess.CalledProcessError(1, "docker run"),
                "expected_exception": subprocess.CalledProcessError,
            },
        ]

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
        for case in test_cases:
            with self.subTest(case=case["name"]):
                # Setup
                _mock_run_command.side_effect = case.get("run_command_side_effect", None)

                # Test execution
                if case.get("expected_exception", None):
                    with self.assertRaises(case["expected_exception"]):
                        self.docker.run_watchtower("watchtower", "app_container")
                else:
                    self.docker.run_watchtower("watchtower", "app_container")

                # Assertions
                _mock_run_command.assert_called_once_with("run", expected_args)

                # Reset the mock for the next test case
                _mock_run_command.reset_mock()

    @mock.patch.object(_Docker, "_run_command")
    def test_run_container(self, _mock_run_command):
        # Common variables
        image = "ubuntu"
        container_name = "test_container"
        host_port = 8080
        container_port = 80

        test_cases = [
            {
                "name": "successful container run without env vars",
            },
            {
                "name": "container run failure without env vars",
                "run_command_side_effect": subprocess.CalledProcessError(1, "docker run"),
                "expected_exception": subprocess.CalledProcessError,
            },
            {
                "name": "successful container run with env vars",
                "env_vars": {"ENV_VAR": "value"},
            },
            {
                "name": "container run failure with env vars",
                "env_vars": {"ENV_VAR": "value"},
                "run_command_side_effect": subprocess.CalledProcessError(1, "docker run"),
                "expected_exception": subprocess.CalledProcessError,
            },
        ]
        for case in test_cases:
            with self.subTest(case=case["name"]):
                # Setup
                expected_args = [
                    "-d",
                    "--name",
                    container_name,
                    "-p",
                    f"{host_port}:{container_port}",
                ]
                if "env_vars" in case:
                    for key, value in case["env_vars"].items():
                        expected_args.extend(["-e", f"{key}={value}"])
                expected_args.append(image)
                _mock_run_command.side_effect = case.get("run_command_side_effect")

                # Test execution
                if case.get("expected_exception"):
                    with self.assertRaises(case["expected_exception"]):
                        self.docker.run_container(
                            image,
                            container_name,
                            host_port,
                            container_port,
                            case.get("env_vars"),
                        )
                else:
                    self.docker.run_container(
                        image,
                        container_name,
                        host_port,
                        container_port,
                        case.get("env_vars"),
                    )

                # Assertions
                _mock_run_command.assert_called_once_with("run", expected_args)

                # Reset the mock for the next test case
                _mock_run_command.reset_mock()

    @mock.patch.object(_Docker, "_run_command")
    def test_stop_container(self, _mock_run_command):
        # Common variables
        container_name = "test_container"

        test_cases = [
            {
                "name": "successful container stop",
                "expected_calls": [
                    mock.call("stop", [container_name]),
                    mock.call("wait", [container_name]),
                ],
            },
            {
                "name": "container stop failure",
                "run_command_side_effect": subprocess.CalledProcessError(1, "docker stop"),
                "expected_exception": subprocess.CalledProcessError,
                "expected_calls": [mock.call("stop", [container_name])],
            },
        ]

        for case in test_cases:
            with self.subTest(case=case["name"]):
                # Setup
                _mock_run_command.side_effect = case.get("run_command_side_effect")

                # Test execution
                if case.get("expected_exception"):
                    with self.assertRaises(case["expected_exception"]):
                        self.docker.stop_container(container_name)
                else:
                    self.docker.stop_container(container_name)

                # Assertions
                _mock_run_command.assert_has_calls(case["expected_calls"])

                # Reset mock for the next test case
                _mock_run_command.reset_mock()

    @mock.patch.object(_Docker, "_run_command")
    def test_remove_container(self, _mock_run_command):
        # Common variables
        container_name = "test_container"

        test_cases = [
            {
                "name": "successful container removal",
            },
            {
                "name": "container removal failure",
                "run_command_side_effect": subprocess.CalledProcessError(1, "docker rm"),
                "expected_exception": subprocess.CalledProcessError,
            },
        ]

        for case in test_cases:
            with self.subTest(case=case["name"]):
                # Setup
                _mock_run_command.side_effect = case.get("run_command_side_effect")

                # Test execution
                if case.get("expected_exception"):
                    with self.assertRaises(case["expected_exception"]):
                        self.docker.remove_container(container_name)
                else:
                    self.docker.remove_container(container_name)

                # Assertions
                _mock_run_command.assert_called_once_with("rm", [container_name])

                # Reset mock for the next test case
                _mock_run_command.reset_mock()


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