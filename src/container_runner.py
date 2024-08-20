"""Control a OCI image running via Docker on a host system. Provides a ContainerRunner class."""

import logging
import subprocess
import time
from typing import Iterable, Optional

from charms.operator_libs_linux.v1 import snap

logger = logging.getLogger(__name__)


class _Docker:
    """Private class for handling the installed Docker snap."""

    @property
    def _docker(self):
        """Return a representation of the Docker snap."""
        cache = snap.SnapCache()
        return cache["docker"]

    def install(self):
        # Install Docker
        try:
            self._docker.ensure(snap.SnapState.Latest, channel="stable")
            snap.hold_refresh()
            self._wait_for_docker()
        except snap.SnapError as e:
            logger.error("could not install docker. Reason: %s", e.message)
            logger.debug(e, exc_info=True)
            raise e

    def _wait_for_docker(self, retries: int = 10, delay: int = 3):
        """Wait for Docker daemon to be ready."""
        for _ in range(retries):
            try:
                subprocess.check_output(["docker", "info"], universal_newlines=True)
                logger.info("Docker daemon is ready")
                return
            except subprocess.CalledProcessError:
                logger.warning("Docker daemon is not ready, retrying...")
                time.sleep(delay)
        raise Exception("Docker daemon did not become ready in time")

    def _run_command(self, command: str, args: Optional[Iterable[str]] = None) -> str:
        args = args or []
        _cmd = ["docker", command, *args]

        try:
            output = subprocess.check_output(_cmd, universal_newlines=True)
            logger.info("Docker command succeeded: %s", _cmd)
            return output
        except subprocess.CalledProcessError as e:
            logger.error("Docker command failed: %s", _cmd)
            logger.error("Error output: %s", e.output)
            raise

    def pull_image(self, image: str):
        """Pull a Docker image."""
        return self._run_command("pull", [image])

    def run_watchtower(self, container_name: str, monitored_container: str):
        """Run Watchtower to monitor a container."""
        docker_args = [
            "-d",
            "--name",
            "watchtower",
            "--restart",
            "unless-stopped",
            "-v",
            "/var/run/docker.sock:/var/run/docker.sock",
            "containrrr/watchtower",
        ]
        return self._run_command("run", docker_args)

    def run_container(self, image: str, container_name: str):
        """Run a container with Docker."""
        docker_args = ["-d", "--name", container_name, image]
        return self._run_command("run", docker_args)


class ContainerRunner:
    """Class representing a managed container running on a host system."""

    def __init__(self):
        self._docker = _Docker()
        self._ratings_image = "ghcr.io/ubuntu/app-center-ratings:sha-69fd697"
        self._ratings_container = "my-ratings-container"
        self._watchtower_container = "my-watchtower-container"

    def install(self):
        """Install the Docker snap package and run the OCI image."""
        # Install the Docker Snap
        self._docker.install()

        # Pull the Ratings image
        try:
            self._docker.pull_image(self._ratings_image)
            logger.info("Successfully pulled ratings image: %s", self._ratings_image)
        except Exception as e:
            logger.error("Failed to pull ratings image: %s", e)
            raise

        # Run the Ratings container
        try:
            self._docker.run_container(self._ratings_image, self._ratings_container)
            logger.info("Successfully started Ratings container: %s", self._ratings_container)
        except Exception as e:
            logger.error("Failed to start Ratings container: %s", e)
            raise

        # Run Watchtower to monitor the Ratings container
        try:
            self._docker.run_watchtower(self._watchtower_container, self._ratings_container)
            logger.info("Successfully started Watchtower to monitor: %s", self._ratings_container)
        except Exception as e:
            logger.error("Failed to start Watchtower: %s", e)
            raise

    # env_vars = {
    # "jwt_secret": "your_jwt_secret",
    # "log_level": "DEBUG",
    # "postgres_uri": "postgresql://localhost/db",
    # "migration_postgres_uri": "postgresql://localhost/migration_db",
    # "env": "production"
    # }

    ## Old functions
    # def configure(self, env_vars=None):
    #     """Configure Ratings on the host system with arbitrary environment variables."""
    #     if env_vars:
    #         for key, value in env_vars.items():
    #             if value:  # Only set if the value is not None
    #                 self._ratings.set({f"app-{key.replace('_', '-')}".lower(): value})

    #     # Restart the snap service
    #     self._ratings.restart()

    # @property
    # def installed(self):
    #     """Report if the Ratings snap is installed."""
    #     return self._ratings.present

    # @property
    # def running(self):
    #     """Report if the 'ratings-svc' snap service is running."""
    #     return self._ratings.services["ratings-svc"]["active"]

    # @property
    # def _ratings(self):
    #     """Return a representation of the Ratings snap."""
    #     cache = snap.SnapCache()
    #     return cache["ratings"]
