"""Control a OCI image running via Docker on a host system. Provides a ContainerRunner class."""

import json
from pathlib import Path
import logging
import subprocess
import time
import os
from typing import Iterable, Optional

# Configure logging level based on environment variable or default to INFO
log_level = os.getenv("LOG_LEVEL", "WARNING").upper()

# Set up the logger
logger = logging.getLogger(__name__)
logger.setLevel(log_level)

DOCKER_DAEMON_CONFIG_PATH = Path("/etc/docker/daemon.json")


class _Docker:
    """Private class for handling the installed Docker snap."""

    def install(self):
        try:
            # Set this env to automatically restart daemons. If not, the prompt is blocking.
            env = os.environ.copy()
            env["NEEDRESTART_MODE"] = "a"

            # Run apt-get update
            subprocess.run(["apt-get", "update"], check=True, env=env)

            # Install docker.io package
            subprocess.run(["apt-get", "install", "-y", "docker.io"], check=True, env=env)

            self._wait_for_docker()

        except subprocess.CalledProcessError as e:
            logger.error("could not install docker. Reason: %s", e)
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
            logger.debug("Docker command succeeded: %s", _cmd)
            return result.stdout
        except subprocess.CalledProcessError as e:
            logger.debug("Docker command failed: %s", _cmd)
            logger.warning("Return code: %s", e.returncode)
            logger.warning("Output: %s", e.stdout)
            logger.warning("Error output: %s", e.stderr)
            raise

    def pull_image(self, image: str):
        """Pull a Docker image."""
        return self._run_command("pull", [image])

    def run_watchtower(self):
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

    def run_container(
        self,
        image: str,
        container_name: str,
        host_port: int,
        container_port: int,
        env_vars: Optional[dict] = None,
    ):
        """Run a Docker container, optionally passing environment variables.

        This function handles cases where the container already exists by either restarting
        it or removing it before running a new instance.
        """
        # Check status of container
        try:
            container_status = self._run_command(
                "inspect", ["-f", "{{.State.Status}}", container_name]
            )
            if "running" in container_status:
                logger.debug(f"Container {container_name} is already running.")
                return
            if "exited" in container_status:
                logger.debug(f"Container {container_name} has exited, restarting now.")
                self._run_command("start", [container_name])
                return
            else:
                logger.debug(
                    f"Container {container_name} exists in state {container_status}. Removing it."
                )
                self.remove_container(container_name)
        except subprocess.CalledProcessError as e:
            # Container does not exist, so we can continue to create it
            if "No such object" in e.stderr:
                logger.debug(
                    f"Container {container_name} does not exist. Proceeding to create it."
                )
            else:
                logger.error(f"Unknown error returned from docker inspect call: {e}")
                raise e

        # Prepare Docker run arguments
        docker_args = ["-d", "--name", container_name, "-p", f"{host_port}:{container_port}"]
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

    def __init__(self, container_image: str, container_port: int, host_port: int):
        self._docker = _Docker()
        self._container_image = container_image
        self._container_name = "managed_container"
        self._watchtower_container = "watchtower_container"
        self._container_port = container_port
        self._host_port = host_port

    def set_docker_proxy(self, http_proxy: str, https_proxy: str):
        """Write docker proxy settings to /etc/docker/daemon.json."""
        if http_proxy == "":
            raise ValueError('http_proxy cannot be ""')
        if https_proxy == "":
            raise ValueError('https_proxy cannot be ""')
        proxy_config = {
            "http-proxy": http_proxy,
            "https-proxy": https_proxy,
        }

        daemon_config = {"proxies": proxy_config}

        DOCKER_DAEMON_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        DOCKER_DAEMON_CONFIG_PATH.write_text(json.dumps(daemon_config, indent=2), encoding="utf-8")

    def set_ports(self, container_port: int, host_port: int):
        """Set the container port and host port used when running the OCI image."""
        self._container_port = container_port
        self._host_port = host_port

    def set_container_image(self, container_image: str):
        """Set the container image that will be used when running the OCI image."""
        self._container_image = container_image
        logger.info(f"Container image updated to: {self._container_image}")

    def run(self):
        """Run the OCI image specified in the ContainerRunner config."""
        # Run the managed container
        if self.running:
            logger.info("Managed container already running, skipping run command.")
            return
        try:
            self._docker.run_container(
                self._container_image, self._container_name, self._host_port, self._container_port
            )
            logger.info("Successfully started managed container: %s", self._container_name)
        except Exception as e:
            logger.error("Failed to start managed container: %s", e)
            raise

    def install(self):
        """Install the Docker snap package and run the OCI image."""
        # Install the Docker Snap
        self._docker.install()
        logger.info("install docker called")

        # Run Watchtower to monitor the managed container
        try:
            self._docker.run_watchtower()
            logger.info("Successfully started Watchtower to monitor: %s", self._container_name)
        except Exception as e:
            logger.error("Failed to start Watchtower: %s", e)
            raise

        # Pull the managed image
        try:
            self._docker.pull_image(self._container_image)
            logger.info("Successfully pulled image: %s", self._container_image)
        except Exception as e:
            logger.error("Failed to pull image: %s", e)
            raise

    def configure(self, env_vars=None):
        """Configure and restart the managed container with updated environment variables."""
        # Stop the current managed container and wait for it to fully stop
        if self.running:
            try:
                self._docker.stop_container(self._container_name)
                logger.info("Successfully stopped container: %s", self._container_name)
            except Exception as e:
                logger.error("Failed to stop container: %s", e)
                raise

            # Remove the managed container and ensure it's fully removed
            try:
                self._docker.remove_container(self._container_name)
                logger.info("Successfully removed container: %s", self._container_name)
            except Exception as e:
                logger.error("Failed to remove container: %s", e)
                raise

        # Re-run the managed container with environment variables
        try:
            self._docker.run_container(
                self._container_image,
                self._container_name,
                self._host_port,
                self._container_port,
                env_vars,
            )
            logger.info(
                "Successfully re-ran container: %s with env vars: %s",
                self._container_name,
                env_vars,
            )
        except Exception as e:
            logger.error("Failed to re-run container: %s", e)
            raise

    @property
    def installed(self):
        """Check if both images have been pulled."""
        try:
            # Inspect the images to see if they are pulled
            managed_image_inspect = self._docker._run_command("inspect", [self._container_image])
            watchtower_image_inspect = self._docker._run_command(
                "inspect", ["containrrr/watchtower"]
            )
            if managed_image_inspect and watchtower_image_inspect:
                return True
        except Exception as e:
            logger.info("Failed to inspect images locally: %s", e)

        return False

    @property
    def managed_container_running(self) -> bool:
        """Check if the managed container is currently running."""
        try:
            # Inspect the managed container to check if it's running
            managed_container_inspect = self._docker._run_command(
                "inspect", ["-f", "{{.State.Running}}", self._container_name]
            )
            if "true" in managed_container_inspect:
                return True
        except Exception as e:
            logger.info(
                "Failed to inspect container state in managed container running check: %s", e
            )

        return False

    @property
    def watchtower_running(self) -> bool:
        """Check if the watchtower container is currently running."""
        try:
            # Inspect the watchtower container to check if it's running
            watchtower_container_inspect = self._docker._run_command(
                "inspect", ["-f", "{{.State.Running}}", "watchtower"]
            )
            if "true" in watchtower_container_inspect:
                return True
        except Exception as e:
            logger.info(
                "Failed to inspect container state in watchtower container running check: %s", e
            )

        return False

    @property
    def running(self) -> bool:
        """Check if both containers are running."""
        return self.watchtower_running and self.managed_container_running
