#!/usr/bin/env python3
# Copyright 2023 Canonical
# See LICENSE file for licensing details.

"""Container Runner Charm.

Charm for deploying and managing OCI images and their database relations.
"""
import logging
from io import StringIO
import ops

from charms.data_platform_libs.v0.data_interfaces import DatabaseCreatedEvent, DatabaseRequires
from container_runner import ContainerRunner
from dotenv import dotenv_values
from ops.model import ActiveStatus, MaintenanceStatus
from typing import Dict

logger = logging.getLogger(__name__)

# A config value can be none, but that only happens if you are requesting an undefined key.
_ConfigValue = bool | int | float | str | None


def _cast_config_to_bool(config_value: _ConfigValue) -> bool:
    """Casts the Juju config value type to an int."""
    if isinstance(config_value, bool):
        return config_value
    else:
        raise ValueError(f"Config value is not a bool: {config_value}")


def _cast_config_to_int(config_value: _ConfigValue) -> int:
    """Casts the Juju config value type to an int."""
    if isinstance(config_value, int):
        return config_value
    else:
        raise ValueError(f"Config value is not an int: {config_value}")


def _cast_config_to_string(config_value: _ConfigValue) -> str:
    """Casts the Juju config value type to a str."""
    if isinstance(config_value, str):
        return config_value
    else:
        raise ValueError(f"Config value is not an int: {config_value}")


class ContainerRunnerCharm(ops.CharmBase):
    """Main operator class for Container Runner charm."""

    def __init__(self, *args):
        super().__init__(*args)

        container_image = _cast_config_to_string(self.config.get("container-image-uri"))
        container_port = _cast_config_to_int(self.config.get("container-port"))
        host_port = _cast_config_to_int(self.config.get("host-port"))
        self._container_runner = ContainerRunner(container_image, container_port, host_port)

        # Initialise the integration with PostgreSQL. Currently hardcoded to ratings
        # TODO: add database name as config, use that to tell if we expect a db + makes this generic
        self._database = DatabaseRequires(self, relation_name="database", database_name="ratings")

        # Observe common Juju events
        # TODO: Do we want to use all these hooks? Or would it be better to use just _on_config?
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self._database.on.database_created, self._on_database_created)

        # Attempt to load the env file
        # Initialise to an empty dict as this is mutated over time as hooks are fired.
        self._env_vars = {}

        self._env_vars = self._load_env_file()

        # Track state of charm
        # TODO: remove (see above)
        database_available = self.model.get_relation("database") is not None
        if database_available:
            self._update_service_config()
        else:
            self._waiting_for_database_relation = (
                _cast_config_to_bool(self.config.get("database-expected"))
                and not database_available
            )

    def _on_config_changed(self, _):
        """Update the env vars and restart the OCI container."""
        # TODO: hook into the event and log what actually changed based on the event.
        self.unit.status = ops.MaintenanceStatus("Attempting to update config")
        # Load env vars
        self._env_vars = self._load_env_file()
        # Load ports from Charm config
        # TODO: write some tests to poke at what happens if we want to override / remove config
        container_image = _cast_config_to_string(self.config.get("container-image-uri"))
        container_port = _cast_config_to_int(self.config.get("container-port"))
        host_port = _cast_config_to_int(self.config.get("host-port"))
        # Set ports to be used when running the container in the ContainerRunner
        self._container_runner.set_ports(container_port, host_port)
        # Set the container image the runner will manage
        self._container_runner.set_container_image(container_image)
        if self._waiting_for_database_relation:
            self.unit.status = ops.WaitingStatus("Waiting for database relation")
            return
        try:
            logger.info("Updating and resuming snap service for Container Runner.")
            self._container_runner.configure(self._env_vars)
            self.unit.open_port(protocol="tcp", port=host_port)
            self.unit.status = ops.ActiveStatus()
            logger.info("Container Runner service started successfully.")
        except Exception as e:
            logger.error(f"Failed to start Container Runner: {str(e)}")
            self.unit.status = ops.BlockedStatus(f"Failed to start Container Runner: {str(e)}")

    def _load_env_file(self) -> Dict[str, str]:
        """Attempt to load and validate the .env files from resources and secrets and append to the existing env_vars dict."""
        env_file_path = None
        env_vars = self._env_vars

        # Load env vars from Juju resource
        try:
            # Get .env file
            env_file_path = self.model.resources.fetch("env-file")
            # Filter out environment variables with values set to None (see dotenv_values docs for why).
            filtered_env_vars: Dict[str, str] = {
                key: value
                for key, value in dotenv_values(env_file_path).items()
                if value is not None
            }
            env_vars.update(filtered_env_vars)
            if not env_vars:
                raise ValueError("The .env file is empty or has invalid formatting.")
            logging.info(".env file loaded successfully.")
        except Exception as e:
            logging.info(f"Failed to load env vars resource: {e}")
        try:
            secret_env_vars = self._get_secret_content(self.config.get("env-vars"))
            if secret_env_vars:
                env_vars.update(secret_env_vars)
                logging.debug("Secret env-vars successfully loaded")
        except Exception as e:
            logging.info(f"Failed to load secret env vars: {e}")

        return env_vars

    def _on_start(self, _):
        """Start Container Runner."""
        if self._waiting_for_database_relation:
            self.unit.status = ops.WaitingStatus("Waiting for database relation")
            return

        if not self._container_runner.running:
            self._container_runner.run()

        try:
            logger.info("Updating and resuming snap service for Container Runner.")
            self._container_runner.configure(self._env_vars)
            # self.unit.open_port(protocol="tcp", port=PORT)
            self.unit.status = ops.ActiveStatus()
            logger.info("Container Runner started successfully.")
        except Exception as e:
            logger.error(f"Failed to start Container Runner: {str(e)}")
            self.unit.status = ops.BlockedStatus(f"Failed to start Container Runner: {str(e)}")

    def _on_upgrade_charm(self, _):
        """Ensure the snap is refreshed (in channel) if there are new revisions."""
        self.unit.status = ops.MaintenanceStatus("upgrade hook called")

    def _on_install(self, _):
        """Install prerequisites for the application."""
        self.unit.status = MaintenanceStatus("Installing Container Runner")

        try:
            self._container_runner.install()
            self.unit.status = MaintenanceStatus("Installation complete, waiting for database.")
        except Exception as e:
            logger.error(f"Failed to install Container Runner via snap: {e}")
            self.unit.status = ops.BlockedStatus(str(e))

    def _get_secret_content(self, secret_id) -> Dict[str, str]:
        """Get the content of a Juju secret."""
        try:
            secret = self.model.get_secret(id=secret_id)
            env_var_buffer = secret.get_content(refresh=True)["env-vars"]
            # Filter out environment variables with values set to None (see dotenv_values docs for why).
            filtered_secret_env_vars: Dict[str, str] = {
                key: value
                for key, value in dotenv_values(stream=StringIO(env_var_buffer)).items()
                if value is not None
            }
            return filtered_secret_env_vars
        except ops.SecretNotFoundError:
            logger.error(f"secret {secret_id!r} not found.")
            raise

    def _on_database_created(self, _: DatabaseCreatedEvent):
        """Handle the database creation event."""
        logger.info("Database created event triggered.")
        self._update_service_config()

    def _update_service_config(self):
        """Update the service config and restart Container Runner."""
        # TODO: if a db is related, and the charm crashed, is the database_created event fired off again?
        # TODO: Move this to a separate field and not shared with env_vars so we can wipe env_vars each time and preserve the connection string.
        logger.info("Updating config and resterting Container Runner.")
        if self.model.get_relation("database") is None:
            logger.warning("No database relation found. Waiting.")
            self.unit.status = ops.WaitingStatus("Waiting for database relation")
            return

        self.unit.status = ops.MaintenanceStatus("Attempting to update Container Runner config.")
        # Get connection string from Juju relation to db
        connection_string = self._db_connection_string()

        self._env_vars.update({"APP_POSTGRES_URI": connection_string})
        self._waiting_for_database_relation = False
        logger.debug(
            f"_waiting_for_database_relation updated to {self._waiting_for_database_relation}"
        )

        try:
            self._container_runner.configure(self._env_vars)
        except Exception as e:
            self.unit.status = ops.BlockedStatus(
                f"Failed to start configure container runner: {str(e)}"
            )
        self.unit.open_port(protocol="tcp", port=_cast_config_to_int(self.config.get("host-port")))
        self.unit.status = ActiveStatus()

    def _db_connection_string(self) -> str:
        """Report database connection string using info from relation databag."""
        logger.info("Attempting to generate database connection string.")

        relation = self.model.get_relation("database")

        if not relation:
            logger.warning("Database relation not found. Returning empty connection string.")
            return ""
        # TODO: Assumes this is a psql db, should be more generic in the future.
        data = self._database.fetch_relation_data()[relation.id]
        username = data.get("username")
        password = data.get("password")
        endpoints = data.get("endpoints")

        if username and password and endpoints:
            # FIXME: We construct the db connection aware of ratings, pass on the parts in future
            connection_string = f"postgresql://{username}:{password}@{endpoints}/ratings"
            logger.info(f"Generated database connection string with endpoints: {endpoints}.")
            return connection_string
        else:
            logger.warning(
                f"Missing database relation data. Cannot generate connection string. Got username: {username is not None}, Got password: {password is not None}, Got endpoints: {endpoints is not None}"
            )
            logger.debug(f"Keys available in relation: {list(data.keys())}")
            return ""


if __name__ == "__main__":  # pragma: nocover
    ops.main(ContainerRunnerCharm)
