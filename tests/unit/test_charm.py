import os
import unittest
from unittest import mock
from unittest.mock import patch

from charms.data_platform_libs.v0.data_interfaces import DatabaseCreatedEvent
from ops.model import ActiveStatus, MaintenanceStatus, WaitingStatus
from ops.testing import Harness

from charm import ContainerRunnerCharm


class MockDatabaseEvent:
    def __init__(self, id, name="database"):
        self.name = name
        self.id = id


DB_RELATION_DATA = {
    "database": "ratings",
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
    def test_on_start_with_no_env_vars(self, _run, _configure):
        # Setup the handler
        self.harness.charm.on.start.emit()
        # Run the assertions
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())
        _run.assert_called_once()
        _configure.assert_called_once()

    @mock.patch("charm.ContainerRunner.configure")
    @mock.patch("charm.ContainerRunner.run")
    def test_on_start_with_env_vars(self, _run, _configure):
        # Setup the handler
        self.harness.charm._env_vars = {"FOO": "foo", "BAR": "bar", "FIZZ": None}
        self.harness.charm.on.start.emit()
        # Run the assertions
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())
        _run.assert_called_once()
        _configure.assert_called_once_with({"FOO": "foo", "BAR": "bar", "FIZZ": None})

    @mock.patch("charm.ContainerRunner.configure")
    def test_on_config_changed_no_env_vars(self, _configure):
        # Setup the handler
        self.harness.charm.on.config_changed.emit()
        # Run the assertions
        _configure.assert_called_once()
        self.assertEqual(
            self.harness.charm.unit.status,
            ActiveStatus(),
        )

    @mock.patch("charm.ContainerRunner.configure")
    def test_on_config_changed_with_secret_env_vars(self, _configure):
        # Setup the handler
        secret = """
        Foo=foo
        Bar=bar
        """
        secret = self.harness.model.unit.add_secret({"env-vars": secret})
        # self.harness.grant_secret(secret_id, self.harness._unit_name)
        self.harness.update_config({"env-vars": secret._canonicalize_id(str(secret.id))})
        self.harness.charm.on.config_changed.emit()
        # Run the assertions
        self.assertEqual(
            self.harness.charm.unit.status,
            ActiveStatus(),
        )

        _configure.assert_called_with({"Foo": "foo", "Bar": "bar"})

    def test_ratings_db_connection_string_no_relation(self):
        self.assertEqual(self.harness.charm._db_connection_string(), "")

    @patch("charm.DatabaseRequires.fetch_relation_data", lambda x: {0: DB_RELATION_DATA})
    def test_ratings_db_connection_string(self):
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
    def test_ratings_database_created_database_success(self, _update):
        rel_id = self.harness.add_relation("database", "postgresql", unit_data=DB_RELATION_DATA)
        self.harness.charm._database.on.database_created.emit(MockDatabaseEvent(id=rel_id))

        _update.assert_called_once()

    @patch("charm.ContainerRunnerCharm._set_proxy")
    @patch("charm.ContainerRunnerCharm._db_connection_string", return_value="bar")
    @mock.patch("charm.ContainerRunner.configure")
    def test_update_service_config(self, _conf, _db_string, _proxy):
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

        # Proxy set
        _proxy.assert_called_once()

        # Configure is called with the correct values
        _conf.assert_called_with({"APP_POSTGRES_URI": "bar"})

        # Check the ports have been opened
        opened_ports = {(p.protocol, p.port) for p in self.harness.charm.unit.opened_ports()}
        self.assertEqual(opened_ports, {("tcp", 1234)})

        # Check status is active
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @mock.patch.dict(os.environ, {"JUJU_CHARM_HTTP_PROXY": "http://example.com:3128"}, clear=True)
    def test_set_proxy(self):
        # Call the method
        self.harness.charm._set_proxy()

        # Assert that the environment variables were set
        self.assertEqual(os.environ["HTTP_PROXY"], "http://example.com:3128")
        self.assertEqual(os.environ["HTTPS_PROXY"], "http://example.com:3128")

        with mock.patch.dict(os.environ, {}, clear=True):
            self.harness.charm._set_proxy()

            # Assert that the environment variables were not set
            self.assertNotIn("HTTP_PROXY", os.environ)
            self.assertNotIn("HTTPS_PROXY", os.environ)
