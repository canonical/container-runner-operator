import unittest
import os
import json
from container_runner import _Docker, ContainerRunner, _try_set_proxy_settings
from unittest import mock
import subprocess


class TestDocker(unittest.TestCase):
    def setUp(self):
        self.docker = _Docker()

    @mock.patch("subprocess.run")
    def test_install_docker(self, mock_subprocess_run):
        test_cases = [
            {
                "name": "successful docker installation",
            },
            {
                "name": "failed docker installation",
                "expected_exception": subprocess.CalledProcessError(1, "apt-get install"),
            },
        ]
        for case in test_cases:
            with self.subTest(case=case["name"]):
                # Setup
                mock_subprocess_run.reset_mock()
                if "expected_exception" in case:
                    mock_subprocess_run.side_effect = case["expected_exception"]
                else:
                    mock_subprocess_run.side_effect = None  # No exception for successful case

                # Run test
                if "expected_exception" in case:
                    with self.assertRaises(subprocess.CalledProcessError) as e:
                        self.docker.install()
                    self.assertEqual(e.exception, case["expected_exception"])
                else:
                    self.docker.install()
                    # Check that subprocess.run was called with the correct commands
                    mock_subprocess_run.assert_any_call(
                        ["apt-get", "update"], check=True, env=mock.ANY
                    )
                    mock_subprocess_run.assert_any_call(
                        ["apt-get", "install", "-y", "docker.io"], check=True, env=mock.ANY
                    )

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
                        self.docker.run_watchtower()
                else:
                    self.docker.run_watchtower()

                # Assertions
                _mock_run_command.assert_called_once_with("run", expected_args)

                # Reset the mock for the next test case
                _mock_run_command.reset_mock()

    @mock.patch.object(_Docker, "_run_command")
    def test_run_container(self, _mock_run_command):  # noqa  W291
        # Common variables
        image = "ubuntu"
        container_name = "test_container"
        host_port = 8080
        container_port = 80

        def _mock_run_command_side_effect(command, _, test_case):
            if command == "inspect":
                state = test_case.get("container_state", "running")
                if state == "No such object" or state == "Error":
                    # Simulate "No such container" error for inspect
                    raise subprocess.CalledProcessError(
                        returncode=1, cmd=str(command), stderr=str(state)
                    )
                return state
            elif command == "run":
                # Return success or raise error based on the test case for "run"
                if test_case.get("run_command_success", True):
                    return "container started successfully"
                raise subprocess.CalledProcessError(
                    returncode=1, cmd=command, stderr="Failed to run container"
                )
            elif command == "start":
                return "started container"
            elif command == "rm":
                return "removed container"
            else:
                # Raise error for unexpected commands
                raise ValueError("Unexpected command")

        test_cases = [
            {
                "name": "successful container run without env vars",
                "container_state": "No such object",
                "run_call_expected": True,
            },
            {
                "name": "successful container run with env vars",
                "container_state": "No such object",
                "env_vars": {"ENV_VAR": "value"},
                "run_call_expected": True,
            },
            {
                "name": "skip calling run if container is already running",
                "container_state": "running",
            },
            {
                "name": "if a container exited, start it again",
                "container_state": "exited",
            },
            {
                "name": "if a container is in an unknown status, remove and restart",
                "container_state": "unknown",
                "run_call_expected": True,
            },
            {
                "name": "Error when unknown error is thrown by inspect command",
                "container_state": "Error",
                "expected_exception": True,
            },
        ]
        for case in test_cases:
            with self.subTest(case=case["name"]):
                # Setup
                inspect_expected_args = ["-f", "{{.State.Status}}", container_name]
                run_expected_args = [
                    "-d",
                    "--name",
                    container_name,
                    "-p",
                    f"{host_port}:{container_port}",
                ]
                if "env_vars" in case:
                    for key, value in case["env_vars"].items():
                        run_expected_args.extend(["-e", f"{key}={value}"])
                run_expected_args.append(image)
                _mock_run_command.side_effect = (
                    lambda command, args: _mock_run_command_side_effect(command, args, case)
                )

                # Test execution
                # Error expected
                if case.get("expected_exception", False):
                    with self.assertRaises(subprocess.CalledProcessError):
                        self.docker.run_container(
                            image,
                            container_name,
                            host_port,
                            container_port,
                            case.get("env_vars"),
                        )
                # No error expected
                else:
                    self.docker.run_container(
                        image,
                        container_name,
                        host_port,
                        container_port,
                        case.get("env_vars"),
                    )

                # Assertions
                _mock_run_command.assert_any_call("inspect", inspect_expected_args)
                if case.get("run_call_expected", False):
                    _mock_run_command.assert_any_call("run", run_expected_args)
                if case.get("container_state") == "exited":
                    _mock_run_command.assert_any_call("start", [container_name])
                if case.get("container_state") == "unknown":
                    _mock_run_command.assert_any_call("rm", [container_name])

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

    @mock.patch("container_runner.ContainerRunner.running", new_callable=mock.PropertyMock)
    @mock.patch("container_runner._Docker.run_container")
    def test_run(self, _mock_run_container, _mock_running):
        # Common expected args for the container run
        expected_args = ("test_image", "managed_container", 8080, 80)

        test_cases = [
            {
                "name": "run success",
            },
            {
                "name": "already running, skip run",
                "running": True,
                "log_message": "INFO:container_runner:Managed container already running, skipping run command.",
            },
            {
                "name": "run failure",
                "expected_exception": "Failed to start container",
            },
        ]

        for case in test_cases:
            with self.subTest(case=case["name"]):
                # Setup
                _mock_running.return_value = case.get("running", False)

                # Test execution
                if case.get("expected_exception"):
                    _mock_run_container.side_effect = Exception(case.get("expected_exception"))
                    with self.assertRaises(Exception) as e:
                        self.container_runner.run()
                    self.assertEqual(str(e.exception), case["expected_exception"])
                else:
                    if case.get("log_message"):
                        with self.assertLogs("container_runner", level="INFO") as log:
                            self.container_runner.run()
                        self.assertIn(case["log_message"], log.output)
                    else:
                        self.container_runner.run()

                # Assertions
                if case.get("running", False):
                    _mock_run_container.assert_not_called()
                else:
                    _mock_run_container.assert_called_once_with(*expected_args)

                # Reset mocks for the next test case
                _mock_run_container.reset_mock()

    @mock.patch("container_runner.ContainerRunner.running", new_callable=mock.PropertyMock)
    @mock.patch("container_runner._Docker.stop_container")
    @mock.patch("container_runner._Docker.remove_container")
    @mock.patch("container_runner._Docker.run_container")
    def test_configure(
        self, _mock_run_container, _mock_remove_container, _mock_stop_container, _mock_running
    ):
        # Common variables
        container_name = "managed_container"
        image_name = "test_image"
        env_vars = {"ENV_VAR": "value"}

        test_cases = [
            {
                "name": "configure success",
                "expected_run_call": True,
            },
            {
                "name": "stop failure",
                "stop_side_effect": Exception("Failed to stop container"),
                "expected_exception": "Failed to stop container",
                "expected_remove_call": False,
                "expected_run_call": False,
            },
            {
                "name": "remove failure",
                "remove_side_effect": Exception("Failed to remove container"),
                "expected_exception": "Failed to remove container",
                "expected_run_call": False,
            },
            {
                "name": "re-run failure",
                "run_side_effect": Exception("Failed to re-run container"),
                "expected_exception": "Failed to re-run container",
            },
            {
                "name": "not running, no stop or remove",
                "running": False,
                "expected_stop_call": False,
                "expected_remove_call": False,
            },
        ]

        for case in test_cases:
            with self.subTest(case=case["name"]):
                # Setup
                _mock_running.return_value = case.get("running", True)
                _mock_stop_container.side_effect = case.get("stop_side_effect")
                _mock_remove_container.side_effect = case.get("remove_side_effect")
                _mock_run_container.side_effect = case.get("run_side_effect")

                # Test execution
                if case.get("expected_exception"):
                    with self.assertRaises(Exception) as e:
                        self.container_runner.configure(env_vars=env_vars)
                    self.assertEqual(str(e.exception), case["expected_exception"])
                else:
                    self.container_runner.configure(env_vars=env_vars)

                # Assertions for stop_container
                if case.get("expected_stop_call", True):
                    _mock_stop_container.assert_called_once_with(container_name)
                else:
                    _mock_stop_container.assert_not_called()

                # Assertions for remove_container
                if case.get("expected_remove_call", True):
                    _mock_remove_container.assert_called_once_with(container_name)
                else:
                    _mock_remove_container.assert_not_called()

                # Assertions for run_container
                if case.get("expected_run_call", True):
                    _mock_run_container.assert_called_once_with(
                        image_name, container_name, 8080, 80, env_vars
                    )
                else:
                    _mock_run_container.assert_not_called()

                # Reset mocks for the next test case
                _mock_stop_container.reset_mock()
                _mock_remove_container.reset_mock()
                _mock_run_container.reset_mock()

    @mock.patch("container_runner._Docker._run_command")
    def test_installed(self, _mock_run_command):
        # Common variables
        image_name = "test_image"
        watchtower_image = "containrrr/watchtower"

        test_cases = [
            {
                "name": "installed success",
                "run_command_side_effect": ["managed_image_details", "watchtower_image_details"],
                "expected_installed": True,
                "expected_calls": [
                    mock.call("inspect", [image_name]),
                    mock.call("inspect", [watchtower_image]),
                ],
            },
            {
                "name": "installed failure inspection",
                "run_command_side_effect": Exception("Failed to inspect image"),
                "expected_calls": [mock.call("inspect", [image_name])],
            },
            {
                "name": "installed partial failure",
                "run_command_side_effect": ["managed_image_details", None],
                "expected_calls": [
                    mock.call("inspect", [image_name]),
                    mock.call("inspect", [watchtower_image]),
                ],
            },
        ]

        for case in test_cases:
            with self.subTest(case=case["name"]):
                # Setup
                _mock_run_command.side_effect = case["run_command_side_effect"]

                # Test execution
                self.assertEqual(
                    self.container_runner.installed, case.get("expected_installed", False)
                )

                # Assertions
                _mock_run_command.assert_has_calls(case["expected_calls"])

                # Reset mock for the next test case
                _mock_run_command.reset_mock()

    @mock.patch("container_runner._Docker._run_command")
    def test_running(self, _mock_run_command):
        # Common variables
        managed_container = "managed_container"
        watchtower_container = "watchtower"
        inspect_format = ["-f", "{{.State.Running}}"]

        test_cases = [
            {
                "name": "running success",
                "run_command_side_effect": ["true", "true"],
                "expected_running": True,
                "expected_calls": [
                    mock.call("inspect", inspect_format + [watchtower_container]),
                    mock.call("inspect", inspect_format + [managed_container]),
                ],
            },
            {
                "name": "running failure inspection",
                "run_command_side_effect": Exception("Failed to inspect container"),
                "expected_calls": [
                    mock.call("inspect", inspect_format + [watchtower_container]),
                ],
            },
            {
                "name": "running partial failure",
                "run_command_side_effect": ["true", "false"],
                "expected_calls": [
                    mock.call("inspect", inspect_format + [watchtower_container]),
                    mock.call("inspect", inspect_format + [managed_container]),
                ],
            },
        ]

        for case in test_cases:
            with self.subTest(case=case["name"]):
                # Setup
                _mock_run_command.side_effect = case["run_command_side_effect"]

                # Test execution
                self.assertEqual(
                    self.container_runner.running, case.get("expected_running", False)
                )

                # Assertions
                _mock_run_command.assert_has_calls(case["expected_calls"])

                # Reset mock for the next test case
                _mock_run_command.reset_mock()


@mock.patch("pathlib.Path.write_text")
@mock.patch("pathlib.Path.mkdir")
def test_try_set_proxy_settings(self, mock_mkdir, mock_write_text):
    http_proxy = "http://proxy.example.com:8080"
    https_proxy = "https://proxy.example.com:8443"

    test_cases = [
        {
            "name": "set both proxies",
            "http_proxy": http_proxy,
            "https_proxy": https_proxy,
        },
        {
            "name": "set http proxy",
            "http_proxy": http_proxy,
        },
        {
            "name": "set https proxy",
            "https_proxy": https_proxy,
        },
        {
            "name": "no proxies provided",
        },
    ]

    for case in test_cases:
        with self.subTest(case=case["name"]):
            # Use default values if not specified in the test case
            http_proxy = case.get("http_proxy")
            https_proxy = case.get("https_proxy")

            # Generate the expected configuration based on the proxies provided
            proxy_config = {}
            if http_proxy:
                proxy_config["http-proxy"] = http_proxy
            if https_proxy:
                proxy_config["https-proxy"] = https_proxy
            expected_config = {}
            if proxy_config:
                expected_config["proxies"] = proxy_config

            # Mock the environment variables
            env_vars = {}
            if http_proxy:
                env_vars["JUJU_CHARM_HTTP_PROXY"] = http_proxy
            if https_proxy:
                env_vars["JUJU_CHARM_HTTPS_PROXY"] = https_proxy

            # Reset mocks for each test case
            mock_mkdir.reset_mock()
            mock_write_text.reset_mock()

            # Run the test case
            with mock.patch.dict(os.environ, env_vars, clear=True):

                # Call the method
                _try_set_proxy_settings()
                # Run assertions
                self.assertEqual(os.environ.get("HTTP_PROXY"), case.get("http_proxy"))
                self.assertEqual(os.environ.get("HTTPS_PROXY"), case.get("https_proxy"))

                # Assertions
                mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
                mock_write_text.assert_called_once_with(
                    json.dumps(expected_config, indent=2), encoding="utf-8"
                )
