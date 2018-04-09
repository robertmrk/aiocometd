"""Client class implementation"""
import asyncio
import reprlib
import logging

from . import transport
from .exceptions import ServerError, ClientInvalidOperation, TransportError, \
    TransportTimeoutError


logger = logging.getLogger(__name__)


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

    def __init__(self, endpoint, *, connection_timeout=10.0, ssl=None,
                 prefetch_size=0, loop=None):
        """
        :param str endpoint: CometD service url
        :param connection_timeout: The maximum amount of time to wait for the \
        transport to re-establish a connection with the server when the \
        connection fails.
        :type connection_timeout: int, float or None
        :param ssl: SSL validation mode. None for default SSL check \
        (:func:`ssl.create_default_context` is used), False for skip SSL \
        certificate validation, \
        `aiohttp.Fingerprint <https://aiohttp.readthedocs.io/en/stable/\
        client_reference.html#aiohttp.Fingerprint>`_ for fingerprint \
        validation, :obj:`ssl.SSLContext` for custom SSL certificate \
        validation.
        :param int prefetch_size: The maximum number of messages to prefetch \
        from the server. If the number of prefetched messages reach this size \
        all following messages will be dropped until messages get consumed. \
        If it is less than or equal to zero, the size is infinite.
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
        #: The maximum amount of time to wait for the transport to re-establish
        #: a connection with the server when the connection fails
        self.connection_timeout = connection_timeout
        #: SSL validation mode
        self.ssl = ssl
        #: the maximum number of messages to prefetch from the server
        self._prefetch_size = prefetch_size

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
        :raise TransportError: If a network or transport related error occurs
        :raise ServerError: If the handshake or the first connect request \
        gets rejected by the server.
        """
        if not self.closed:
            raise ClientInvalidOperation("Client is already open.")

        self._incoming_queue = asyncio.Queue(maxsize=self._prefetch_size)
        self._transport = transport.LongPollingTransport(
            endpoint=self.endpoint,
            incoming_queue=self._incoming_queue,
            ssl=self.ssl
        )

        response = await self._transport.handshake([self._transport.name])
        self._verify_response(response)

        response = await self._transport.connect()
        self._verify_response(response)
        self._closed = False

    async def close(self):
        """Disconnect from the CometD server"""
        try:
            if self._transport.client_id:
                await self._transport.disconnect()

        # Don't raise TransportError if disconnect fails. Event if the
        # request fails, and the server doesn't gets notified about the
        # disconnecting client, it will still close the server side session
        # after a certain timeout. The important thing is that we did our
        # best to notify the server.
        except TransportError as error:
            logger.debug("Disconnect request failed, {}".format(error))
        finally:
            await self._transport.close()
            self._closed = True

    async def subscribe(self, channel):
        """Subscribe to *channel*

        :param str channel: Name of the channel
        :raise ClientInvalidOperation: If the client is :obj:`closed`
        :raise TransportError: If a network or transport related error occurs
        :raise ServerError: If the subscribe request gets rejected by the \
        server
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
        :raise TransportError: If a network or transport related error occurs
        :raise ServerError: If the unsubscribe request gets rejected by the \
        server
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
        :raise TransportError: If a network or transport related error occurs
        :raise ServerError: If the publish request gets rejected by the server
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
        :raise TransportTimeoutError: If the transport can't re-establish \
        connection with the server in :obj:`connection_timeout` time.
        """
        if not self.closed or self.has_pending_messages:
            response = await self._get_message(self.connection_timeout)
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

    async def __aiter__(self):
        """Asynchronous iterator

        :raise ServerError: If the client receives a confirmation message \
         which is not ``successful``
        :raise TransportTimeoutError: If the transport can't re-establish \
        connection with the server in :obj:`connection_timeout` time.
        """
        while True:
            try:
                yield await self.receive()
            except ClientInvalidOperation:
                break

    async def __aenter__(self):
        """Enter the runtime context and call :obj:`open`

        :raise ClientInvalidOperation:  If the client is already open, or in \
        other words if it isn't :obj:`closed`
        :raise TransportError: If a network or transport related error occurs
        :raise ServerError: If the handshake or the first connect request \
        gets rejected by the server.
        :return: The client object itself
        :rtype: Client
        """
        try:
            await self.open()
        except Exception:
            await self.close()
            raise
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit the runtime context and call :obj:`open`"""
        await self.close()

    async def _get_message(self, connection_timeout):
        """Get the next incoming message

        :param connection_timeout: The maximum amount of time to wait for the \
        transport to re-establish a connection with the server when the \
        connection fails.
        :return: Incoming message
        :rtype: dict
        :raise TransportTimeoutError: If the transport can't re-establish \
        connection with the server in :obj:`connection_timeout` time.
        """
        if connection_timeout:
            timeout_task = asyncio.ensure_future(
                self._wait_connection_timeout(connection_timeout),
                loop=self._loop
            )
            get_task = asyncio.ensure_future(self._incoming_queue.get(),
                                             loop=self._loop)
            try:
                done, pending = await asyncio.wait(
                    [timeout_task, get_task],
                    return_when=asyncio.FIRST_COMPLETED,
                    loop=self._loop)

                next(iter(pending)).cancel()
                if get_task in done:
                    return get_task.result()
                else:
                    raise TransportTimeoutError("Lost connection with the "
                                                "server.")
            except asyncio.CancelledError:
                timeout_task.cancel()
                get_task.cancel()
                raise
        else:
            return await self._incoming_queue.get()

    async def _wait_connection_timeout(self, timeout):
        """Wait for and return when the transport can't re-establish \
        connection with the server in *timeout* time

        :param timeout: The maximum amount of time to wait for the \
        transport to re-establish a connection with the server when the \
        connection fails.
        """
        while True:
            await self._transport.wait_for_connecting()
            try:
                await asyncio.wait_for(self._transport.wait_for_connected(),
                                       timeout, loop=self._loop)
            except asyncio.TimeoutError:
                break
