"""Extension classes"""
from abc import ABC, abstractmethod


class Extension(ABC):
    """Defines operations supported by extensions"""
    @abstractmethod
    async def outgoing(self, payload, headers):
        """Process outgoing *payload* and *headers*

        Called just before a payload is sent

        :param list[dict] payload: List of outgoing messages
        :param dict headers: Headers to send
        """

    @abstractmethod
    async def incoming(self, payload, headers=None):
        """Process incoming *payload* and *headers*

        Called just after a payload is received

        :param list[dict] payload: List of incoming messages
        :param headers: Headers to send
        :type headers: dict or None
        """
