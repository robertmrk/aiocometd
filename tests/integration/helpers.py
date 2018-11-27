import time
from urllib.request import urlopen
from http import HTTPStatus
from contextlib import suppress

import docker


class DockerContainer:
    def __init__(self, image_name, name, container_port, host_port):
        self.image_name = image_name
        self.name = name
        self.contaner_port = container_port
        self.host_port = host_port
        self._container = None
        self.client = docker.from_env()
        self._ensure_exists()

    def _ensure_exists(self):
        filter = {
            "name": self.name,
            "ancestor": self.image_name
        }
        results = self.client.containers.list(all=True, filters=filter)
        if not results:
            self._container = self.client.containers.run(
                name=self.name,
                image=self.image_name,
                ports={f"{self.contaner_port}/tcp": self.host_port},
                detach=True
            )
        else:
            self._container = results[0]

    def _wait_for_state(self, state):
        while self._container.status != state:
            time.sleep(1)
            self._container.reload()

    def _ensure_running(self):
        self._ensure_exists()

        if self._container.status != "running":
            if self._container.status == "exited":
                self._container.start()
            if self._container.status == "paused":
                self._container.unpause()

            self._wait_for_state("running")

    def _get_url(self):
        return f"http://localhost:{self.host_port}"

    def ensure_reacheable(self):
        self._ensure_running()
        url = self._get_url()

        status = None
        with suppress(Exception):
            status = urlopen(url).status
        while status != HTTPStatus.OK:
            time.sleep(1)
            with suppress(Exception):
                status = urlopen(url).status

        return url

    def stop(self):
        self._container.stop()
        self._wait_for_state("exited")

    def pause(self):
        self._container.pause()
        self._wait_for_state("paused")
