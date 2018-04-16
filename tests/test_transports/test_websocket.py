from asynctest import TestCase, mock

from aiohttp import client_exceptions, WSMsgType

from aiocometd.transports.websocket import WebSocketTransport, _WebSocket
from aiocometd.transports.constants import ConnectionType, MetaChannel
from aiocometd.exceptions import TransportConnectionClosed, TransportError


class TestWebSocket(TestCase):
    def setUp(self):
        self.session = mock.CoroutineMock()
        self.session_factory = mock.CoroutineMock(return_value=self.session)
        self.url = "http://example.com/"
        self.websocket = _WebSocket(self.session_factory, self.url)

    async def test_enter(self):
        socket = object()
        context = mock.MagicMock()
        context.__aenter__ = mock.CoroutineMock(return_value=socket)
        self.session.ws_connect.return_value = context

        await self.websocket._enter()

        self.session.ws_connect.assert_called_with(
            self.url,
            headers=self.websocket._headers
        )
        self.assertEqual(self.websocket._context, context)
        self.assertEqual(self.websocket._socket, socket)

    async def test_exit(self):
        socket = object()
        context = mock.MagicMock()
        context.__aexit__ = mock.CoroutineMock(return_value=socket)
        self.websocket._context = context
        self.websocket._socket = socket

        await self.websocket._exit()

        context.__aexit__.assert_called()
        self.assertIsNone(self.websocket._context)
        self.assertIsNone(self.websocket._socket)

    async def test_close(self):
        self.websocket._exit = mock.CoroutineMock()

        await self.websocket.close()

        self.websocket._exit.assert_called()

    async def test_get_socket_creates_socket(self):
        self.websocket._enter = mock.CoroutineMock()
        headers = {}

        await self.websocket.get_socket(headers)

        self.websocket._enter.assert_called()
        self.assertIs(self.websocket._headers, headers)

    async def test_get_socket_returns_open_socket(self):
        self.websocket._enter = mock.CoroutineMock()
        socket = mock.MagicMock()
        socket.closed = False
        self.websocket._socket = socket
        headers = {}

        result = await self.websocket.get_socket(headers)

        self.assertEqual(result, socket)
        self.websocket._enter.assert_not_called()
        self.assertIs(self.websocket._headers, headers)

    async def test_get_socket_creates_new_if_closed(self):
        self.websocket._exit = mock.CoroutineMock()
        socket = mock.MagicMock()
        socket.closed = True
        self.websocket._socket = socket
        headers = {}

        await self.websocket.get_socket(headers)

        self.websocket._exit.assert_called()
        self.assertIs(self.websocket._headers, headers)


class TestWebSocketTransport(TestCase):
    def setUp(self):
        self.transport = WebSocketTransport(endpoint="example.com/cometd",
                                            incoming_queue=None,
                                            loop=None)

    def test_connection_type(self):
        self.assertEqual(self.transport.connection_type,
                         ConnectionType.WEBSOCKET)

    async def test_get_socket_for_short_request(self):
        channel = "/test/channel"
        self.assertNotIn(channel, self.transport._connect_task_channels)
        expected_socket = object()
        self.transport._websocket = mock.MagicMock()
        self.transport._websocket.get_socket = mock.CoroutineMock(
            return_value=expected_socket
        )
        headers = object()

        result = await self.transport._get_socket(channel, headers)

        self.assertIs(result, expected_socket)
        self.transport._websocket.get_socket.assert_called_with(headers)

    async def test_get_socket_for_long_duration_request(self):
        channel = MetaChannel.CONNECT
        self.assertIn(channel, self.transport._connect_task_channels)
        expected_socket = object()
        self.transport._connect_websocket = mock.MagicMock()
        self.transport._connect_websocket.get_socket = mock.CoroutineMock(
            return_value=expected_socket
        )
        headers = object()

        result = await self.transport._get_socket(channel, headers)

        self.assertIs(result, expected_socket)
        self.transport._connect_websocket.get_socket.assert_called_with(
            headers)

    def test_get_lock_for_short_request(self):
        channel = "/test/channel"
        self.assertNotIn(channel, self.transport._connect_task_channels)
        expected_lock = object()
        self.transport._websocket_lock = expected_lock

        result = self.transport._get_socket_lock(channel)

        self.assertIs(result, expected_lock)

    def test_get_lock_for_long_duration_request(self):
        channel = MetaChannel.CONNECT
        self.assertIn(channel, self.transport._connect_task_channels)
        expected_lock = object()
        self.transport._connect_websocket_lock = expected_lock

        result = self.transport._get_socket_lock(channel)

        self.assertIs(result, expected_lock)

    async def test_close(self):
        self.transport._websocket = mock.MagicMock()
        self.transport._websocket.close = mock.CoroutineMock()
        self.transport._connect_websocket = mock.MagicMock()
        self.transport._connect_websocket.close = mock.CoroutineMock()
        self.transport._close_http_session = mock.CoroutineMock()

        await self.transport.close()

        self.transport._websocket.close.assert_called()
        self.transport._connect_websocket.close.assert_called()
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

        socket.send_json.assert_called_with(payload)
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

        socket.send_json.assert_called_with(payload)
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

        with self.assertRaises(TransportConnectionClosed,
                               msg="Received CLOSE message on the websocket."):
            await self.transport._send_socket_payload(socket, payload)

        socket.send_json.assert_called_with(payload)
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
