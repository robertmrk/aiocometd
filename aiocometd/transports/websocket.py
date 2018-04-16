"""Websocket transport class definition"""
import asyncio
import logging

import aiohttp

from .constants import ConnectionType, MetaChannel
from .registry import register_transport
from .base import TransportBase
from ..exceptions import TransportError, TransportConnectionClosed


LOGGER = logging.getLogger(__name__)


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
class WebSocketTransport(TransportBase):
    """WebSocket type transport"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        #: channels used during the connect task, requests on these channels
        #: are usually long running
        self._connect_task_channels = (MetaChannel.HANDSHAKE,
                                       MetaChannel.CONNECT)
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
        return await self._websocket.get_socket(headers)

    def _get_socket_lock(self, channel):
        """Get an exclusive lock object for the given *channel*

        :param str channel: CometD channel name
        :return: lock object for the *channel*
        :rtype: asyncio.Lock
        """
        if channel in self._connect_task_channels:
            return self._connect_websocket_lock
        return self._websocket_lock

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
        await socket.send_json(payload)
        while True:
            response = await socket.receive()
            if response.type == aiohttp.WSMsgType.CLOSE:
                raise TransportConnectionClosed("Received CLOSE message on "
                                                "the websocket.")
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
        await super().close()
