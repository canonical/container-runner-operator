import unittest
from unittest import mock
from unittest.mock import patch

from charm import ContainerRunnerCharm
from charms.data_platform_libs.v0.data_interfaces import DatabaseCreatedEvent
from ops.model import ActiveStatus, MaintenanceStatus, WaitingStatus
from ops.testing import Harness


class MockDatabaseEvent:
    def __init__(self, id, name="database"):
        self.name = name
        self.id = id


DB_RELATION_DATA = {
    "database": "managed_container",
    "endpoints": "postgres:5432",
    "password": "password",
    "username": "username",
    "version": "14.8",
}


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(ContainerRunnerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    @mock.patch("charm.ContainerRunner.install")
    def test_on_install(self, _install):
        # Setup the handler
        self.harness.charm.on.install.emit()
        # Run the assertions
        self.assertEqual(
            self.harness.charm.unit.status,
            MaintenanceStatus("Installation complete, waiting for database."),
        )
        _install.assert_called_once()

    @mock.patch("charm.ContainerRunner.configure")
    @mock.patch("charm.ContainerRunner.run")
    def test_on_start(self, _run, _configure):
        test_cases = [
            {
                "name": "started with no configuration",
            },
            {
                "name": "started with configuration",
                "env_vars": {"FOO": "foo", "BAR": "bar", "FIZZ": None},
            },
            {
                "name": "started when waiting for database",
                "waiting_for_db": True,
            },
        ]
        for case in test_cases:
            with self.subTest(case=case["name"]):
                # Test setup
                env_vars = case.get("env_vars", {})
                self.harness.charm._env_vars = env_vars
                waiting_for_db = case.get("waiting_for_db", False)
                self.harness.charm._waiting_for_database_relation = waiting_for_db
                expected_status = (
                    WaitingStatus("Waiting for database relation")
                    if waiting_for_db
                    else ActiveStatus()
                )

                # Emit the start event
                self.harness.charm.on.start.emit()

                # Assertions
                self.assertEqual(self.harness.charm.unit.status, expected_status)
                if waiting_for_db:
                    _run.assert_not_called()
                    _configure.assert_not_called()
                else:
                    _run.assert_called_once()
                    _configure.assert_called_once_with(env_vars)

                # Reset mock calls for the next test case
                _run.reset_mock()
                _configure.reset_mock()

    @mock.patch("charm.ContainerRunnerCharm._load_env_file")
    @mock.patch("charm.ContainerRunner.configure")
    def test_on_config_changed(self, _configure, _load_env_file):
        test_cases = [
            {
                "name": "no secrets, no env vars, not waiting for db",
            },
            {
                "name": "no secrets, no env vars, waiting for db",
                "waiting_for_db": True,
            },
            {
                "name": "secrets provided, no env vars, not waiting for db",
                "secrets": {"Foo": "foo", "Bar": "bar"},
            },
            {
                "name": "env vars provided, no secrets, not waiting for db",
                "env_vars": {"FOO": "foo", "BAR": "bar", "FIZZ": None},
            },
            {
                "name": "both secrets and env vars provided, not waiting for db",
                "secrets": {"Foo": "foo"},
                "env_vars": {"BAR": "bar", "FIZZ": None},
            },
        ]
        for case in test_cases:
            with self.subTest(case=case["name"]):
                # Test setup
                self.harness.charm._env_vars = {}

                env_vars = case.get("env_vars", {})
                secrets = case.get("secrets", {})
                combined = {**secrets, **env_vars}
                waiting_for_db = case.get("waiting_for_db", False)
                should_skip = combined == self.harness.charm._env_vars or waiting_for_db

                _load_env_file.return_value = combined

                self.harness.charm._waiting_for_database_relation = waiting_for_db

                if combined == env_vars:
                    expected_status = ActiveStatus()
                elif waiting_for_db:
                    expected_status = WaitingStatus("Waiting for database relation")
                else:
                    expected_status = ActiveStatus()

                if secrets:
                    secret_string = "\n".join(f"{key}={value}" for key, value in secrets.items())
                    secret = self.harness.model.unit.add_secret({"env-vars": secret_string})
                    self.harness.update_config(
                        {"env-vars": secret._canonicalize_id(str(secret.id))}
                    )

                # Emit the config changed event
                self.harness.charm.on.config_changed.emit()

                # Run assertions
                self.assertEqual(self.harness.charm.unit.status, expected_status)
                if should_skip:
                    _configure.assert_not_called()
                else:
                    expected_config = {**secrets, **env_vars}
                    _configure.assert_called_with(expected_config)

                # Reset the mock for the next test case
                _configure.reset_mock()

    def test_managed_container_db_connection_string_no_relation(self):
        self.assertEqual(self.harness.charm._db_connection_string(), "")

    @patch("charm.DatabaseRequires.fetch_relation_data", lambda x: {0: DB_RELATION_DATA})
    def test_managed_container_db_connection_string(self):
        self.harness.add_relation("database", "postgresql", unit_data=DB_RELATION_DATA)
        expected = "postgresql://username:password@postgres:5432/ratings"
        self.assertEqual(self.harness.charm._db_connection_string(), expected)

    @mock.patch("charm.ContainerRunnerCharm._update_service_config")
    def test_on_database_created(self, _update):
        # Create a mock DatabaseCreatedEvent
        mock_event = mock.MagicMock(spec=DatabaseCreatedEvent)

        # Simulate database created event
        self.harness.charm._on_database_created(mock_event)

        # Check _update_service_config was called
        _update.assert_called_once()

    @patch("charm.ContainerRunnerCharm._update_service_config")
    @patch("charm.DatabaseRequires.is_resource_created", lambda x: True)
    def test_created_database(self, _update):
        rel_id = self.harness.add_relation("database", "postgresql", unit_data=DB_RELATION_DATA)
        self.harness.charm._database.on.database_created.emit(MockDatabaseEvent(id=rel_id))

        _update.assert_called_once()

    @patch("charm.ContainerRunnerCharm._db_connection_string", return_value="bar")
    @mock.patch("charm.ContainerRunner.configure")
    def test_update_service_config(self, _conf, _db_string):
        # Set env and log-level
        self.harness.update_config({"host-port": 1234, "container-port": 4321})

        # If no relation, wait on relation
        self.harness.charm._update_service_config()
        self.assertEqual(
            self.harness.charm.unit.status, WaitingStatus("Waiting for database relation")
        )

        # If the relation is set, open the ports and restart the service
        self.harness.add_relation("database", "postgresql", unit_data=DB_RELATION_DATA)
        self.harness.charm._update_service_config()

        # Connection string retrieved
        _db_string.assert_called_once()

        # Configure is called with the correct values
        _conf.assert_called_with({"APP_POSTGRES_URI": "bar"})

        # Check the ports have been opened
        opened_ports = {(p.protocol, p.port) for p in self.harness.charm.unit.opened_ports()}
        self.assertEqual(opened_ports, {("tcp", 1234), ("tcp", 80), ("tcp", 443)})

        # Check status is active
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())
