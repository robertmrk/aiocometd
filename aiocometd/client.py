"""Client class implementation"""
import asyncio
import reprlib

from . import transport
from .exceptions import ServerError, ClientInvalidOperation


class Client:
    """CometD client"""
    #: Predefined server error messages by channel name
    _SERVER_ERROR_MESSAGES = {
        "/meta/handshake": "Handshake request failed.",
        "/meta/connect": "Connect request failed.",
        "/meta/disconnect": "Disconnect request failed.",
        "/meta/subscribe": "Subscribe request failed.",
        "/meta/unsubscribe": "Unsubscribe request failed."
    }

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
        self._verify_response(response)

        response = await self._transport.connect()
        self._verify_response(response)
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
        self._verify_response(response)

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
        self._verify_response(response)

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
        self._verify_response(response)

    def _verify_response(self, response):
        """Check the ``successful`` status of the *response* and raise \
        the appropriate :obj:`~aiocometd.exceptions.ServerError` if it's False

        If the *response* has no ``successful`` field, it's considered to be
        successful.

        :param dict response: Response message
        :raise ServerError: If the *response* is not ``successful``
        """
        if not response.get("successful", True):
            self._raise_server_error(response)

    def _raise_server_error(self, response):
        """Raise the appropriate :obj:`~aiocometd.exceptions.ServerError` for \
        the failed *response*

        :param dict response: Response message
        :raise ServerError: If the *response* is not ``successful``
        """
        channel = response["channel"]
        message = type(self)._SERVER_ERROR_MESSAGES.get(channel)
        if not message:
            if channel.startswith("/service/"):
                message = "Service request failed."
            else:
                message = "Publish request failed."
        raise ServerError(message, response)

    async def receive(self):
        """Wait for incoming messages from the server

        :return: Incoming message
        :rtype: dict
        :raise ClientInvalidOperation: If the client is closed, and has no \
        more pending incoming messages
        :raise ServerError: If the client receives a confirmation message \
         which is not ``successful``
        """
        if not self.closed or self.has_pending_messages:
            response = await self._incoming_queue.get()
            self._verify_response(response)
            return response
        else:
            raise ClientInvalidOperation("The client is closed and there are "
                                         "no pending messages.")

    @property
    def pending_count(self):
        """The number of pending incoming messages

        Once :obj:`open` is called the client starts listening for messages
        from the server. The incoming messages are retrieved and stored in an
        internal queue until they get consumed by calling :obj:`receive`.
        """
        if self._incoming_queue is None:
            return 0
        return self._incoming_queue.qsize()

    @property
    def has_pending_messages(self):
        """Marks whether the client has any pending incoming messages"""
        return self.pending_count > 0
