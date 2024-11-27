import unittest

from container_runner import ContainerRunner


class TestContainerRunner(unittest.TestCase):
    """Functional tests designed to test the ContainerRunner Class isolated from the Charm lifecycle hooks."""

    def setUp(self):
        self.container_runner = ContainerRunner(
            "ghcr.io/ubuntu/app-center-ratings:sha-7f05d08", 8080, 8080, "", ""
        )
        if not self.container_runner.installed:
            self.container_runner.install()

    def test_lifecycle(self):
        self.assertTrue(self.container_runner.installed)

        self.container_runner.run()
        self.assertTrue(self.container_runner.running)

        env_vars = {"Foo": "foo", "Bar": "bar"}
        self.container_runner.configure(env_vars)

        # Check if the container is running post configuration
        self.assertTrue(self.container_runner.running)

        # Inspect the container's environment variables
        env_output = self.container_runner._docker._run_command(
            "inspect",
            ["-f", "{{json .Config.Env}}", self.container_runner._container_name],
        )
        env_vars_in_container = eval(env_output)
        for key, value in env_vars.items():
            self.assertIn(f"{key}={value}", env_vars_in_container)
