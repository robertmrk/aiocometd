"""Websocket transport class definition"""
import asyncio
import logging
from contextlib import suppress

import aiohttp

from ..constants import ConnectionType, MetaChannel
from .registry import register_transport
from .base import TransportBase
from ..exceptions import TransportError, TransportConnectionClosed


LOGGER = logging.getLogger(__name__)


class WebSocketFactory:  # pylint: disable=too-few-public-methods
    """Helper class to create asynchronous callable objects, that return
    factory objects

    This class allows the usage of factory objects without context blocks
    """
    def __init__(self, session_factory):
        """
        :param asyncio.coroutine session_factory: Coroutine factory function \
        which returns an HTTP session
        """
        self._session_factory = session_factory
        self._context = None
        self._socket = None

    async def close(self):
        """Close the factory"""
        with suppress(Exception):
            await self._exit()

    async def __call__(self, *args, **kwargs):
        """Create a new factory object or returns a previously created one
        if it's not closed

        :param args: positional arguments for the ws_connect function
        :param kwargs: keyword arguments for the ws_connect function
        :return: Websocket object
        :rtype: `aiohttp.ClientWebSocketResponse \
        <https://aiohttp.readthedocs.io/en/stable\
        /client_reference.html#aiohttp.ClientWebSocketResponse>`_
        """
        # if a the factory object already exists and if it's in closed state
        # exit the context manager and clear the references
        if self._socket is not None and self._socket.closed:
            await self._exit()

        # if there is no factory object, then create it and enter the \
        # context manager to initialize it
        if self._socket is None:
            await self._enter(*args, **kwargs)

        return self._socket

    async def _enter(self, *args, **kwargs):
        """Enter factory context

        :param args: positional arguments for the ws_connect function
        :param kwargs: keyword arguments for the ws_connect function
        """
        session = await self._session_factory()
        self._context = session.ws_connect(*args, **kwargs)
        self._socket = await self._context.__aenter__()

    async def _exit(self):
        """Exit factory context"""
        if self._context:
            await self._context.__aexit__(None, None, None)
            self._socket = self._context = None


@register_transport(ConnectionType.WEBSOCKET)
class WebSocketTransport(TransportBase):
    """WebSocket type transport"""

    #: The increase factor to use for request timeout
    REQUEST_TIMEOUT_INCREASE_FACTOR = 1.2

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #: channels used during the connect task, requests on these channels
        #: are usually long running
        self._long_duration_channels = (MetaChannel.HANDSHAKE,
                                        MetaChannel.CONNECT)

        #: factory creating sockets for short duration requests
        self._socket_factory_short = WebSocketFactory(self._get_http_session)
        #: factory creating sockets for long duration requests
        self._socket_factory_long = WebSocketFactory(self._get_http_session)

        #: exclusive lock for the objects created by _socket_factory_short
        self._socket_lock_short = asyncio.Lock()
        #: exclusive lock for the objects created by _socket_factory_long
        self._socket_lock_long = asyncio.Lock()

    @property
    def request_timeout(self):
        timeout = super().request_timeout
        if timeout:
            # increase the timeout specified by the server to avoid timing out
            # by mistake
            timeout *= self.__class__.REQUEST_TIMEOUT_INCREASE_FACTOR
        return timeout

    async def _get_socket(self, channel, headers):
        """Get a websocket object for the given *channel*

        Returns different websocket objects for long running and short duration
        requests, so while a long running request is pending, short duration
        requests can be transmitted.

        :param str channel: CometD channel name
        :param dict headers: Headers to send
        :return: Websocket object
        :rtype: `aiohttp.ClientWebSocketResponse \
        <https://aiohttp.readthedocs.io/en/stable\
        /client_reference.html#aiohttp.ClientWebSocketResponse>`_
        """
        if channel in self._long_duration_channels:
            factory = self._socket_factory_long
        else:
            factory = self._socket_factory_short

        return await factory(self.endpoint, ssl=self.ssl, headers=headers,
                             receive_timeout=self.request_timeout)

    def _get_socket_lock(self, channel):
        """Get an exclusive lock object for the given *channel*

        :param str channel: CometD channel name
        :return: lock object for the *channel*
        :rtype: asyncio.Lock
        """
        if channel in self._long_duration_channels:
            return self._socket_lock_long
        return self._socket_lock_short

    async def _reset_sockets(self):
        """Close all socket factories and recreate them"""
        await self._socket_factory_short.close()
        self._socket_factory_short = WebSocketFactory(self._get_http_session)
        await self._socket_factory_long.close()
        self._socket_factory_long = WebSocketFactory(self._get_http_session)

    async def _send_final_payload(self, payload, *, headers):
        try:
            # the channel of the first message
            channel = payload[0]["channel"]
            # lock the socket until we're done sending the payload and
            # receiving the response
            lock = self._get_socket_lock(channel)
            async with lock:
                try:
                    # try to send the payload on the socket which might have
                    # been closed since the last time it was used
                    socket = await self._get_socket(channel, headers)
                    return await self._send_socket_payload(socket, payload)
                except asyncio.TimeoutError:
                    # reset all socket factories since after a timeout error
                    # most likely all of them are invalid
                    await self._reset_sockets()
                    raise
                except TransportConnectionClosed:
                    # if the socket was indeed closed, try to reopen the socket
                    # and send the payload, since the connection could've
                    # normalised since the last network problem
                    socket = await self._get_socket(channel, headers)
                    return await self._send_socket_payload(socket, payload)

        except aiohttp.client_exceptions.ClientError as error:
            LOGGER.warning("Failed to send payload, %s", error)
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
        :raises TransportConnectionClosed: When the *socket* receives a CLOSE \
        message instead of the expected response
        """
        # receive responses from the server and consume them,
        # until we get back the response for the first message in the *payload*
        await socket.send_json(payload, dumps=self._json_dumps)
        while True:
            response = await socket.receive()
            if response.type == aiohttp.WSMsgType.CLOSE:
                raise TransportConnectionClosed("Received CLOSE message on "
                                                "the factory.")
            response_payload = response.json(loads=self._json_loads)
            matching_response = await self._consume_payload(
                response_payload,
                headers=None,
                find_response_for=payload[0])
            if matching_response:
                return matching_response

    async def close(self):
        await self._socket_factory_short.close()
        await self._socket_factory_long.close()
        await super().close()
