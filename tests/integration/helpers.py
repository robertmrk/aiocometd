"""Helper classes for integration tests"""
import time
from urllib.request import urlopen
from http import HTTPStatus
from contextlib import suppress

import docker


class DockerContainer:
    """Docker container encapsulation

    If the container with the given *name* doesn't exists yet it'll be created.
    """
    def __init__(self, image_name, name, container_port, host_port):
        """
        :param str image_name: A docker image name with or without a tag
        :param name: Container name
        :param container_port: TCP port exposed by the container
        :param host_port: TCP port on the host where the exposed container \
        port gets published
        """
        #: docker image name with or without a tag
        self.image_name = image_name
        #: container name
        self.name = name
        #: TCP port exposed by the container
        self.contaner_port = container_port
        #: TCP port on the host where the exposed container port gets published
        self.host_port = host_port
        #: container instance
        self._container = None
        #: docker client
        self.client = docker.from_env()

        self._ensure_exists()

    def _ensure_exists(self):
        """Create the container if it doesn't already exists"""
        # try to find the container by name and image
        filter = {
            "name": self.name,
            "ancestor": self.image_name
        }
        results = self.client.containers.list(all=True, filters=filter)

        # if it doesn't exists then create it
        if not results:
            self._container = self.client.containers.run(
                name=self.name,
                image=self.image_name,
                ports={f"{self.contaner_port}/tcp": self.host_port},
                detach=True
            )
        # if it exists assign it to the instance attribute
        else:
            self._container = results[0]

    def _wait_for_state(self, state):
        """Wait until the state of the container becomes the given *state*
        value
        """
        while self._container.status != state:
            time.sleep(1)
            self._container.reload()

    def _ensure_running(self):
        """Get the container into the ``running`` state if it's in a different
        one"""
        # make sure the container exists
        self._ensure_exists()

        # if the container is not running
        if self._container.status != "running":
            # if the container is stopped then start it
            if self._container.status == "exited":
                self._container.start()
            # if the container is paused then resume it
            if self._container.status == "paused":
                self._container.unpause()

            self._wait_for_state("running")

    def _get_url(self):
        """Return the url of the container's service"""
        return f"http://localhost:{self.host_port}"

    def ensure_reachable(self):
        """Start the container and make sure it's exposed service is reachable
        """
        # make sure the container is running
        self._ensure_running()
        url = self._get_url()

        # query the service's URL until it can be reached
        status = None
        with suppress(Exception):
            status = urlopen(url).status
        while status != HTTPStatus.OK:
            time.sleep(1)
            with suppress(Exception):
                status = urlopen(url).status

        return url

    def stop(self):
        """Stop the container"""
        self._container.stop()
        self._wait_for_state("exited")

    def pause(self):
        """Pause the container"""
        self._container.pause()
        self._wait_for_state("paused")
