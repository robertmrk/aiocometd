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


class AuthExtension(Extension):  # pylint: disable=abstract-method
    """Extension with support for authentication"""
    async def authenticate(self):
        """Called after a failed authentication attempt

        For authentication schemes where the credentials are static it doesn't
        makes much sense to reimplement this function. However for schemes
        where the credentials can expire (like OAuth, JWT...) this method can
        be reimplemented to update those credentials
        """
