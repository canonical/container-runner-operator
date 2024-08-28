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
            result = subprocess.run(_cmd, check=True, text=True, capture_output=True)
            logger.info("Docker command succeeded: %s", _cmd)
            return result.stdout
        except subprocess.CalledProcessError as e:
            logger.error("Docker command failed: %s", _cmd)
            logger.error("Return code: %s", e.returncode)
            logger.error("Output: %s", e.stdout)
            logger.error("Error output: %s", e.stderr)
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

    def run_container(self, image: str, container_name: str, env_vars: Optional[dict] = None):
        """Run a container with Docker, optionally passing environment variables."""
        docker_args = ["-d", "--name", container_name]
        if env_vars:
            for key, value in env_vars.items():
                docker_args.extend(["-e", f"{key}={value}"])

        docker_args.append(image)
        return self._run_command("run", docker_args)

    def stop_container(self, container_name: str):
        """Stop a running container and wait for it to stop."""
        self._run_command("stop", [container_name])
        self._run_command("wait", [container_name])

    def remove_container(self, container_name: str):
        """Remove a stopped container."""
        self._run_command("rm", [container_name])


class ContainerRunner:
    """Class representing a managed container running on a host system."""

    def __init__(self):
        self._docker = _Docker()
        self._ratings_image = "ghcr.io/ubuntu/app-center-ratings:sha-69fd697"
        self._ratings_container = "my-ratings-container"
        self._watchtower_container = "my-watchtower-container"

    def run(self):
        """Run the OCI image specified in the ContainerRunner config."""
        # Run the Ratings container
        try:
            self._docker.run_container(self._ratings_image, self._ratings_container)
            logger.info("Successfully started Ratings container: %s", self._ratings_container)
        except Exception as e:
            logger.error("Failed to start Ratings container: %s", e)
            raise

    def install(self):
        """Install the Docker snap package and run the OCI image."""
        # Install the Docker Snap
        self._docker.install()
        logger.info("install docker called")

        # Run Watchtower to monitor the Ratings container
        try:
            self._docker.run_watchtower(self._watchtower_container, self._ratings_container)
            logger.info("Successfully started Watchtower to monitor: %s", self._ratings_container)
        except Exception as e:
            logger.error("Failed to start Watchtower: %s", e)
            raise

        # Pull the Ratings image
        try:
            self._docker.pull_image(self._ratings_image)
            logger.info("Successfully pulled ratings image: %s", self._ratings_image)
        except Exception as e:
            logger.error("Failed to pull ratings image: %s", e)
            raise

    def configure(self, env_vars=None):
        """Configure and restart the Ratings container with updated environment variables."""
        # Stop the current Ratings container and wait for it to fully stop
        try:
            self._docker.stop_container(self._ratings_container)
            logger.info("Successfully stopped container: %s", self._ratings_container)
        except Exception as e:
            logger.error("Failed to stop container: %s", e)
            raise

        # Remove the Ratings container and ensure it's fully removed
        try:
            self._docker.remove_container(self._ratings_container)
            logger.info("Successfully removed container: %s", self._ratings_container)
        except Exception as e:
            logger.error("Failed to remove container: %s", e)
            raise

        # Re-run the Ratings container with environment variables
        try:
            self._docker.run_container(self._ratings_image, self._ratings_container, env_vars)
            logger.info(
                "Successfully re-ran container: %s with env vars: %s",
                self._ratings_container,
                env_vars,
            )
        except Exception as e:
            logger.error("Failed to re-run container: %s", e)
            raise

    @property
    def installed(self):
        """Check if both images (ratings and watchtower) have been pulled."""
        try:
            # Inspect the images to see if they are pulled
            ratings_image_inspect = self._docker._run_command("inspect", [self._ratings_image])
            watchtower_image_inspect = self._docker._run_command(
                "inspect", ["containrrr/watchtower"]
            )
            if ratings_image_inspect and watchtower_image_inspect:
                return True
        except Exception as e:
            logger.info("Failed to inspect images locally: %s", e)

        return False

    @property
    def running(self):
        """Check if both containers (ratings and watchtower) are running."""
        try:
            # Inspect the ratings container to check if it's running
            ratings_container_inspect = self._docker._run_command(
                "inspect", ["-f", "{{.State.Running}}", self._ratings_container]
            )
            watchtower_container_inspect = self._docker._run_command(
                "inspect", ["-f", "{{.State.Running}}", "watchtower"]
            )
            if "true" in ratings_container_inspect and "true" in watchtower_container_inspect:
                return True
        except Exception as e:
            logger.info("Failed to inspect container state: %s", e)

        return False
