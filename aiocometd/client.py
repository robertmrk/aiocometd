"""Client class implementation"""
import asyncio
import reprlib
import logging
from collections import abc
from contextlib import suppress

from .transport import create_transport, DEFAULT_CONNECTION_TYPE, \
    ConnectionType
from .exceptions import ServerError, ClientInvalidOperation, TransportError, \
    TransportTimeoutError, ClientError


LOGGER = logging.getLogger(__name__)


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
    #: Defualt connection types list
    _DEFAULT_CONNECTION_TYPES = [ConnectionType.WEBSOCKET,
                                 ConnectionType.LONG_POLLING]

    def __init__(self, endpoint, connection_types=None, *,
                 connection_timeout=10.0, ssl=None, prefetch_size=0,
                 extensions=None, auth=None, loop=None):
        """
        :param str endpoint: CometD service url
        :param connection_types: List of connection types in order of \
        preference, or a single connection type name. If ``None``, \
        ["websocket", "long-polling"] will be used.
        :type connection_types: list[str], str or None
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
        :param extensions: List of protocol extension objects
        :type extensions: list[Extension] or None
        :param AuthExtension auth: An auth extension
        :param loop: Event :obj:`loop <asyncio.BaseEventLoop>` used to
                     schedule tasks. If *loop* is ``None`` then
                     :func:`asyncio.get_event_loop` is used to get the default
                     event loop.
        """
        #: CometD service url
        self.endpoint = endpoint
        #: List of connection types to use in order of preference
        self._connection_types = None
        if isinstance(connection_types, ConnectionType):
            self._connection_types = [connection_types]
        elif isinstance(connection_types, abc.Iterable):
            self._connection_types = list(connection_types)
        else:
            self._connection_types = self._DEFAULT_CONNECTION_TYPES
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
        #: List of protocol extension objects
        self.extensions = extensions
        #: An auth extension
        self.auth = auth

    def __repr__(self):
        """Formal string representation"""
        cls_name = type(self).__name__
        fmt_spec = "{}({}, {}, connection_timeout={}, ssl={}, " \
                   "prefetch_size={}, extensions={}, loop={})"
        return fmt_spec.format(cls_name,
                               reprlib.repr(self.endpoint),
                               reprlib.repr(self._connection_types),
                               reprlib.repr(self.connection_timeout),
                               reprlib.repr(self.ssl),
                               reprlib.repr(self._prefetch_size),
                               reprlib.repr(self.extensions),
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

    @property
    def connection_type(self):
        """The current connection

        :return: The current connection type in use if the client is open, \
        otherwise ``None``
        :rtype: ConnectionType or None
        """
        if self._transport is not None:
            return self._transport.connection_type
        return None

    def _pick_connection_type(self, connection_types):
        """Pick a connection type based on the  *connection_types*
        supported by the server and on the user's preferences

        :param list[str] connection_types: Connection types \
        supported by the server
        :return: The connection type with the highest precedence \
        which is supported by the server
        :rtype: ConnectionType or None
        """
        server_connection_types = []
        for type_string in connection_types:
            with suppress(ValueError):
                server_connection_types.append(ConnectionType(type_string))

        intersection = (set(server_connection_types) &
                        set(self._connection_types))
        if not intersection:
            return None

        result = min(intersection,
                     key=lambda type: self._connection_types.index(type))
        return result

    async def _negotiate_transport(self):
        """Negotiate the transport type to use with the server and create the
        transport object

        :return: Transport object
        :rtype: Transport
        :raise ClientError: If none of the connection types offered by the \
        server are supported
        """
        self._incoming_queue = asyncio.Queue(maxsize=self._prefetch_size)
        transport = create_transport(DEFAULT_CONNECTION_TYPE,
                                     endpoint=self.endpoint,
                                     incoming_queue=self._incoming_queue,
                                     ssl=self.ssl,
                                     extensions=self.extensions,
                                     auth=self.auth,
                                     loop=self._loop)

        try:
            response = await transport.handshake(self._connection_types)
            self._verify_response(response)

            LOGGER.info("Connection types supported by the server: %r",
                        response["supportedConnectionTypes"])
            connection_type = self._pick_connection_type(
                response["supportedConnectionTypes"]
            )
            if not connection_type:
                raise ClientError("None of the connection types offered by "
                                  "the server are supported.")

            if transport.connection_type != connection_type:
                client_id = transport.client_id
                await transport.close()
                transport = create_transport(
                    connection_type,
                    endpoint=self.endpoint,
                    incoming_queue=self._incoming_queue,
                    client_id=client_id,
                    ssl=self.ssl,
                    extensions=self.extensions,
                    auth=self.auth,
                    loop=self._loop)
            return transport
        except Exception:
            await transport.close()
            raise

    async def open(self):
        """Establish a connection with the CometD server

        This method works mostly the same way as the `handshake` method of
        CometD clients in the reference implementations.

        :raise ClientError: If none of the connection types offered by the \
        server are supported
        :raise ClientInvalidOperation:  If the client is already open, or in \
        other words if it isn't :obj:`closed`
        :raise TransportError: If a network or transport related error occurs
        :raise ServerError: If the handshake or the first connect request \
        gets rejected by the server.
        """
        if not self.closed:
            raise ClientInvalidOperation("Client is already open.")

        LOGGER.info("Opening client with connection types %r ...",
                    [t.value for t in self._connection_types])
        self._transport = await self._negotiate_transport()

        response = await self._transport.connect()
        self._verify_response(response)
        self._closed = False
        LOGGER.info("Client opened with connection_type %r",
                    self.connection_type.value)

    async def close(self):
        """Disconnect from the CometD server"""
        if self.pending_count == 0:
            LOGGER.info("Closing client...")
        else:
            LOGGER.warning(
                "Closing client while %s messages are still pending...",
                self.pending_count)
        try:
            if self._transport and self._transport.client_id:
                await self._transport.disconnect()

        # Don't raise TransportError if disconnect fails. Event if the
        # request fails, and the server doesn't gets notified about the
        # disconnecting client, it will still close the server side session
        # after a certain timeout. The important thing is that we did our
        # best to notify the server.
        except TransportError as error:
            LOGGER.debug("Disconnect request failed, %s", error)
        finally:
            if self._transport:
                await self._transport.close()
            self._closed = True
            LOGGER.info("Client closed.")

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
        LOGGER.info("Subscribed to channel %s", channel)

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
        LOGGER.info("Unsubscribed from channel %s", channel)

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
