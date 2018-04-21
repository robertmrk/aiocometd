"""Transport abstract base class definition"""
from abc import ABC, abstractmethod


class Transport(ABC):
    """Defines the operations that all transport classes should support"""
    @property
    @abstractmethod
    def connection_type(self):
        """The transport's connection type"""

    @property
    @abstractmethod
    def endpoint(self):
        """CometD service url"""

    @property
    @abstractmethod
    def client_id(self):
        """Clinet id value assigned by the server"""

    @property
    @abstractmethod
    def state(self):
        """Current state of the transport"""

    @property
    @abstractmethod
    def subscriptions(self):
        """Set of subscribed channels"""

    @property
    @abstractmethod
    def last_connect_result(self):
        """Result of the last connect request"""

    @abstractmethod
    async def handshake(self, connection_types):
        """Executes the handshake operation

        :param list[ConnectionType] connection_types: list of connection types
        :return: Handshake response
        :rtype: dict
        :raises TransportError: When the network request fails.
        """

    @abstractmethod
    async def connect(self):
        """Connect to the server

        The transport will try to start and maintain a continuous connection
        with the server, but it'll return with the response of the first
        successful connection as soon as possible.

        :return dict: The response of the first successful connection.
        :raise TransportInvalidOperation: If the transport doesn't has a \
        client id yet, or if it's not in a :obj:`~TransportState.DISCONNECTED`\
        :obj:`state`.
        :raises TransportError: When the network request fails.
        """

    @abstractmethod
    async def disconnect(self):
        """Disconnect from server

        The disconnect message is only sent to the server if the transport is
        actually connected.
        """

    @abstractmethod
    async def close(self):
        """Close transport and release resources"""

    @abstractmethod
    async def subscribe(self, channel):
        """Subscribe to *channel*

        :param str channel: Name of the channel
        :return: Subscribe response
        :rtype: dict
        :raise TransportInvalidOperation: If the transport is not in the \
        :obj:`~TransportState.CONNECTED` or :obj:`~TransportState.CONNECTING` \
        :obj:`state`
        :raises TransportError: When the network request fails.
        """

    @abstractmethod
    async def unsubscribe(self, channel):
        """Unsubscribe from *channel*

        :param str channel: Name of the channel
        :return: Unsubscribe response
        :rtype: dict
        :raise TransportInvalidOperation: If the transport is not in the \
        :obj:`~TransportState.CONNECTED` or :obj:`~TransportState.CONNECTING` \
        :obj:`state`
        :raises TransportError: When the network request fails.
        """

    @abstractmethod
    async def publish(self, channel, data):
        """Publish *data* to the given *channel*

        :param str channel: Name of the channel
        :param dict data: Data to send to the server
        :return: Publish response
        :rtype: dict
        :raise TransportInvalidOperation: If the transport is not in the \
        :obj:`~TransportState.CONNECTED` or :obj:`~TransportState.CONNECTING` \
        :obj:`state`
        :raises TransportError: When the network request fails.
        """

    @abstractmethod
    async def wait_for_state(self, state):
        """Waits for and returns when the transport enters the given *state*

        :param TransportState state: A state value
        """
