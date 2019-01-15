import asyncio
from asynctest import TestCase, mock

from aiohttp import client_exceptions, WSMsgType

from aiocometd.transports.websocket import WebSocketTransport, WebSocketFactory
from aiocometd.constants import ConnectionType, MetaChannel
from aiocometd.exceptions import TransportConnectionClosed, TransportError


class TestWebSocketFactory(TestCase):
    def setUp(self):
        self.session = mock.CoroutineMock()
        self.session_factory = mock.CoroutineMock(return_value=self.session)
        self.url = "http://example.com/"
        self.factory = WebSocketFactory(self.session_factory)

    async def test_enter(self):
        socket = object()
        context = mock.MagicMock()
        context.__aenter__ = mock.CoroutineMock(return_value=socket)
        self.session.ws_connect.return_value = context
        args = [object()]
        kwargs = {"key": "value"}

        result = await self.factory._enter(*args, **kwargs)

        self.session.ws_connect.assert_called_with(*args, **kwargs)
        self.assertEqual(self.factory._context, context)
        self.assertEqual(result, socket)

    async def test_exit(self):
        socket = object()
        context = mock.MagicMock()
        context.__aexit__ = mock.CoroutineMock(return_value=socket)
        self.factory._context = context
        self.factory._socket = socket

        await self.factory._exit()

        context.__aexit__.assert_called()
        self.assertIsNone(self.factory._context)
        self.assertIsNone(self.factory._socket)

    async def test_exit_none_context(self):
        self.factory._context = None

        await self.factory._exit()

    async def test_close(self):
        self.factory._exit = mock.CoroutineMock()

        await self.factory.close()

        self.factory._exit.assert_called()

    async def test_close_supresses_errors(self):
        self.factory._exit = mock.CoroutineMock(side_effect=AttributeError())

        await self.factory.close()

        self.factory._exit.assert_called()

    async def test_call_socket_creates_socket(self):
        self.factory._enter = mock.CoroutineMock()
        args = [object()]
        kwargs = {"key": "value"}

        await self.factory(*args, **kwargs)

        self.factory._enter.assert_called_with(*args, **kwargs)
        self.assertEqual(self.factory._socket,
                         self.factory._enter.return_value)

    async def test_call_socket_returns_open_socket(self):
        self.factory._enter = mock.CoroutineMock()
        socket = mock.MagicMock()
        socket.closed = False
        self.factory._socket = socket

        result = await self.factory()

        self.assertEqual(result, socket)
        self.factory._enter.assert_not_called()

    async def test_call_socket_creates_new_if_closed(self):
        self.factory._exit = mock.CoroutineMock()
        socket = mock.MagicMock()
        socket.closed = True
        self.factory._socket = socket

        await self.factory()

        self.factory._exit.assert_called()


class TestWebSocketTransport(TestCase):
    def setUp(self):
        self.transport = WebSocketTransport(url="example.com/cometd",
                                            incoming_queue=None,
                                            loop=None)

    def test_connection_type(self):
        self.assertEqual(self.transport.connection_type,
                         ConnectionType.WEBSOCKET)

    async def test_get_socket_for_short_request(self):
        channel = "/test/channel"
        self.assertNotIn(channel, self.transport._long_duration_channels)
        expected_socket = object()
        self.transport._socket_factory_short = mock.CoroutineMock(
            return_value=expected_socket
        )
        headers = object()

        result = await self.transport._get_socket(channel, headers)

        self.assertIs(result, expected_socket)
        self.transport._socket_factory_short.assert_called_with(
            self.transport._url,
            ssl=self.transport.ssl,
            headers=headers,
            receive_timeout=self.transport.request_timeout
        )

    async def test_get_socket_for_long_duration_request(self):
        channel = MetaChannel.CONNECT
        self.assertIn(channel, self.transport._long_duration_channels)
        expected_socket = object()
        self.transport._socket_factory_long = mock.CoroutineMock(
            return_value=expected_socket
        )
        headers = object()

        result = await self.transport._get_socket(channel, headers)

        self.assertIs(result, expected_socket)
        self.transport._socket_factory_long.assert_called_with(
            self.transport._url,
            ssl=self.transport.ssl,
            headers=headers,
            receive_timeout=self.transport.request_timeout
        )

    def test_get_lock_for_short_request(self):
        channel = "/test/channel"
        self.assertNotIn(channel, self.transport._long_duration_channels)
        expected_lock = object()
        self.transport._socket_lock_short = expected_lock

        result = self.transport._get_socket_lock(channel)

        self.assertIs(result, expected_lock)

    def test_get_lock_for_long_duration_request(self):
        channel = MetaChannel.CONNECT
        self.assertIn(channel, self.transport._long_duration_channels)
        expected_lock = object()
        self.transport._socket_lock_long = expected_lock

        result = self.transport._get_socket_lock(channel)

        self.assertIs(result, expected_lock)

    async def test_close(self):
        self.transport._socket_factory_short = mock.MagicMock()
        self.transport._socket_factory_short.close = mock.CoroutineMock()
        self.transport._socket_factory_long = mock.MagicMock()
        self.transport._socket_factory_long.close = mock.CoroutineMock()
        self.transport._close_http_session = mock.CoroutineMock()

        await self.transport.close()

        self.transport._socket_factory_short.close.assert_called()
        self.transport._socket_factory_long.close.assert_called()
        self.transport._close_http_session.assert_called()

    async def test_send_socket_payload_short_request(self):
        matching_response = object()
        payload = [object()]
        socket = mock.MagicMock()
        socket.send_json = mock.CoroutineMock()
        response_payload = object()
        response = mock.MagicMock()
        response.json = mock.MagicMock(return_value=response_payload)
        socket.receive = mock.CoroutineMock(return_value=response)
        self.transport._consume_payload = mock.CoroutineMock(
            return_value=matching_response
        )

        await self.transport._send_socket_payload(socket, payload)

        socket.send_json.assert_called_with(payload,
                                            dumps=self.transport._json_dumps)
        response.json.assert_called_with(loads=self.transport._json_loads)
        self.transport._consume_payload.assert_called_with(
            response_payload,
            headers=None,
            find_response_for=payload[0]
        )

    async def test_send_socket_payload_long_duration_request(self):
        matching_response = object()
        payload = [object()]
        socket = mock.MagicMock()
        socket.send_json = mock.CoroutineMock()
        response_payload = object()
        response = mock.MagicMock()
        response.json = mock.MagicMock(return_value=response_payload)
        socket.receive = mock.CoroutineMock(side_effect=[response, response])
        self.transport._consume_payload = mock.CoroutineMock(
            side_effect=[False, matching_response]
        )

        await self.transport._send_socket_payload(socket, payload)

        socket.send_json.assert_called_with(payload,
                                            dumps=self.transport._json_dumps)
        response.json.assert_called_with(loads=self.transport._json_loads)
        self.transport._consume_payload.assert_called_with(
            response_payload,
            headers=None,
            find_response_for=payload[0]
        )

    async def test_send_socket_payload_socket_closed(self):
        matching_response = object()
        payload = [object()]
        socket = mock.MagicMock()
        socket.send_json = mock.CoroutineMock()
        response = mock.MagicMock()
        response.type = WSMsgType.CLOSE
        socket.receive = mock.CoroutineMock(return_value=response)
        self.transport._consume_payload = mock.CoroutineMock(
            return_value=matching_response
        )

        with self.assertRaisesRegex(TransportConnectionClosed,
                                    "Received CLOSE message on the "
                                    "factory."):
            await self.transport._send_socket_payload(socket, payload)

        socket.send_json.assert_called_with(payload,
                                            dumps=self.transport._json_dumps)
        self.transport._consume_payload.assert_not_called()

    async def test_send_socket_payload_invalid_response(self):
        payload = [object()]
        socket = mock.MagicMock()
        socket.send_json = mock.CoroutineMock()
        response = mock.MagicMock()
        response.json = mock.MagicMock(side_effect=TypeError())
        socket.receive = mock.CoroutineMock(return_value=response)
        self.transport._consume_payload = mock.CoroutineMock()

        with self.assertRaisesRegex(TransportError,
                                    "Received invalid response from the "
                                    "server."):
            await self.transport._send_socket_payload(socket, payload)

        socket.send_json.assert_called_with(payload,
                                            dumps=self.transport._json_dumps)
        response.json.assert_called_with(loads=self.transport._json_loads)
        self.transport._consume_payload.assert_not_called()

    async def test_send_final_payload(self):
        channel = "channel"
        payload = [dict(channel=channel)]
        lock = mock.MagicMock()
        socket = object()
        response = object()
        self.transport._get_socket = mock.CoroutineMock(return_value=socket)
        self.transport._get_socket_lock = mock.MagicMock(return_value=lock)
        self.transport._send_socket_payload = \
            mock.CoroutineMock(return_value=response)
        headers = object()

        result = await self.transport._send_final_payload(payload,
                                                          headers=headers)

        self.assertEqual(result, response)
        self.transport._get_socket.assert_called_with(channel, headers)
        self.transport._get_socket_lock.assert_called_with(channel)
        lock.__aenter__.assert_called()
        lock.__aexit__.assert_called()
        self.transport._send_socket_payload.assert_called_with(socket,
                                                               payload)

    async def test_send_final_payload_transport_error(self):
        channel = "channel"
        payload = [dict(channel=channel)]
        lock = mock.MagicMock()
        socket = object()
        exception = client_exceptions.ClientError("message")
        self.transport._get_socket = mock.CoroutineMock(return_value=socket)
        self.transport._get_socket_lock = mock.MagicMock(return_value=lock)
        self.transport._send_socket_payload = \
            mock.CoroutineMock(side_effect=exception)
        headers = object()

        with self.assertLogs(WebSocketTransport.__module__,
                             level="DEBUG") as log:
            with self.assertRaisesRegex(TransportError, str(exception)):
                await self.transport._send_final_payload(payload,
                                                         headers=headers)

        log_message = "WARNING:{}:Failed to send payload, {}"\
            .format(WebSocketTransport.__module__, exception)
        self.assertEqual(log.output, [log_message])
        self.transport._get_socket.assert_called_with(channel, headers)
        self.transport._get_socket_lock.assert_called_with(channel)
        lock.__aenter__.assert_called()
        lock.__aexit__.assert_called()
        self.transport._send_socket_payload.assert_called_with(socket,
                                                               payload)

    async def test_send_final_payload_connection_closed_error(self):
        channel = "channel"
        payload = [dict(channel=channel)]
        lock = mock.MagicMock()
        socket = object()
        socket2 = object()
        response = object()
        self.transport._get_socket = mock.CoroutineMock(
            side_effect=[socket, socket2])
        self.transport._get_socket_lock = mock.MagicMock(return_value=lock)
        error = TransportConnectionClosed()
        self.transport._send_socket_payload = \
            mock.CoroutineMock(side_effect=[error, response])
        headers = object()

        result = await self.transport._send_final_payload(payload,
                                                          headers=headers)

        self.assertEqual(result, response)
        self.transport._get_socket.assert_has_calls([
            mock.call(channel, headers), mock.call(channel, headers)])
        self.transport._get_socket_lock.assert_called_with(channel)
        lock.__aenter__.assert_called()
        lock.__aexit__.assert_called()
        self.transport._send_socket_payload.assert_has_calls([
            mock.call(socket, payload), mock.call(socket2, payload)
        ])

    async def test_send_final_payload_connection_timeout_error(self):
        channel = "channel"
        payload = [dict(channel=channel)]
        lock = mock.MagicMock()
        socket = object()
        self.transport._get_socket = mock.CoroutineMock(return_value=socket)
        self.transport._get_socket_lock = mock.MagicMock(return_value=lock)
        error = asyncio.TimeoutError()
        self.transport._send_socket_payload = \
            mock.CoroutineMock(side_effect=error)
        headers = object()
        self.transport._reset_sockets = mock.CoroutineMock()

        with self.assertRaises(asyncio.TimeoutError):
            await self.transport._send_final_payload(payload, headers=headers)

        self.transport._get_socket.assert_called_with(channel, headers)
        self.transport._get_socket_lock.assert_called_with(channel)
        lock.__aenter__.assert_called()
        lock.__aexit__.assert_called()
        self.transport._send_socket_payload.assert_called_with(socket, payload)
        self.transport._reset_sockets.assert_called()

    @mock.patch("aiocometd.transports.websocket.WebSocketFactory")
    async def test_reset_sockets(self, ws_factory_cls):
        factory_short = object()
        factory_long = object()
        ws_factory_cls.side_effect = [factory_short, factory_long]
        old_factory_short = mock.MagicMock()
        old_factory_short.close = mock.CoroutineMock()
        self.transport._socket_factory_short = old_factory_short
        old_factory_long = mock.MagicMock()
        old_factory_long.close = mock.CoroutineMock()
        self.transport._socket_factory_long = old_factory_long

        await self.transport._reset_sockets()

        old_factory_short.close.assert_called()
        old_factory_long.close.assert_called()
        self.assertIs(self.transport._socket_factory_short, factory_short)
        self.assertIs(self.transport._socket_factory_long, factory_long)
        ws_factory_cls.assert_has_calls([
            mock.call(self.transport._get_http_session),
            mock.call(self.transport._get_http_session)
        ])
