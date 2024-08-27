#!/usr/bin/env python3
# Copyright 2023 Canonical
# See LICENSE file for licensing details.

"""Ubuntu Software Centre ratings service.

A backend service to support application ratings in the new Ubuntu Software Centre.
"""
import logging
import os
from io import StringIO

import ops
from charms.data_platform_libs.v0.data_interfaces import DatabaseCreatedEvent, DatabaseRequires
from container_runner import ContainerRunner
from dotenv import dotenv_values
from ops.model import ActiveStatus, MaintenanceStatus

logger = logging.getLogger(__name__)


class ContainerRunnerCharm(ops.CharmBase):
    """Main operator class for ratings service."""

    def __init__(self, *args):
        super().__init__(*args)
        self._container_runner = ContainerRunner()

        # Initialise the integration with PostgreSQL
        self._database = DatabaseRequires(self, relation_name="database", database_name="ratings")

        # Observe common Juju events
        self.framework.observe(self._database.on.database_created, self._on_database_created)
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)
        self.framework.observe(self.on.config_changed, self._on_config_changed)

        # Attempt to load the env file
        self._env_vars = self._load_env_file()

    def _on_config_changed(self, _):
        """Update the env vars and restart the OCI container."""
        self._env_vars = self._load_env_file()
        try:
            logger.info("Updating and resuming snap service for Ratings.")
            if self._env_vars:
                self._container_runner.configure(self._env_vars)
            # self.unit.open_port(protocol="tcp", port=PORT)
            self.unit.status = ops.ActiveStatus()
            logger.info("Ratings service started successfully.")
        except Exception as e:
            logger.error(f"Failed to start Ratings service: {str(e)}")
            self.unit.status = ops.BlockedStatus(f"Failed to start Ratings service: {str(e)}")

    def _load_env_file(self):
        """Attempt to load and validate the .env files from resources and secrets."""
        env_file_path = None
        env_vars = {}

        # Load env vars from Juju resource
        try:
            env_file_path = self.model.resources.fetch('env-file')
            env_vars = dotenv_values(env_file_path)
            if not env_vars:
                raise ValueError("The .env file is empty or has invalid formatting.")
            logging.info(".env file loaded successfully.")
        except Exception as e:
            logging.info(f"Failed to load env vars resource: {e}")
        try:
            secret_env_vars = self._get_secret_content(self.config.get("env-vars"))
            if secret_env_vars:
                env_vars.update(secret_env_vars)
                logging.info(f"Loaded secret env vars: {env_vars}")
        except Exception as e:
            logging.info(f"Failed to load secret env vars: {e}")

        return env_vars

    def _on_start(self, _):
        """Start Ratings."""
        logger.info("Start hook called")
        self._container_runner.run()

        try:
            logger.info("Updating and resuming snap service for Ratings.")
            if self._env_vars:
                self._container_runner.configure(self._env_vars)
            # self.unit.open_port(protocol="tcp", port=PORT)
            self.unit.status = ops.ActiveStatus()
            logger.info("Ratings service started successfully.")
        except Exception as e:
            logger.error(f"Failed to start Ratings service: {str(e)}")
            self.unit.status = ops.BlockedStatus(f"Failed to start Ratings service: {str(e)}")

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
            logger.error(f"Failed to install Ratings via snap: {e}")
            self.unit.status = ops.BlockedStatus(str(e))

    def _get_secret_content(self, secret_id):
        """Get the content of a Juju secret."""
        try:
            secret = self.model.get_secret(id=secret_id)
            env_var_buffer = secret.get_content(refresh=True)["env-vars"]
            env_vars = dotenv_values(stream=StringIO(env_var_buffer))
            return env_vars
        except ops.SecretNotFoundError:
            logger.error(f"secret {secret_id!r} not found.")
            raise

    def _on_database_created(self, _: DatabaseCreatedEvent):
        """Handle the database creation event."""
        logger.info("Database created event triggered.")
        self._update_service_config()

    def _update_service_config(self):
        """Update the service config and restart Ratings."""
        logger.info("Updating config and resterting Ratings.")

        if self.model.get_relation("database") is None:
            logger.warning("No database relation found. Waiting.")
            self.unit.status = ops.WaitingStatus("Waiting for database relation")
            return

        self.unit.status = ops.MaintenanceStatus("Attempting to update Ratings config.")
        # Get connection string from Juju relation to db
        connection_string = self._db_connection_string()

        # Ensure squid proxy
        self._set_proxy()
        self._env_vars.update({"DB_CONNECTION_STRING": connection_string})
        try:
            self._container_runner.configure(self._env_vars)
        except Exception as e:
            self.unit.status = ops.BlockedStatus(f"Failed to start configure container runner: {str(e)}")
        self.unit.open_port(protocol="tcp", port=443)
        self.unit.status = ops.ActiveStatus()

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
            # FIXME: We contruct the db connection aware of ratings, pass on the parts in future
            connection_string = f"postgres://{username}:{password}@{endpoints}/ratings"
            logger.info(f"Generated database connection string with endpoints: {endpoints}.")
            return connection_string
        else:
            logger.warning("Missing database relation data. Cannot generate connection string.")
            return ""

    def _set_proxy(self):
        """Set Squid proxy environment variables if configured."""
        proxy_url = os.environ.get("JUJU_CHARM_HTTP_PROXY")
        if proxy_url:
            os.environ["HTTP_PROXY"] = proxy_url
            os.environ["HTTPS_PROXY"] = proxy_url


if __name__ == "__main__":  # pragma: nocover
    ops.main(ContainerRunnerCharm)
