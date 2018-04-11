"""Transport classes"""
import asyncio
import logging
from enum import Enum, unique, auto
from abc import ABC, abstractmethod

import aiohttp

from .exceptions import TransportError, TransportInvalidOperation


logger = logging.getLogger(__name__)


@unique
class ConnectionType(Enum):
    """Connection types"""
    #: Long polling connection type
    LONG_POLLING = "long-polling"
    #: Websocket connection type
    WEBSOCKET = "websocket"


DEFAULT_CONNECTION_TYPE = ConnectionType.LONG_POLLING
transport_classes = {}


def register_transport(type):
    """Class decorator for registering transport classes

    The class' connection_type property will be also defined to return the
    given *connection_type*
    :param ConnectionType type: A connection type
    :return: The updated class
    """
    def decorator(cls):
        global transport_classes
        transport_classes[type] = cls

        @property
        def connection_type(instance):
            return type

        cls.connection_type = connection_type
        return cls
    return decorator


def create_transport(connection_type, *args, **kwargs):
    """Create a transport object that can be used for the given
    *connection_type*

    :param ConnectionType connection_type: A connection type
    :param args: Positional arguments to pass to the transport
    :param kwargs: Keyword arguments to pass to the transport
    :return: A transport object
    :rtype: Transport
    """
    global transport_classes

    if connection_type not in transport_classes:
        raise TransportInvalidOperation("There is no transport for connection "
                                        "type {!r}".format(connection_type))

    return transport_classes[connection_type](*args, **kwargs)


@unique
class TransportState(Enum):
    """Describes a transport object's state"""
    #: Transport is disconnected
    DISCONNECTED = auto()
    #: Transport is trying to establish a connection
    CONNECTING = auto()
    #: Transport is connected to the server
    CONNECTED = auto()
    #: Transport is disconnecting from the server
    DISCONNECTING = auto()


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

        :raises TransportError: When the network request fails.
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
    async def wait_for_connected(self):
        """Waits for and returns when the transport enters the \
        :obj:`~TransportState.CONNECTED` state"""

    @abstractmethod
    async def wait_for_connecting(self):
        """Waits for and returns when the transport enters the \
        :obj:`~TransportState.CONNECTING` state"""


class _TransportBase(Transport):
    """Base transport implementation

    This class contains most of the transport operations implemented, it can
    be used as a base class for various concrete transport implementations.
    When subclassing, at a minimum the :meth:`_send_final_payload` and
    :obj:`~Transport.connection_type` methods should be reimplemented.
    """
    #: Handshake message template
    _HANDSHAKE_MESSAGE = {
        # mandatory
        "channel": "/meta/handshake",
        "version": "1.0",
        "supportedConnectionTypes": None,
        # optional
        "minimumVersion": "1.0",
        "id": None
    }
    #: Connect message template
    _CONNECT_MESSAGE = {
        # mandatory
        "channel": "/meta/connect",
        "clientId": None,
        "connectionType": None,
        # optional
        "id": None
    }
    #: Disconnect message template
    _DISCONNECT_MESSAGE = {
        # mandatory
        "channel": "/meta/disconnect",
        "clientId": None,
        # optional
        "id": None
    }
    #: Subscribe message template
    _SUBSCRIBE_MESSAGE = {
        # mandatory
        "channel": "/meta/subscribe",
        "clientId": None,
        "subscription": None,
        # optional
        "id": None
    }
    #: Unsubscribe message template
    _UNSUBSCRIBE_MESSAGE = {
        # mandatory
        "channel": "/meta/unsubscribe",
        "clientId": None,
        "subscription": None,
        # optional
        "id": None
    }
    #: Publish message template
    _PUBLISH_MESSAGE = {
        # mandatory
        "channel": None,
        "clientId": None,
        "data": None,
        # optional
        "id": None
    }
    #: Timeout to give to HTTP session to close itself
    _HTTP_SESSION_CLOSE_TIMEOUT = 0.250

    def __init__(self, *, endpoint, incoming_queue,
                 client_id=None, reconnection_timeout=1, ssl=None, loop=None):
        """
        :param str endpoint: CometD service url
        :param asyncio.Queue incoming_queue: Queue for consuming incoming event
                                             messages
        :param str client_id: Clinet id value assigned by the server
        :param reconnection_timeout: The time to wait before trying to \
        reconnect to the server after a network failure
        :type reconnection_timeout: None or int or float
        :param ssl: SSL validation mode. None for default SSL check \
        (:func:`ssl.create_default_context` is used), False for skip SSL \
        certificate validation, \
        `aiohttp.Fingerprint <https://aiohttp.readthedocs.io/en/stable/\
        client_reference.html#aiohttp.Fingerprint>`_ for fingerprint \
        validation, :obj:`ssl.SSLContext` for custom SSL certificate \
        validation.
        :param loop: Event :obj:`loop <asyncio.BaseEventLoop>` used to
                     schedule tasks. If *loop* is ``None`` then
                     :func:`asyncio.get_event_loop` is used to get the default
                     event loop.
        """
        #: queue for consuming incoming event messages
        self.incoming_queue = incoming_queue
        #: CometD service url
        self._endpoint = endpoint
        #: event loop used to schedule tasks
        self._loop = loop or asyncio.get_event_loop()
        #: clinet id value assigned by the server
        self._client_id = client_id
        #: message id which should be unique for every message during a client
        #: session
        self._message_id = 0
        #: reconnection advice parameters returned by the server
        self._reconnect_advice = {}
        #: set of subscribed channels
        self._subscriptions = set()
        #: boolean to mark whether to resubscribe on connect
        self._subscribe_on_connect = False
        #: current state of the transport
        self._state = TransportState.DISCONNECTED
        #: asyncio connection task
        self._connect_task = None
        #: time to wait before reconnecting after a network failure
        self._reconnect_timeout = reconnection_timeout
        #: asyncio event, set when the state becomes CONNECTED
        self._connected_event = asyncio.Event()
        #: asyncio event, set when the state becomes CONNECTING
        self._connecting_event = asyncio.Event()
        #: SSL validation mode
        self.ssl = ssl
        #: semaphore to limit the number of concurrent HTTP connections to 2
        self._http_semaphore = asyncio.Semaphore(2, loop=self._loop)
        #: http session
        self._http_session = None

    async def _get_http_session(self):
        """Factory method for getting the current HTTP session

        :return: The current session if it's not None, otherwise it creates a
                 new session.
        """
        # it would be nicer to create the session when the class gets
        # initialized, but this seems to be the right way to do it since
        # aiohttp produces log messages with warnings that a session should be
        # created in a coroutine
        if self._http_session is None:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def _close_http_session(self):
        """Close the http session if it's not already closed"""
        # graceful shutdown recommended by the documentation
        # https://aiohttp.readthedocs.io/en/stable/client_advanced.html#graceful-shutdown
        if self._http_session is not None and not self._http_session.closed:
            await self._http_session.close()
            await asyncio.sleep(self._HTTP_SESSION_CLOSE_TIMEOUT)

    @property
    def connection_type(self):
        """The transport's connection type"""
        return None  # pragma: no cover

    @property
    def endpoint(self):
        """CometD service url"""
        return self._endpoint

    @property
    def client_id(self):
        """clinet id value assigned by the server"""
        return self._client_id

    @property
    def state(self):
        """Current state of the transport"""
        return self._state

    @property
    def subscriptions(self):
        """Set of subscribed channels"""
        return self._subscriptions

    async def wait_for_connected(self):
        await self._connected_event.wait()

    async def wait_for_connecting(self):
        await self._connecting_event.wait()

    async def handshake(self, connection_types):
        """Executes the handshake operation

        :param list[ConnectionType] connection_types: list of connection types
        :return: Handshake response
        :rtype: dict
        :raises TransportError: When the network request fails.
        """
        return await self._handshake(connection_types, delay=None)

    async def _handshake(self, connection_types, delay=None):
        """Executes the handshake operation

        :param list[ConnectionType] connection_types: list of connection types
        :param delay: Initial connection delay
        :type delay: None or int or float
        :return: Handshake response
        :rtype: dict
        :raises TransportError: When the network request fails.
        """
        if delay:
            await asyncio.sleep(delay, loop=self._loop)
        # reset message id for a new client session
        self._message_id = 0

        connection_types = list(connection_types)
        # make sure that the supported connection types list contains this
        # transport
        if self.connection_type not in connection_types:
            connection_types.append(self.connection_type)
        connection_type_values = [ct.value for ct in connection_types]

        # send message and await its response
        response_message = await self._send_message(
            self._HANDSHAKE_MESSAGE.copy(),
            supportedConnectionTypes=connection_type_values
        )
        # store the returned client id or set it to None if it's not in the
        # response
        if response_message["successful"]:
            self._client_id = response_message.get("clientId")
            self._subscribe_on_connect = True
        return response_message

    def _finalize_message(self, message):
        """Update the ``id``, ``clientId`` and ``connectionType`` message
        fields as a side effect if they're are present in the *message*.

        :param dict message: Outgoing message
        """
        if "id" in message:
            message["id"] = str(self._message_id)
            self._message_id += 1

        if "clientId" in message:
            message["clientId"] = self.client_id

        if "connectionType" in message:
            message["connectionType"] = self.connection_type.value

    def _finalize_payload(self, payload):
        """Update the ``id``, ``clientId`` and ``connectionType`` message
        fields in the *payload*, as a side effect if they're are present in
        the *message*. The *payload* can be either a single message or a list
        of messages.

        :param payload: A message or a list of messages
        :type payload: dict or list[dict]
        """
        if isinstance(payload, list):
            for item in payload:
                self._finalize_message(item)
        else:
            self._finalize_message(payload)

    async def _send_message(self, message, **kwargs):
        """Send message to server

        :param dict message: A message
        :param kwargs: Optional key-value pairs that'll be used to update the \
        the values in the *message*
        :return: Response message
        :rtype: dict
        :raises TransportError: When the network request fails.
        """
        message.update(kwargs)
        return await self._send_payload([message])

    async def _send_payload(self, payload):
        """Finalize and send *payload* to server

        Finalize and send the *payload* to the server and return once a
        response message can be provided for the first message in the
        *payload*.

        :param list[dict] payload: A list of messages
        :return: The response message for the first message in the *payload*
        :rtype: dict
        :raises TransportError: When the network request fails.
        """
        self._finalize_payload(payload)
        headers = {}
        return await self._send_final_payload(payload, headers=headers)

    @abstractmethod
    async def _send_final_payload(self, payload, *, headers):
        """Send *payload* to server

        Send the *payload* to the server and return once a
        response message can be provided for the first message in the
        *payload*.
        When reimplementing this method keep in mind that the server will
        likely return additional responses which should be enqueued for
        consumers. To enqueue the received messages :meth:`_consume_payload`
        can be used.

        :param list[dict] payload: A list of messages
        :param dict headers: Headers to send
        :return: The response message for the first message in the *payload*
        :rtype: dict
        :raises TransportError: When the network request fails.
        """

    def _is_matching_response(self, response_message, message):
        """Check whether the *response_message* is a response for the
        given *message*.

        :param dict message: A sent message
        :param response_message: A response message
        :return: True if the *response_message* is a match for *message*
                 otherwise False.
        :rtype: bool
        """
        if message is None or response_message is None:
            return False
        # to consider a response message as a pair of the sent message
        # their channel should match, if they contain an id field it should
        # also match (according to the specs an id is always optional),
        # and the response message should contain the successful field
        return (message["channel"] == response_message["channel"] and
                message.get("id") == response_message.get("id") and
                "successful" in response_message)

    def _is_server_error_message(self, response_message):
        """Check whether the *response_message* is a server side error message

        :param response_message: A response message
        :return: True if the *response_message* is a server side error message
                 otherwise False.
        :rtype: bool
        """
        return (response_message["channel"] != "/meta/connect" and
                response_message["channel"] != "/meta/disconnect" and
                response_message["channel"] != "/meta/handshake" and
                not response_message.get("successful", True))

    def _is_event_message(self, response_message):
        """Check whether the *response_message* is an event message

        :param response_message: A response message
        :return: True if the *response_message* is an event message
                 otherwise False.
        :rtype: bool
        """
        return (not response_message["channel"].startswith("/meta/") and
                not response_message["channel"].startswith("/service/") and
                "data" in response_message)

    def _consume_message(self, response_message):
        """Enqueue the *response_message* for consumers if it's a type of
        message that consumers should receive

        :param response_message: A response message
        """
        if (self._is_server_error_message(response_message) or
                self._is_event_message(response_message)):
            self._enqueue_message(response_message)

    def _update_subscriptions(self, response_message):
        """Update the set of subscriptions based on the *response_message*

       :param response_message: A response message
        """
        # if a subscription response is successful, then add the channel
        # to the set of subscriptions, if it fails, then remove it
        if response_message["channel"] == "/meta/subscribe":
            if (response_message["successful"] and
                    response_message["subscription"]
                    not in self._subscriptions):
                self._subscriptions.add(response_message["subscription"])
            elif (not response_message["successful"] and
                  response_message["subscription"] in self._subscriptions):
                self._subscriptions.remove(response_message["subscription"])

        # if an unsubscribe response is successful then remove the channel
        # from the set of subscriptions
        if response_message["channel"] == "/meta/unsubscribe":
            if (response_message["successful"] and
                    response_message["subscription"] in self._subscriptions):
                self._subscriptions.remove(response_message["subscription"])

    async def _consume_payload(self, payload, *, headers=None,
                               find_response_for=None):
        """Enqueue event messages for the consumers and update the internal
        state of the transport, based on response messages in the *payload*.

        :param payload: A list of response messages
        :type payload: list[dict]
        :param headers: Received headers
        :type headers: dict or None
        :param dict find_response_for: Find and return the matching \
        response message for the given *find_response_for* message.
        :return: The response message for the *find_response_for* message, \
        otherwise ``None``
        :rtype: dict or None
        """
        # return None if no response message is found for *find_response_for*
        result = None
        for message in payload:
            # if there is an advice in the message then update the transport's
            # reconnect advice
            if "advice" in message:
                self._reconnect_advice = message["advice"]

            # update subscriptions based on responses
            self._update_subscriptions(message)

            # set the message as the result and continue if it is a matching
            # response
            if (result is None and
                    self._is_matching_response(message, find_response_for)):
                result = message
                continue

            self._consume_message(message)
        return result

    def _enqueue_message(self, message):
        """Enqueue *message* for consumers or drop the message if the queue \
        is full

        :param message: A response message
        """
        try:
            self.incoming_queue.put_nowait(message)
        except asyncio.QueueFull:
            logger.debug("Incoming message queue is full, "
                         "dropping message.")

    def _start_connect_task(self, coro):
        """Wrap the *coro* in a future and schedule it

        The future is stored internally in :obj:`_connect_task`. The future's
        results will be consumed by :obj:`_connect_done`.

        :param coro: Coroutine
        :return: Future
        """
        self._connect_task = asyncio.ensure_future(coro, loop=self._loop)
        self._connect_task.add_done_callback(self._connect_done)
        return self._connect_task

    async def _stop_connect_task(self):
        """Stop the connection task

        If no connect task exists or if it's done it does nothing.
        """
        if self._connect_task and not self._connect_task.done():
            self._connect_task.cancel()
            await asyncio.wait([self._connect_task])

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
        if not self.client_id:
            raise TransportInvalidOperation(
                "Can't connect to the server without a client id. "
                "Do a handshake first.")
        if self.state != TransportState.DISCONNECTED:
            raise TransportInvalidOperation(
                "Can't connect to a server without disconnecting first.")

        self._state = TransportState.CONNECTING
        return await self._start_connect_task(self._connect())

    async def _connect(self, delay=None):
        """Connect to the server

        :param delay: Initial connection delay
        :type delay: None or int or float
        :return: Connect response
        :rtype: dict
        :raises TransportError: When the network request fails.
        """
        if delay:
            await asyncio.sleep(delay, loop=self._loop)
        message = self._CONNECT_MESSAGE.copy()
        payload = [message]
        if self._subscribe_on_connect and self.subscriptions:
            for subscription in self.subscriptions:
                extra_message = self._SUBSCRIBE_MESSAGE.copy()
                extra_message["subscription"] = subscription
                payload.append(extra_message)
        result = await self._send_payload(payload)
        self._subscribe_on_connect = not result["successful"]
        return result

    def _connect_done(self, future):
        """Consume the result of the *future* and follow the server's \
        connection advice if the transport is still connected

        :param asyncio.Future future: A :obj:`_connect` or :obj:`_handshake` \
        future
        """
        try:
            result = future.result()
            reconnect_timeout = self._reconnect_advice["interval"]
            if self.state == TransportState.CONNECTING:
                self._state = TransportState.CONNECTED
                self._connected_event.set()
                self._connecting_event.clear()
        except Exception as error:
            result = error
            reconnect_timeout = self._reconnect_timeout
            if self.state == TransportState.CONNECTED:
                self._state = TransportState.CONNECTING
                self._connecting_event.set()
                self._connected_event.clear()

        log_fmt = "Connect task finished with: {!r}"
        logger.debug(log_fmt.format(result))

        if self.state != TransportState.DISCONNECTING:
            self._follow_advice(reconnect_timeout)

    def _follow_advice(self, reconnect_timeout):
        """Follow the server's reconnect advice

        Either a :obj:`_connect` or :obj:`_handshake` operation is started
        based on the advice or the method returns without starting any
        operation if no advice is provided.

        :param reconnect_timeout: Initial connection delay to pass to \
        :obj:`_connect` or :obj:`_handshake`.
        """
        advice = self._reconnect_advice.get("reconnect")
        # do a handshake operation if advised
        if advice == "handshake":
            self._start_connect_task(
                self._handshake([self.connection_type],
                                delay=reconnect_timeout)
            )
        # do a connect operation if advised
        elif advice == "retry":
            self._start_connect_task(self._connect(delay=reconnect_timeout))
        # there is not reconnect advice from the server or its value
        # is none
        else:
            logger.debug("No reconnect advice provided, no more operations "
                         "will be scheduled.")
            self._state = TransportState.DISCONNECTED

    async def disconnect(self):
        """Disconnect from server

        :raises TransportError: When the network request fails.
        """
        try:
            self._state = TransportState.DISCONNECTING
            await self._stop_connect_task()
            await self._send_message(self._DISCONNECT_MESSAGE.copy())
        finally:
            self._state = TransportState.DISCONNECTED

    async def close(self):
        """Close transport and release resources"""
        await self._close_http_session()

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
        if self.state not in [TransportState.CONNECTING,
                              TransportState.CONNECTED]:
            raise TransportInvalidOperation(
                "Can't subscribe without being connected to a server.")
        return await self._send_message(self._SUBSCRIBE_MESSAGE.copy(),
                                        subscription=channel)

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
        if self.state not in [TransportState.CONNECTING,
                              TransportState.CONNECTED]:
            raise TransportInvalidOperation(
                "Can't unsubscribe without being connected to a server.")
        return await self._send_message(self._UNSUBSCRIBE_MESSAGE.copy(),
                                        subscription=channel)

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
        if self.state not in [TransportState.CONNECTING,
                              TransportState.CONNECTED]:
            raise TransportInvalidOperation(
                "Can't publish without being connected to a server.")
        return await self._send_message(self._PUBLISH_MESSAGE.copy(),
                                        channel=channel,
                                        data=data)


@register_transport(ConnectionType.LONG_POLLING)
class LongPollingTransport(_TransportBase):
    """Long-polling type transport"""

    async def _send_final_payload(self, payload, *, headers):
        try:
            session = await self._get_http_session()
            async with self._http_semaphore:
                response = await session.post(self._endpoint, json=payload,
                                              ssl=self.ssl, headers=headers)
            response_payload = await response.json()
            headers = response.headers
        except aiohttp.client_exceptions.ClientError as error:
            logger.debug("Failed to send payload, {}".format(error))
            raise TransportError(str(error)) from error
        return await self._consume_payload(response_payload, headers=headers,
                                           find_response_for=payload[0])


class _WebSocket:
    """Helper class to create future-like objects which return websocket
    objects

    This class allows us to use websockets objects without context blocks
    """
    def __init__(self, session_factory, *args, **kwargs):
        """
        :param asyncio.coroutine session_factory: Coroutine factory function \
        which returns an HTTP session
        :param args: positional arguments for the ws_connect function
        :param kwargs: keyword arguments for the ws_connect function
        """
        self._session_factory = session_factory
        self._constructor_args = args
        self._constructor_kwargs = kwargs
        self._context = None
        self._socket = None
        self._headers = None

    async def close(self):
        """Close the websocket"""
        await self._exit()

    async def get_socket(self, headers):
        """Create or return an existing websocket object

        :param dict headers: Headers to send
        :return: Websocket object
        :rtype: `aiohttp.ClientWebSocketResponse \
        <https://aiohttp.readthedocs.io/en/stable\
        /client_reference.html#aiohttp.ClientWebSocketResponse>`_
        """
        self._headers = headers
        # if a the websocket object already exists and if it's in closed state
        # exit the context manager properly and clear the references
        if self._socket is not None and self._socket.closed:
            await self._exit()

        # if there is no websocket object, then create it and enter the \
        # context manager properly to initialize it
        if self._socket is None:
            await self._enter()

        return self._socket

    async def _enter(self):
        """Enter websocket context"""
        session = await self._session_factory()
        kwargs = self._constructor_kwargs.copy()
        kwargs["headers"] = self._headers
        self._context = session.ws_connect(*self._constructor_args, **kwargs)
        self._socket = await self._context.__aenter__()

    async def _exit(self):
        """Exit websocket context"""
        if self._context:
            await self._context.__aexit__(None, None, None)
            self._socket = self._context = None


@register_transport(ConnectionType.WEBSOCKET)
class WebSocketTransport(_TransportBase):
    """WebSocket type transport"""

    def __init__(self, *, endpoint, incoming_queue, client_id=None,
                 reconnection_timeout=1, ssl=None, loop=None):
        super().__init__(endpoint=endpoint,
                         incoming_queue=incoming_queue,
                         client_id=client_id,
                         reconnection_timeout=reconnection_timeout,
                         ssl=ssl, loop=loop)

        #: channels used during the connect task, requests on these channels
        #: are usually long running
        self._connect_task_channels = ("/meta/handshake", "/meta/connect")
        #: websocket for short duration requests
        self._websocket = _WebSocket(self._get_http_session,
                                     self.endpoint, ssl=self.ssl)
        #: exclusive lock for the _websocket object
        self._websocket_lock = asyncio.Lock()
        #: websocket for long duration requests
        self._connect_websocket = _WebSocket(self._get_http_session,
                                             self.endpoint, ssl=self.ssl)
        #: exclusive lock for the _connect_websocket object
        self._connect_websocket_lock = asyncio.Lock()

    async def _get_socket(self, channel, headers):
        """Get a websocket object for the given *channel*

        Returns different websocket objects for long running and short duration
        requests, so while a long running request is pending, short duration
        requests can be transmitted.

        :param str channel: CometD channel name
        :param dict headers: Headers to send
        :return: websocket object
        :rtype: aiohttp.ClientWebSocketResponse
        """
        if channel in self._connect_task_channels:
            return await self._connect_websocket.get_socket(headers)
        else:
            return await self._websocket.get_socket(headers)

    def _get_socket_lock(self, channel):
        """Get an exclusive lock object for the given *channel*

        :param str channel: CometD channel name
        :return: lock object for the *channel*
        :rtype: asyncio.Lock
        """
        if channel in self._connect_task_channels:
            return self._connect_websocket_lock
        else:
            return self._websocket_lock

    async def _send_final_payload(self, payload, *, headers):
        try:
            # the channel of the first message
            channel = payload[0]["channel"]
            # get the socket and the lock associated with it, for the channel
            # of the first message
            socket = await self._get_socket(channel, headers)
            lock = self._get_socket_lock(channel)

            async with lock:
                return await self._send_socket_payload(socket, payload)

        except aiohttp.client_exceptions.ClientError as error:
            logger.debug("Failed to send payload, {}".format(error))
            raise TransportError(str(error)) from error

    async def _send_socket_payload(self, socket, payload):
        """Send *payload* to the server on the given *socket*

        :param socket: WebSocket object
        :type socket: `aiohttp.ClientWebSocketResponse \
        <https://aiohttp.readthedocs.io/en/stable\
        /client_reference.html#aiohttp.ClientWebSocketResponse>`_
        :param list[dict] payload: A message or a list of messages
        :return: Response payload
        :rtype: list[dict]
        :raises TransportError: When the request fails.
        """
        # receive responses from the server and consume them,
        # until we get back the response for the first message in the *payload*
        await socket.send_json(payload)
        while True:
            response = await socket.receive()
            response_payload = response.json()
            matching_response = await self._consume_payload(
                response_payload,
                headers=None,
                find_response_for=payload[0])
            if matching_response:
                return matching_response

    async def close(self):
        await self._websocket.close()
        await self._connect_websocket.close()
        await self._close_http_session()
