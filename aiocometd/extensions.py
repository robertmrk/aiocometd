"""Extension classes"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional

from .utils import JsonObject


class Extension(ABC):
    """Defines operations supported by extensions"""
    @abstractmethod
    async def outgoing(self, payload: List[JsonObject],
                       headers: Dict[str, str]) -> None:
        """Process outgoing *payload* and *headers*

        Called just before a payload is sent

        :param payload: List of outgoing messages
        :param headers: Headers to send
        """

    @abstractmethod
    async def incoming(self, payload: List[JsonObject],
                       headers: Optional[Dict[str, str]] = None) -> None:
        """Process incoming *payload* and *headers*

        Called just after a payload is received

        :param payload: List of incoming messages
        :param headers: Headers to send
        """


class AuthExtension(Extension):  # pylint: disable=abstract-method
    """Extension with support for authentication"""
    async def authenticate(self) -> None:
        """Called after a failed authentication attempt

        For authentication schemes where the credentials are static it doesn't
        makes much sense to reimplement this function. However for schemes
        where the credentials can expire (like OAuth, JWT...) this method can
        be reimplemented to update those credentials
        """
