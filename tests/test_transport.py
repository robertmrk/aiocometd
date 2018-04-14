import asyncio

from asynctest import TestCase, mock
from aiohttp import ClientSession, client_exceptions, WSMsgType

from aiocometd.transport import LongPollingTransport, TransportState, \
    _TransportBase, _WebSocket, WebSocketTransport, register_transport, \
    transport_classes, create_transport, ConnectionType
from aiocometd.exceptions import TransportError, TransportInvalidOperation, \
    TransportConnectionClosed
from aiocometd.extension import Extension, AuthExtension


class TransportBase(_TransportBase):
    async def _send_final_payload(self, payload):
        pass

    @property
    def connection_type(self):
        return ConnectionType.LONG_POLLING


class TestTransportBase(TestCase):
    def setUp(self):
        self.transport = TransportBase(endpoint="example.com/cometd",
                                       incoming_queue=None,
                                       loop=None)

    async def long_task(self, result, timeout=None):
        if timeout:
            await asyncio.sleep(timeout, loop=self.loop)
        if not isinstance(result, Exception):
            return result
        else:
            raise result

    def test_init_with_loop(self):
        loop = object()

        transport = TransportBase(endpoint=None,
                                  incoming_queue=None,
                                  loop=loop)

        self.assertIs(transport._loop, loop)
        self.assertEqual(transport.state, TransportState.DISCONNECTED)

    @mock.patch("aiocometd.transport.asyncio")
    def test_init_without_loop(self, asyncio_mock):
        loop = object()
        asyncio_mock.get_event_loop.return_value = loop

        transport = TransportBase(endpoint=None,
                                  incoming_queue=None)

        self.assertIs(transport._loop, loop)
        self.assertEqual(transport.state, TransportState.DISCONNECTED)

    async def test_get_http_session(self):
        self.transport._http_session = ClientSession()

        session = await self.transport._get_http_session()

        self.assertIsInstance(session, ClientSession)
        await session.close()

    async def test_get_http_session_creates_session(self):
        self.transport._http_session = None

        session = await self.transport._get_http_session()

        self.assertIsInstance(session, ClientSession)
        await session.close()

    @mock.patch("aiocometd.transport.asyncio")
    async def test_close_http_session(self, asyncio_mock):
        self.transport._http_session = mock.MagicMock()
        self.transport._http_session.closed = False
        self.transport._http_session.close = mock.CoroutineMock()
        asyncio_mock.sleep = mock.CoroutineMock()

        await self.transport._close_http_session()

        self.transport._http_session.close.assert_called()
        asyncio_mock.sleep.assert_called_with(
            self.transport._HTTP_SESSION_CLOSE_TIMEOUT)

    def test_finalize_message_updates_fields(self):
        message = {
            "field": "value",
            "id": None,
            "clientId": None,
            "connectionType": None
        }
        self.transport._client_id = "client_id"

        self.transport._finalize_message(message)

        self.assertEqual(message["id"], str(0))
        self.assertEqual(self.transport._message_id, 1)
        self.assertEqual(message["clientId"], self.transport.client_id)
        self.assertEqual(message["connectionType"],
                         self.transport.connection_type.value)

    def test_finalize_message_ignores_non_existing_fields(self):
        message = {
            "field": "value"
        }
        self.transport._client_id = "client_id"

        self.transport._finalize_message(message)

        self.assertEqual(list(message.keys()), ["field"])
        self.assertEqual(message["field"], "value")

    def test_finalize_payload_single_message(self):
        payload = {
            "field": "value",
            "id": None,
            "clientId": None
        }
        self.transport._finalize_message = mock.MagicMock()

        self.transport._finalize_payload(payload)

        self.transport._finalize_message.assert_called_once_with(payload)

    def test_finalize_payload_multiple_messages(self):
        payload = [
            {
                "field": "value",
                "id": None,
                "clientId": None,
                "connectionType": None
            },
            {
                "field2": "value2",
                "id": None,
                "clientId": None,
                "connectionType": None
            }
        ]
        self.transport._finalize_message = mock.MagicMock()

        self.transport._finalize_payload(payload)

        self.transport._finalize_message.assert_has_calls([
            mock.call(payload[0]), mock.call(payload[1])
        ])

    def test_is_matching_response(self):
        message = {
            "channel": "/test/channel1",
            "data": {},
            "clientId": "clientId",
            "id": "1"
        }
        response = {
            "channel": "/test/channel1",
            "successful": True,
            "clientId": "clientId",
            "id": "1"
        }

        self.assertTrue(self.transport._is_matching_response(response,
                                                             message))

    def test_is_matching_response_response_none(self):
        message = {
            "channel": "/test/channel1",
            "data": {},
            "clientId": "clientId",
            "id": "1"
        }
        response = None

        self.assertFalse(self.transport._is_matching_response(response,
                                                              message))

    def test_is_matching_response_message_none(self):
        message = None
        response = {
            "channel": "/test/channel1",
            "successful": True,
            "clientId": "clientId",
            "id": "1"
        }

        self.assertFalse(self.transport._is_matching_response(response,
                                                              message))

    def test_is_matching_response_without_id(self):
        message = {
            "channel": "/test/channel1",
            "data": {},
            "clientId": "clientId",
        }
        response = {
            "channel": "/test/channel1",
            "successful": True,
            "clientId": "clientId",
        }

        self.assertTrue(self.transport._is_matching_response(response,
                                                             message))

    def test_is_matching_response_different_id(self):
        message = {
            "channel": "/test/channel1",
            "data": {},
            "clientId": "clientId",
            "id": "1"
        }
        response = {
            "channel": "/test/channel1",
            "successful": True,
            "clientId": "clientId",
            "id": "2"
        }

        self.assertFalse(self.transport._is_matching_response(response,
                                                              message))

    def test_is_matching_response_different_channel(self):
        message = {
            "channel": "/test/channel1",
            "data": {},
            "clientId": "clientId",
            "id": "1"
        }
        response = {
            "channel": "/test/channel2",
            "successful": True,
            "clientId": "clientId",
            "id": "1"
        }

        self.assertFalse(self.transport._is_matching_response(response,
                                                              message))

    def test_is_matching_response_without_successful_field(self):
        message = {
            "channel": "/test/channel1",
            "data": {},
            "clientId": "clientId",
            "id": "1"
        }
        response = {
            "channel": "/test/channel1",
            "clientId": "clientId",
            "id": "1"
        }

        self.assertFalse(self.transport._is_matching_response(response,
                                                              message))

    def assert_server_error_message_for_channel(self, channel, successful,
                                                expected_result):
        message = {
            "channel": channel,
            "successful": successful
        }

        result = self.transport._is_server_error_message(message)

        self.assertEqual(result, expected_result)

    def test_is_server_error_message_subscribe(self):
        channel = "/meta/subscribe"
        self.assert_server_error_message_for_channel(channel, False, True)
        self.assert_server_error_message_for_channel(channel, True, False)

    def test_is_server_error_message_unsubscribe(self):
        channel = "/meta/unsubscribe"
        self.assert_server_error_message_for_channel(channel, False, True)
        self.assert_server_error_message_for_channel(channel, True, False)

    def test_is_server_error_message_non_meta_channel(self):
        channel = "/test/channel"
        self.assert_server_error_message_for_channel(channel, False, True)
        self.assert_server_error_message_for_channel(channel, True, False)

    def test_is_server_error_message_service_channel(self):
        channel = "/service/test"
        self.assert_server_error_message_for_channel(channel, False, True)
        self.assert_server_error_message_for_channel(channel, True, False)

    def test_is_server_error_message_handshake(self):
        channel = "/meta/handshake"
        self.assert_server_error_message_for_channel(channel, False, False)
        self.assert_server_error_message_for_channel(channel, True, False)

    def test_is_server_error_message_connect(self):
        channel = "/meta/connect"
        self.assert_server_error_message_for_channel(channel, False, False)
        self.assert_server_error_message_for_channel(channel, True, False)

    def test_is_server_error_message_disconnect(self):
        channel = "/meta/disconnect"
        self.assert_server_error_message_for_channel(channel, False, False)
        self.assert_server_error_message_for_channel(channel, True, False)

    def assert_event_message_for_channel(self, channel, has_data,
                                         expected_result):
        message = dict(channel=channel)
        if has_data:
            message["data"] = None

        result = self.transport._is_event_message(message)

        self.assertEqual(result, expected_result)

    def test_is_event_message_subscribe(self):
        channel = "/meta/subscribe"
        self.assert_event_message_for_channel(channel, False, False)
        self.assert_event_message_for_channel(channel, True, False)

    def test_is_event_message_unsubscribe(self):
        channel = "/meta/unsubscribe"
        self.assert_event_message_for_channel(channel, False, False)
        self.assert_event_message_for_channel(channel, True, False)

    def test_is_event_message_non_meta_channel(self):
        channel = "/test/channel"
        self.assert_event_message_for_channel(channel, False, False)
        self.assert_event_message_for_channel(channel, True, True)

    def test_is_event_message_service_channel(self):
        channel = "/service/test"
        self.assert_event_message_for_channel(channel, False, False)
        self.assert_event_message_for_channel(channel, True, False)

    def test_is_event_message_handshake(self):
        channel = "/meta/handshake"
        self.assert_event_message_for_channel(channel, False, False)
        self.assert_event_message_for_channel(channel, True, False)

    def test_is_event_message_connect(self):
        channel = "/meta/connect"
        self.assert_event_message_for_channel(channel, False, False)
        self.assert_event_message_for_channel(channel, True, False)

    def test_is_event_message_disconnect(self):
        channel = "/meta/disconnect"
        self.assert_event_message_for_channel(channel, False, False)
        self.assert_event_message_for_channel(channel, True, False)

    def test_consume_message(self):
        self.transport._is_event_message = mock.MagicMock(return_value=False)
        self.transport._is_server_error_message = \
            mock.MagicMock(return_value=False)
        self.transport._enqueue_message = mock.MagicMock()
        response_message = object()

        self.transport._consume_message(response_message)

        self.transport._is_server_error_message.assert_called_with(
            response_message)
        self.transport._is_event_message.assert_called_with(response_message)
        self.transport._enqueue_message.assert_not_called()

    def test_consume_message_event_message(self):
        self.transport._is_event_message = mock.MagicMock(return_value=True)
        self.transport._is_server_error_message = \
            mock.MagicMock(return_value=False)
        self.transport._enqueue_message = mock.MagicMock()
        response_message = object()

        self.transport._consume_message(response_message)

        self.transport._is_event_message.assert_called_with(response_message)
        self.transport._enqueue_message.assert_called_with(response_message)

    def test_consume_message_server_error_message(self):
        self.transport._is_event_message = mock.MagicMock(return_value=False)
        self.transport._is_server_error_message = \
            mock.MagicMock(return_value=True)
        self.transport._enqueue_message = mock.MagicMock()
        response_message = object()

        self.transport._consume_message(response_message)

        self.transport._is_server_error_message.assert_called_with(
            response_message)
        self.transport._enqueue_message.assert_called_with(response_message)

    def test_update_subscriptions_new_subscription_success(self):
        response_message = {
            "channel": "/meta/subscribe",
            "subscription": "/test/channel1",
            "successful": True,
            "id": "3"
        }
        self.transport._subscriptions = set()

        self.transport._update_subscriptions(response_message)

        self.assertEqual(self.transport.subscriptions,
                         set([response_message["subscription"]]))

    def test_update_subscriptions_existing_subscription_success(self):
        response_message = {
            "channel": "/meta/subscribe",
            "subscription": "/test/channel1",
            "successful": True,
            "id": "3"
        }
        self.transport._subscriptions = set([response_message["subscription"]])

        self.transport._update_subscriptions(response_message)

        self.assertEqual(self.transport.subscriptions,
                         set([response_message["subscription"]]))

    def test_update_subscriptions_new_subscription_fail(self):
        response_message = {
            "channel": "/meta/subscribe",
            "subscription": "/test/channel1",
            "successful": False,
            "id": "3"
        }
        self.transport._subscriptions = set()

        self.transport._update_subscriptions(response_message)

        self.assertEqual(self.transport.subscriptions, set())

    def test_update_subscriptions_existing_subscription_fail(self):
        response_message = {
            "channel": "/meta/subscribe",
            "subscription": "/test/channel1",
            "successful": False,
            "id": "3"
        }
        self.transport._subscriptions = set([response_message["subscription"]])

        self.transport._update_subscriptions(response_message)

        self.assertEqual(self.transport.subscriptions, set())

    def test_update_subscriptions_new_unsubscription_success(self):
        response_message = {
            "channel": "/meta/unsubscribe",
            "subscription": "/test/channel1",
            "successful": True,
            "id": "3"
        }
        self.transport._subscriptions = set()

        self.transport._update_subscriptions(response_message)

        self.assertEqual(self.transport.subscriptions, set())

    def test_update_subscriptions_existing_unsubscription_success(self):
        response_message = {
            "channel": "/meta/unsubscribe",
            "subscription": "/test/channel1",
            "successful": True,
            "id": "3"
        }
        self.transport._subscriptions = set([response_message["subscription"]])

        self.transport._update_subscriptions(response_message)

        self.assertEqual(self.transport.subscriptions, set())

    def test_update_subscriptions_new_unsubscription_fail(self):
        response_message = {
            "channel": "/meta/unsubscribe",
            "subscription": "/test/channel1",
            "successful": False,
            "id": "3"
        }
        self.transport._subscriptions = set()

        self.transport._update_subscriptions(response_message)

        self.assertEqual(self.transport.subscriptions, set())

    def test_update_subscriptions_existing_unsubscription_fail(self):
        response_message = {
            "channel": "/meta/unsubscribe",
            "subscription": "/test/channel1",
            "successful": False,
            "id": "3"
        }
        self.transport._subscriptions = set([response_message["subscription"]])

        self.transport._update_subscriptions(response_message)

        self.assertEqual(self.transport.subscriptions,
                         set([response_message["subscription"]]))

    async def test_consume_payload_matching_without_advice(self):
        payload = [
            {
                "channel": "/meta/connect",
                "successful": True,
                "id": "1"
            }
        ]
        message = object()
        self.transport._update_subscriptions = mock.MagicMock()
        self.transport._is_matching_response = \
            mock.MagicMock(return_value=True)
        self.transport._consume_message = mock.MagicMock()

        result = await self.transport._consume_payload(
            payload, find_response_for=message)

        self.assertEqual(result, payload[0])
        self.assertEqual(self.transport._reconnect_advice, {})
        self.transport._update_subscriptions.assert_called_with(payload[0])
        self.transport._is_matching_response.assert_called_with(payload[0],
                                                                message)
        self.transport._consume_message.assert_not_called()

    async def test_process_incoming_payload(self):
        extension = mock.create_autospec(spec=Extension)
        auth = mock.create_autospec(spec=AuthExtension)
        self.transport._extensions = [extension]
        self.transport._auth = auth
        payload = object()
        headers = object()

        await self.transport._process_incoming_payload(payload, headers)

        extension.incoming.assert_called_with(payload, headers)
        auth.incoming.assert_called_with(payload, headers)

    async def test_consume_payload_matching_without_advice_extension(self):
        payload = [
            {
                "channel": "/meta/connect",
                "successful": True,
                "id": "1"
            }
        ]
        message = object()
        self.transport._update_subscriptions = mock.MagicMock()
        self.transport._is_matching_response = \
            mock.MagicMock(return_value=True)
        self.transport._consume_message = mock.MagicMock()
        self.transport._process_incoming_payload = mock.CoroutineMock()
        headers = object()

        result = await self.transport._consume_payload(
            payload, headers=headers, find_response_for=message)

        self.assertEqual(result, payload[0])
        self.assertEqual(self.transport._reconnect_advice, {})
        self.transport._update_subscriptions.assert_called_with(payload[0])
        self.transport._is_matching_response.assert_called_with(payload[0],
                                                                message)
        self.transport._consume_message.assert_not_called()
        self.transport._process_incoming_payload.assert_called_with(payload,
                                                                    headers)

    async def test_consume_payload_matching_with_advice(self):
        payload = [
            {
                "channel": "/meta/connect",
                "successful": True,
                "advice": {"interval": 0, "reconnect": "retry"},
                "id": "1"
            }
        ]
        message = object()
        self.transport._update_subscriptions = mock.MagicMock()
        self.transport._is_matching_response = \
            mock.MagicMock(return_value=True)
        self.transport._consume_message = mock.MagicMock()
        self.transport._process_incoming_payload = mock.CoroutineMock()

        result = await self.transport._consume_payload(
            payload, find_response_for=message)

        self.assertEqual(result, payload[0])
        self.assertEqual(self.transport._reconnect_advice,
                         payload[0]["advice"])
        self.transport._update_subscriptions.assert_called_with(payload[0])
        self.transport._is_matching_response.assert_called_with(payload[0],
                                                                message)
        self.transport._consume_message.assert_not_called()
        self.transport._process_incoming_payload.assert_called_with(payload,
                                                                    None)

    async def test_consume_payload_non_matching(self):
        payload = [
            {
                "channel": "/meta/connect",
                "successful": True,
                "id": "1"
            }
        ]
        message = None
        self.transport._update_subscriptions = mock.MagicMock()
        self.transport._is_matching_response = \
            mock.MagicMock(return_value=False)
        self.transport._consume_message = mock.MagicMock()
        self.transport._process_incoming_payload = mock.CoroutineMock()

        result = await self.transport._consume_payload(
            payload, find_response_for=message)

        self.assertIsNone(result)
        self.assertEqual(self.transport._reconnect_advice, {})
        self.transport._update_subscriptions.assert_called_with(payload[0])
        self.transport._is_matching_response.assert_called_with(payload[0],
                                                                message)
        self.transport._consume_message.assert_called_with(payload[0])
        self.transport._process_incoming_payload.assert_called_with(payload,
                                                                    None)

    def test_enqueu_message(self):
        self.transport.incoming_queue = mock.MagicMock()
        self.transport.incoming_queue.put_nowait = mock.CoroutineMock()
        message = {
            "channel": "/test/channel1",
            "data": {"key": "value"},
            "id": "1"
        }

        self.transport._enqueue_message(message)

        self.transport.incoming_queue.put_nowait.assert_called_with(message)

    async def test_enqueu_message_queue_full(self):
        self.transport.incoming_queue = mock.MagicMock()
        self.transport.incoming_queue.put_nowait = mock.MagicMock(
            side_effect=asyncio.QueueFull()
        )
        message = {
            "channel": "/test/channel1",
            "data": {"key": "value"},
            "id": "1"
        }

        with self.assertLogs("aiocometd.transport", "DEBUG") as log:
            self.transport._enqueue_message(message)

        log_message = "WARNING:aiocometd.transport:Incoming message queue is "\
                      "full, dropping message: {!r}".format(message)
        self.assertEqual(log.output, [log_message])
        self.transport.incoming_queue.put_nowait.assert_called_with(message)

    async def test_send_message(self):
        message = {
            "channel": "/test/channel1",
            "data": {},
            "clientId": None,
            "id": "1"
        }
        response = object()
        self.transport._send_payload_with_auth = \
            mock.CoroutineMock(return_value=response)

        result = await self.transport._send_message(message,
                                                    field="value")

        self.assertIs(result, response)
        self.assertEqual(message["field"], "value")
        self.transport._send_payload_with_auth.assert_called_with([message])

    @mock.patch("aiocometd.transport.asyncio.sleep")
    async def test_handshake(self, sleep):
        connection_types = [ConnectionType.WEBSOCKET]
        response = {
            "clientId": "id1",
            "successful": True
        }
        self.transport._send_message = \
            mock.CoroutineMock(return_value=response)
        message = {
            "channel": "/meta/handshake",
            "version": "1.0",
            "supportedConnectionTypes": None,
            "minimumVersion": "1.0",
            "id": None
        }
        self.transport._subscribe_on_connect = False

        result = await self.transport._handshake(connection_types)

        self.assertEqual(result, response)
        sleep.assert_not_called()
        final_connection_types = [ConnectionType.WEBSOCKET.value,
                                  self.transport.connection_type.value]
        self.transport._send_message.assert_called_with(
            message,
            supportedConnectionTypes=final_connection_types)
        self.assertEqual(self.transport.client_id, response["clientId"])
        self.assertTrue(self.transport._subscribe_on_connect)

    @mock.patch("aiocometd.transport.asyncio.sleep")
    async def test_handshake_failure(self, sleep):
        connection_types = [ConnectionType.WEBSOCKET]
        response = {
            "clientId": "id1",
            "successful": False
        }
        self.transport._send_message = \
            mock.CoroutineMock(return_value=response)
        message = {
            "channel": "/meta/handshake",
            "version": "1.0",
            "supportedConnectionTypes": None,
            "minimumVersion": "1.0",
            "id": None
        }
        self.transport._subscribe_on_connect = False

        result = await self.transport._handshake(connection_types, 5)

        self.assertEqual(result, response)
        sleep.assert_called_with(5, loop=self.loop)
        final_connection_types = [ConnectionType.WEBSOCKET.value,
                                  self.transport.connection_type.value]
        self.transport._send_message.assert_called_with(
            message,
            supportedConnectionTypes=final_connection_types)
        self.assertEqual(self.transport.client_id, None)
        self.assertFalse(self.transport._subscribe_on_connect)

    async def test_public_handshake(self):
        self.transport._handshake = mock.CoroutineMock(return_value="result")
        connection_types = ["type1"]

        result = await self.transport.handshake(connection_types)

        self.assertEqual(result, "result")
        self.transport._handshake.assert_called_with(connection_types,
                                                     delay=None)

    def test_subscriptions(self):
        self.assertIs(self.transport.subscriptions,
                      self.transport._subscriptions)

    def test_subscriptions_read_only(self):
        with self.assertRaises(AttributeError):
            self.transport.subscriptions = {"channel1", "channel2"}

    @mock.patch("aiocometd.transport.asyncio.sleep")
    async def test__connect(self, sleep):
        self.transport._subscribe_on_connect = False
        response = {
            "channel": "/meta/connect",
            "successful": True,
            "advice": {"interval": 0, "reconnect": "retry"},
            "id": "2"
        }
        self.transport._send_payload_with_auth = \
            mock.CoroutineMock(return_value=response)

        result = await self.transport._connect()

        self.assertEqual(result, response)
        sleep.assert_not_called()
        self.transport._send_payload_with_auth.assert_called_with(
            [self.transport._CONNECT_MESSAGE])
        self.assertFalse(self.transport._subscribe_on_connect)

    @mock.patch("aiocometd.transport.asyncio.sleep")
    async def test__connect_with_delay(self, sleep):
        self.transport._subscribe_on_connect = False
        response = {
            "channel": "/meta/connect",
            "successful": True,
            "advice": {"interval": 0, "reconnect": "retry"},
            "id": "2"
        }
        self.transport._send_payload_with_auth = \
            mock.CoroutineMock(return_value=response)

        result = await self.transport._connect(5)

        self.assertEqual(result, response)
        sleep.assert_called_with(5, loop=self.transport._loop)
        self.transport._send_payload_with_auth.assert_called_with(
            [self.transport._CONNECT_MESSAGE])
        self.assertFalse(self.transport._subscribe_on_connect)

    async def test__connect_subscribe_on_connect(self):
        self.transport._subscribe_on_connect = True
        self.transport._subscriptions = {"/test/channel1", "/test/channel2"}
        response = {
            "channel": "/meta/connect",
            "successful": True,
            "advice": {"interval": 0, "reconnect": "retry"},
            "id": "2"
        }
        additional_messages = []
        for subscription in self.transport.subscriptions:
            message = self.transport._SUBSCRIBE_MESSAGE.copy()
            message["subscription"] = subscription
            additional_messages.append(message)
        self.transport._send_payload_with_auth = \
            mock.CoroutineMock(return_value=response)

        result = await self.transport._connect()

        self.assertEqual(result, response)
        self.transport._send_payload_with_auth.assert_called_with(
            [self.transport._CONNECT_MESSAGE] + additional_messages)
        self.assertFalse(self.transport._subscribe_on_connect)

    async def test__connect_subscribe_on_connect_error(self):
        self.transport._subscribe_on_connect = True
        self.transport._subscriptions = {"/test/channel1", "/test/channel2"}
        response = {
            "channel": "/meta/connect",
            "successful": False,
            "advice": {"interval": 0, "reconnect": "retry"},
            "id": "2"
        }
        additional_messages = []
        for subscription in self.transport.subscriptions:
            message = self.transport._SUBSCRIBE_MESSAGE.copy()
            message["subscription"] = subscription
            additional_messages.append(message)
        self.transport._send_payload_with_auth = \
            mock.CoroutineMock(return_value=response)

        result = await self.transport._connect()

        self.assertEqual(result, response)
        self.transport._send_payload_with_auth.assert_called_with(
            [self.transport._CONNECT_MESSAGE] + additional_messages)
        self.assertTrue(self.transport._subscribe_on_connect)

    def test_state(self):
        self.assertIs(self.transport.state,
                      self.transport._state)

    def test_state_read_only(self):
        with self.assertRaises(AttributeError):
            self.transport.state = TransportState.CONNECTING

    @mock.patch("aiocometd.transport.asyncio")
    async def test_start_connect_task(self, asyncio_mock):
        task = mock.MagicMock()
        asyncio_mock.ensure_future.return_value = task

        async def coro_func():
            pass
        coro = coro_func()

        result = self.transport._start_connect_task(coro)

        asyncio_mock.ensure_future.assert_called_with(
            coro,
            loop=self.transport._loop)
        self.assertEqual(self.transport._connect_task, task)
        task.add_done_callback.assert_called_with(self.transport._connect_done)
        self.assertEqual(result, task)
        await coro

    @mock.patch("aiocometd.transport.asyncio")
    async def test_stop_connect_task(self, asyncio_mock):
        self.transport._connect_task = mock.MagicMock()
        self.transport._connect_task.done.return_value = False
        asyncio_mock.wait = mock.CoroutineMock()

        await self.transport._stop_connect_task()

        self.transport._connect_task.cancel.assert_called()
        asyncio_mock.wait.assert_called_with([self.transport._connect_task])

    @mock.patch("aiocometd.transport.asyncio")
    async def test_stop_connect_task_with_none_task(self, asyncio_mock):
        self.transport._connect_task = None
        asyncio_mock.wait = mock.CoroutineMock()

        await self.transport._stop_connect_task()

        asyncio_mock.wait.assert_not_called()

    @mock.patch("aiocometd.transport.asyncio")
    async def test_stop_connect_task_with_done_task(self, asyncio_mock):
        self.transport._connect_task = mock.MagicMock()
        self.transport._connect_task.done.return_value = True
        asyncio_mock.wait = mock.CoroutineMock()

        await self.transport._stop_connect_task()

        asyncio_mock.wait.assert_not_called()

    async def test_connect_error_on_invalid_state(self):
        self.transport._client_id = "id"
        response = {
            "channel": "/meta/connect",
            "successful": True,
            "advice": {"interval": 0, "reconnect": "retry"},
            "id": "2"
        }
        self.transport._connect = mock.CoroutineMock(return_value=response)
        for state in TransportState:
            if state != TransportState.DISCONNECTED:
                self.transport._state = state
                with self.assertRaisesRegex(TransportInvalidOperation,
                                            "Can't connect to a server "
                                            "without disconnecting first."):
                    await self.transport.connect()

    async def test_connect_error_on_invalid_client_id(self):
        self.transport._client_id = ""

        with self.assertRaisesRegex(TransportInvalidOperation,
                                    "Can't connect to the server without a "
                                    "client id. Do a handshake first."):
            await self.transport.connect()

    async def test_connect(self):
        self.transport._client_id = "id"
        response = {
            "channel": "/meta/connect",
            "successful": True,
            "advice": {"interval": 0, "reconnect": "retry"},
            "id": "2"
        }
        self.transport._connect = mock.CoroutineMock(return_value=response)
        self.transport._connect_done = mock.MagicMock()
        self.transport._state = TransportState.DISCONNECTED

        result = await self.transport.connect()

        self.assertEqual(result, response)
        self.assertEqual(self.transport.state, TransportState.CONNECTING)

    async def test_connect_done_with_result(self):
        task = asyncio.ensure_future(self.long_task("result"))
        await asyncio.wait([task])
        self.transport._follow_advice = mock.MagicMock()
        self.transport._state = TransportState.CONNECTING
        self.transport._connecting_event.set()
        self.transport._connected_event.clear()
        self.transport._reconnect_advice = {
            "interval": 1,
            "reconnect": "retry"
        }
        self.transport._reconnect_timeout = 2

        with self.assertLogs("aiocometd.transport", "DEBUG") as log:
            self.transport._connect_done(task)

        log_message = "Connect task finished with: {!r}".format("result")
        self.assertEqual(
            log.output,
            ["DEBUG:aiocometd.transport:{}".format(log_message)])
        self.transport._follow_advice.assert_called_with(1)
        self.assertEqual(self.transport.state, TransportState.CONNECTED)
        self.assertFalse(self.transport._connecting_event.is_set())
        self.assertTrue(self.transport._connected_event.is_set())

    async def test_connect_done_with_error(self):
        error = RuntimeError("error")
        task = asyncio.ensure_future(self.long_task(error))
        await asyncio.wait([task])
        self.transport._follow_advice = mock.MagicMock()
        self.transport._state = TransportState.CONNECTED
        self.transport._connecting_event.clear()
        self.transport._connected_event.set()
        self.transport._reconnect_advice = {
            "interval": 1,
            "reconnect": "retry"
        }
        self.transport._reconnect_timeout = 2

        with self.assertLogs("aiocometd.transport", "DEBUG") as log:
            self.transport._connect_done(task)

        log_message = "Connect task finished with: {!r}".format(error)
        self.assertEqual(
            log.output,
            ["DEBUG:aiocometd.transport:{}".format(log_message)])
        self.transport._follow_advice.assert_called_with(2)
        self.assertEqual(self.transport.state, TransportState.CONNECTING)
        self.assertTrue(self.transport._connecting_event.is_set())
        self.assertFalse(self.transport._connected_event.is_set())

    async def test_connect_dont_follow_advice_on_disconnecting(self):
        task = asyncio.ensure_future(self.long_task("result"))
        await asyncio.wait([task])
        self.transport._follow_advice = mock.MagicMock()
        self.transport._state = TransportState.DISCONNECTING
        self.transport._reconnect_advice = {
            "interval": 1,
            "reconnect": "retry"
        }
        self.transport._reconnect_timeout = 2

        with self.assertLogs("aiocometd.transport", "DEBUG") as log:
            self.transport._connect_done(task)

        log_message = "Connect task finished with: {!r}".format("result")
        self.assertEqual(
            log.output,
            ["DEBUG:aiocometd.transport:{}".format(log_message)])
        self.transport._follow_advice.assert_not_called()

    def test_follow_advice_handshake(self):
        self.transport._reconnect_advice = {
            "interval": 1,
            "reconnect": "handshake"
        }
        self.transport._handshake = mock.MagicMock(return_value=object())
        self.transport._connect = mock.MagicMock(return_value=object())
        self.transport._start_connect_task = mock.MagicMock()

        self.transport._follow_advice(5)

        self.transport._handshake.assert_called_with(
            [self.transport.connection_type],
            delay=5
        )
        self.transport._connect.assert_not_called()
        self.transport._start_connect_task.assert_called_with(
            self.transport._handshake.return_value
        )

    def test_follow_advice_retry(self):
        self.transport._reconnect_advice = {
            "interval": 1,
            "reconnect": "retry"
        }
        self.transport._handshake = mock.MagicMock(return_value=object())
        self.transport._connect = mock.MagicMock(return_value=object())
        self.transport._start_connect_task = mock.MagicMock()

        self.transport._follow_advice(5)

        self.transport._handshake.assert_not_called()
        self.transport._connect.assert_called_with(delay=5)
        self.transport._start_connect_task.assert_called_with(
            self.transport._connect.return_value
        )

    def test_follow_advice_none(self):
        advices = ["none", "", None]
        for advice in advices:
            self.transport._state = TransportState.CONNECTED
            self.transport._reconnect_advice = {
                "interval": 1,
                "reconnect": advice
            }
            self.transport._handshake = mock.MagicMock(return_value=object())
            self.transport._connect = mock.MagicMock(return_value=object())
            self.transport._start_connect_task = mock.MagicMock()

            with self.assertLogs("aiocometd.transport", "DEBUG") as log:
                self.transport._follow_advice(5)

            self.assertEqual(log.output,
                             ["WARNING:aiocometd.transport:No reconnect "
                              "advice provided, no more operations will be "
                              "scheduled."])
            self.transport._handshake.assert_not_called()
            self.transport._connect.assert_not_called()
            self.transport._start_connect_task.assert_not_called()
            self.assertEqual(self.transport.state, TransportState.DISCONNECTED)

    def test_follow_advice_none_with_done_task(self):
        advices = ["none", "", None]
        for advice in advices:
            self.transport._state = TransportState.CONNECTED
            self.transport._reconnect_advice = {
                "interval": 1,
                "reconnect": advice
            }
            self.transport._handshake = mock.MagicMock(return_value=object())
            self.transport._connect = mock.MagicMock(return_value=object())
            self.transport._start_connect_task = mock.MagicMock()
            self.transport._connect_task = mock.MagicMock()
            connect_result = object()
            self.transport._connect_task.result.return_value = connect_result
            self.transport._enqueue_message = mock.MagicMock()

            with self.assertLogs("aiocometd.transport", "DEBUG") as log:
                self.transport._follow_advice(5)

            self.assertEqual(log.output,
                             ["WARNING:aiocometd.transport:No reconnect "
                              "advice provided, no more operations will be "
                              "scheduled."])
            self.transport._handshake.assert_not_called()
            self.transport._connect.assert_not_called()
            self.transport._start_connect_task.assert_not_called()
            self.assertEqual(self.transport.state, TransportState.DISCONNECTED)
            self.transport._enqueue_message.assert_called_with(connect_result)

    def test_client_id(self):
        self.assertIs(self.transport.client_id,
                      self.transport._client_id)

    def test_client_id_read_only(self):
        with self.assertRaises(AttributeError):
            self.transport.client_id = "id"

    def test_endpoint(self):
        self.assertIs(self.transport.endpoint,
                      self.transport._endpoint)

    def test_endpoint_read_only(self):
        with self.assertRaises(AttributeError):
            self.transport.endpoint = ""

    async def test_disconnect(self):
        for state in TransportState:
            self.transport._state = state
            self.transport._stop_connect_task = mock.CoroutineMock()
            self.transport._send_message = mock.CoroutineMock()

            await self.transport.disconnect()

            self.assertEqual(self.transport.state, TransportState.DISCONNECTED)
            self.transport._stop_connect_task.assert_called()
            self.transport._send_message.assert_called_with(
                self.transport._DISCONNECT_MESSAGE)

    async def test_subscribe(self):
        for state in [TransportState.CONNECTED, TransportState.CONNECTING]:
            self.transport._state = state
            self.transport._send_message = mock.CoroutineMock(
                return_value="result"
            )

            result = await self.transport.subscribe("channel")

            self.assertEqual(result,
                             self.transport._send_message.return_value)
            self.transport._send_message.assert_called_with(
                self.transport._SUBSCRIBE_MESSAGE,
                subscription="channel"
            )

    async def test_subscribe_error_if_not_connected(self):
        for state in TransportState:
            if state not in [TransportState.CONNECTED,
                             TransportState.CONNECTING]:
                self.transport._state = state
                self.transport._send_message = mock.CoroutineMock(
                    return_value="result"
                )

                with self.assertRaisesRegex(TransportInvalidOperation,
                                            "Can't subscribe without being "
                                            "connected to a server."):
                    await self.transport.subscribe("channel")

                self.transport._send_message.assert_not_called()

    async def test_unsubscribe(self):
        for state in [TransportState.CONNECTED, TransportState.CONNECTING]:
            self.transport._state = state
            self.transport._send_message = mock.CoroutineMock(
                return_value="result"
            )

            result = await self.transport.unsubscribe("channel")

            self.assertEqual(result,
                             self.transport._send_message.return_value)
            self.transport._send_message.assert_called_with(
                self.transport._UNSUBSCRIBE_MESSAGE,
                subscription="channel"
            )

    async def test_unsubscribe_error_if_not_connected(self):
        for state in TransportState:
            if state not in [TransportState.CONNECTED,
                             TransportState.CONNECTING]:
                self.transport._state = state
                self.transport._send_message = mock.CoroutineMock(
                    return_value="result"
                )

                with self.assertRaisesRegex(TransportInvalidOperation,
                                            "Can't unsubscribe without being "
                                            "connected to a server."):
                    await self.transport.unsubscribe("channel")

                self.transport._send_message.assert_not_called()

    async def test_publish(self):
        for state in [TransportState.CONNECTED, TransportState.CONNECTING]:
            self.transport._state = state
            self.transport._send_message = mock.CoroutineMock(
                return_value="result"
            )

            result = await self.transport.publish("channel", {})

            self.assertEqual(result,
                             self.transport._send_message.return_value)
            self.transport._send_message.assert_called_with(
                self.transport._PUBLISH_MESSAGE,
                channel="channel",
                data={}
            )

    async def test_publish_error_if_not_connected(self):
        for state in TransportState:
            if state not in [TransportState.CONNECTED,
                             TransportState.CONNECTING]:
                self.transport._state = state
                self.transport._send_message = mock.CoroutineMock(
                    return_value="result"
                )

                with self.assertRaisesRegex(TransportInvalidOperation,
                                            "Can't publish without being "
                                            "connected to a server."):
                    await self.transport.publish("channel", {})

                self.transport._send_message.assert_not_called()

    async def test_wait_for_connecting(self):
        self.transport._connecting_event.wait = mock.CoroutineMock()

        await self.transport.wait_for_connecting()

        self.transport._connecting_event.wait.assert_called()

    async def test_wait_for_connected(self):
        self.transport._connected_event.wait = mock.CoroutineMock()

        await self.transport.wait_for_connected()

        self.transport._connected_event.wait.assert_called()

    async def test_close(self):
        self.transport._close_http_session = mock.CoroutineMock()

        await self.transport.close()

        self.transport._close_http_session.assert_called()

    async def test_send_payload(self):
        payload = object()
        self.transport._finalize_payload = mock.MagicMock()
        response = object()
        self.transport._send_final_payload = mock.CoroutineMock(
            return_value=response
        )
        self.transport._process_outgoing_payload = mock.CoroutineMock()

        result = await self.transport._send_payload(payload)

        self.assertEqual(result, response)
        self.transport._finalize_payload.assert_called_with(payload)
        self.transport._send_final_payload.assert_called_with(payload,
                                                              headers={})
        self.transport._process_outgoing_payload.assert_called_with(payload,
                                                                    {})

    async def test_process_outgoing_payload(self):
        extension = mock.create_autospec(spec=Extension)
        auth = mock.create_autospec(spec=AuthExtension)
        self.transport._extensions = [extension]
        self.transport._auth = auth
        payload = object()
        headers = object()

        await self.transport._process_outgoing_payload(payload, headers)

        extension.outgoing.assert_called_with(payload, headers)
        auth.outgoing.assert_called_with(payload, headers)

    @mock.patch("aiocometd.transport.get_error_code")
    def test_is_auth_error_message(self, get_error_code):
        response = {
            "error": "error"
        }
        get_error_code.return_value = 401

        result = self.transport._is_auth_error_message(response)

        self.assertTrue(result)
        get_error_code.assert_called_with(response["error"])

    @mock.patch("aiocometd.transport.get_error_code")
    def test_is_auth_error_message_forbidden(self, get_error_code):
        response = {
            "error": "error"
        }
        get_error_code.return_value = 403

        result = self.transport._is_auth_error_message(response)

        self.assertTrue(result)
        get_error_code.assert_called_with(response["error"])

    @mock.patch("aiocometd.transport.get_error_code")
    def test_is_auth_error_message_not_an_auth_error(self, get_error_code):
        response = {
            "error": "error"
        }
        get_error_code.return_value = 400

        result = self.transport._is_auth_error_message(response)

        self.assertFalse(result)
        get_error_code.assert_called_with(response["error"])

    @mock.patch("aiocometd.transport.get_error_code")
    def test_is_auth_error_message_not_an_error(self, get_error_code):
        response = {}
        get_error_code.return_value = None

        result = self.transport._is_auth_error_message(response)

        self.assertFalse(result)
        get_error_code.assert_called_with(None)

    async def test_send_payload_with_auth(self):
        response = object()
        payload = object()
        self.transport._send_payload = mock.CoroutineMock(
            return_value=response)
        self.transport._auth = None
        self.transport._is_auth_error_message = mock.MagicMock(
            return_value=False)

        result = await self.transport._send_payload_with_auth(payload)

        self.assertIs(result, response)
        self.transport._send_payload.assert_called_with(payload)
        self.transport._is_auth_error_message.assert_not_called()

    async def test_send_payload_with_auth_with_extension(self):
        response = object()
        payload = object()
        self.transport._send_payload = mock.CoroutineMock(
            return_value=response)
        self.transport._auth = mock.create_autospec(spec=AuthExtension)
        self.transport._is_auth_error_message = mock.MagicMock(
            return_value=False)

        result = await self.transport._send_payload_with_auth(payload)

        self.assertIs(result, response)
        self.transport._send_payload.assert_called_with(payload)
        self.transport._is_auth_error_message.assert_called_with(response)
        self.transport._auth.authenticate.assert_not_called()

    async def test_send_payload_with_auth_with_extension_error(self):
        response = object()
        response2 = object()
        payload = object()
        self.transport._send_payload = mock.CoroutineMock(
            side_effect=[response, response2])
        self.transport._auth = mock.create_autospec(spec=AuthExtension)
        self.transport._is_auth_error_message = mock.MagicMock(
            return_value=True)

        result = await self.transport._send_payload_with_auth(payload)

        self.assertIs(result, response2)
        self.transport._send_payload.assert_has_calls([
            mock.call(payload), mock.call(payload)
        ])
        self.transport._is_auth_error_message.assert_called_with(response)
        self.transport._auth.authenticate.assert_called()


class TestLongPollingTransport(TestCase):
    def setUp(self):
        self.transport = LongPollingTransport(endpoint="example.com/cometd",
                                              incoming_queue=None,
                                              loop=None)

    def test_connection_type(self):
        self.assertEqual(self.transport.connection_type,
                         ConnectionType.LONG_POLLING)

    async def test_send_payload_final_payload(self):
        resp_data = [{
            "channel": "test/channel3",
            "data": {},
            "id": 4
        }]
        response_mock = mock.MagicMock()
        response_mock.json = mock.CoroutineMock(return_value=resp_data)
        response_mock.headers = object()
        session = mock.MagicMock()
        session.post = mock.CoroutineMock(return_value=response_mock)
        self.transport._get_http_session = \
            mock.CoroutineMock(return_value=session)
        self.transport._http_semaphore = mock.MagicMock()
        payload = [object(), object()]
        self.transport.ssl = object()
        self.transport._consume_payload = \
            mock.CoroutineMock(return_value=resp_data[0])
        headers = dict(key="value")

        response = await self.transport._send_final_payload(payload,
                                                            headers=headers)

        self.assertEqual(response, resp_data[0])
        self.transport._http_semaphore.__aenter__.assert_called()
        self.transport._http_semaphore.__aexit__.assert_called()
        session.post.assert_called_with(self.transport._endpoint,
                                        json=payload,
                                        ssl=self.transport.ssl,
                                        headers=headers)
        self.transport._consume_payload.assert_called_with(
            resp_data,
            headers=response_mock.headers,
            find_response_for=payload[0])

    async def test_send_payload_final_payload_client_error(self):
        resp_data = [{
            "channel": "test/channel3",
            "data": {},
            "id": 4
        }]
        response_mock = mock.MagicMock()
        response_mock.json = mock.CoroutineMock(return_value=resp_data)
        session = mock.MagicMock()
        post_exception = client_exceptions.ClientError("client error")
        session.post = mock.CoroutineMock(side_effect=post_exception)
        self.transport._get_http_session = \
            mock.CoroutineMock(return_value=session)
        self.transport._http_semaphore = mock.MagicMock()
        payload = [object(), object()]
        self.transport.ssl = object()
        self.transport._consume_payload = \
            mock.CoroutineMock(return_value=resp_data[0])
        headers = dict(key="value")

        with self.assertLogs("aiocometd.transport", level="DEBUG") as log:
            with self.assertRaisesRegex(TransportError, str(post_exception)):
                await self.transport._send_final_payload(payload,
                                                         headers=headers)

        log_message = "WARNING:aiocometd.transport:" \
                      "Failed to send payload, {}".format(post_exception)
        self.assertEqual(log.output, [log_message])
        self.transport._http_semaphore.__aenter__.assert_called()
        self.transport._http_semaphore.__aexit__.assert_called()
        session.post.assert_called_with(self.transport._endpoint,
                                        json=payload,
                                        ssl=self.transport.ssl,
                                        headers=headers)
        self.transport._consume_payload.assert_not_called()


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
        channel = "/meta/connect"
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
        channel = "/meta/connect"
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

        with self.assertLogs("aiocometd.transport", level="DEBUG") as log:
            with self.assertRaisesRegex(TransportError, str(exception)):
                await self.transport._send_final_payload(payload,
                                                         headers=headers)

        log_message = "WARNING:aiocometd.transport:" \
                      "Failed to send payload, {}".format(exception)
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


class TestTransportFactoryFunctions(TestCase):
    def tearDown(self):
        transport_classes.clear()

    def test_register_transport(self):
        connection_type = ConnectionType.LONG_POLLING

        @register_transport(connection_type)
        class FakeTransport:
            "FakeTransport"

        obj = FakeTransport()

        self.assertEqual(obj.connection_type, connection_type)
        self.assertEqual(transport_classes[connection_type], FakeTransport)

    def test_create_transport(self):
        transport = object()
        transport_cls = mock.MagicMock(return_value=transport)
        transport_classes[ConnectionType.LONG_POLLING] = transport_cls

        result = create_transport(ConnectionType.LONG_POLLING,
                                  "arg", kwarg="value")

        self.assertEqual(result, transport)
        transport_cls.assert_called_with("arg", kwarg="value")

    def test_create_transport_error(self):
        connection_type = None

        with self.assertRaises(TransportInvalidOperation,
                               msg="There is no transport with "
                                   "a name {!r}".format(connection_type)):
            create_transport(connection_type)
