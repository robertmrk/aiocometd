"""Client class implementation"""
import asyncio
import reprlib

from . import transport
from .exceptions import ServerError, ClientInvalidOperation


class Client:
    """CometD client"""
    def __init__(self, endpoint, *, loop=None):
        """
        :param str endpoint: CometD service url
        :param loop: Event :obj:`loop <asyncio.BaseEventLoop>` used to
                     schedule tasks. If *loop* is ``None`` then
                     :func:`asyncio.get_event_loop` is used to get the default
                     event loop.
        """
        #: CometD service url
        self.endpoint = endpoint
        #: event loop used to schedule tasks
        self._loop = loop or asyncio.get_event_loop()
        #: queue for consuming incoming event messages
        self._incoming_queue = None
        #: transport object
        self._transport = None
        #: marks whether the client is open or closed
        self._closed = True

    def __repr__(self):
        """Formal string representation"""
        cls_name = type(self).__name__
        fmt_spec = "{}(endpoint={}, loop={})"
        return fmt_spec.format(cls_name,
                               reprlib.repr(self.endpoint),
                               reprlib.repr(self._loop))

    @property
    def closed(self):
        """Marks whether the client is open or closed"""
        return self._closed

    @property
    def subscriptions(self):
        """Set of subscribed channels"""
        if self._transport:
            return self._transport.subscriptions
        else:
            return set()

    async def open(self):
        """Establish a connection with the CometD server

        This method works mostly the same way as the `handshake` method of
        CometD clients in the reference implementations.

        :raise ClientInvalidOperation:  If the client is already open, or in \
        other words if it isn't :obj:`closed`
        :raise ServerError: If the handshake or the first connect request \
        gets rejected by the server.
        """
        if not self.closed:
            raise ClientInvalidOperation("Client is already open.")

        self._incoming_queue = asyncio.Queue()
        self._transport = transport.LongPollingTransport(
            endpoint=self.endpoint,
            incoming_queue=self._incoming_queue
        )

        response = await self._transport.handshake([self._transport.NAME])
        if not response["successful"]:
            raise ServerError("Handshake request failed.", response)

        response = await self._transport.connect()
        if not response["successful"]:
            raise ServerError("Connect request failed.", response)
        self._closed = False

    async def close(self):
        """Disconnect from the CometD server"""
        if not self.closed:
            await self._transport.disconnect()
            self._closed = True

    async def subscribe(self, channel):
        """Subscribe to *channel*

        :param str channel: Name of the channel
        :raise ClientInvalidOperation: If the client is :obj:`closed`
        :raise ServerError: If the subscribe request gets rejected by the \
        server
        :raise TransportError: If a network or transport related error occurs
        """
        if self.closed:
            raise ClientInvalidOperation("Can't send subscribe request while, "
                                         "the client is closed.")
        response = await self._transport.subscribe(channel)
        if not response["successful"]:
            raise ServerError("Subscribe request failed.", response)

    async def unsubscribe(self, channel):
        """Unsubscribe from *channel*

        :param str channel: Name of the channel
        :raise ClientInvalidOperation: If the client is :obj:`closed`
        :raise ServerError: If the unsubscribe request gets rejected by the \
        server
        :raise TransportError: If a network or transport related error occurs
        """
        if self.closed:
            raise ClientInvalidOperation("Can't send unsubscribe request "
                                         "while, the client is closed.")
        response = await self._transport.unsubscribe(channel)
        if not response["successful"]:
            raise ServerError("Unsubscribe request failed.", response)

    async def publish(self, channel, data):
        """Publish *data* to the given *channel*

        :param str channel: Name of the channel
        :param dict data: Data to send to the server
        :raise ClientInvalidOperation: If the client is :obj:`closed`
        :raise ServerError: If the publish request gets rejected by the server
        :raise TransportError: If a network or transport related error occurs
        """
        if self.closed:
            raise ClientInvalidOperation("Can't publish data while, "
                                         "the client is closed.")
        response = await self._transport.publish(channel, data)
        if not response["successful"]:
            raise ServerError("Publish request failed.", response)
