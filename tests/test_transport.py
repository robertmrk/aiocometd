import asyncio

from asynctest import TestCase, mock
from aiohttp import ClientSession, client_exceptions

from aiocometd.transport import LongPollingTransport, TransportState, \
    _TransportBase
from aiocometd.exceptions import TransportError, TransportInvalidOperation


class TransportBase(_TransportBase):
    async def _send_final_payload(self, payload):
        pass


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
        self.assertEqual(message["connectionType"], self.transport.name)

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

        result = await self.transport._consume_payload(
            payload, find_response_for=message)

        self.assertEqual(result, payload[0])
        self.assertEqual(self.transport._reconnect_advice,
                         payload[0]["advice"])
        self.transport._update_subscriptions.assert_called_with(payload[0])
        self.transport._is_matching_response.assert_called_with(payload[0],
                                                                message)
        self.transport._consume_message.assert_not_called()

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

        result = await self.transport._consume_payload(
            payload, find_response_for=message)

        self.assertIsNone(result)
        self.assertEqual(self.transport._reconnect_advice, {})
        self.transport._update_subscriptions.assert_called_with(payload[0])
        self.transport._is_matching_response.assert_called_with(payload[0],
                                                                message)
        self.transport._consume_message.assert_called_with(payload[0])

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

        log_message = "DEBUG:aiocometd.transport:Incoming message queue is " \
                      "full, dropping message."
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
        self.transport._send_payload = \
            mock.CoroutineMock(return_value=response)

        result = await self.transport._send_message(message,
                                                    field="value")

        self.assertIs(result, response)
        self.assertEqual(message["field"], "value")
        self.transport._send_payload.assert_called_with([message])

    @mock.patch("aiocometd.transport.asyncio.sleep")
    async def test_handshake(self, sleep):
        connection_types = ["type1"]
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
        self.transport._send_message.assert_called_with(
            message,
            supportedConnectionTypes=connection_types + [self.transport.name])
        self.assertEqual(self.transport.client_id, response["clientId"])
        self.assertTrue(self.transport._subscribe_on_connect)

    @mock.patch("aiocometd.transport.asyncio.sleep")
    async def test_handshake_failure(self, sleep):
        connection_types = ["type1"]
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
        self.transport._send_message.assert_called_with(
            message,
            supportedConnectionTypes=connection_types + [self.transport.name])
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
        self.transport._send_payload = \
            mock.CoroutineMock(return_value=response)

        result = await self.transport._connect()

        self.assertEqual(result, response)
        sleep.assert_not_called()
        self.transport._send_payload.assert_called_with(
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
        self.transport._send_payload = \
            mock.CoroutineMock(return_value=response)

        result = await self.transport._connect(5)

        self.assertEqual(result, response)
        sleep.assert_called_with(5, loop=self.transport._loop)
        self.transport._send_payload.assert_called_with(
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
        self.transport._send_payload = \
            mock.CoroutineMock(return_value=response)

        result = await self.transport._connect()

        self.assertEqual(result, response)
        self.transport._send_payload.assert_called_with(
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
        self.transport._send_payload = \
            mock.CoroutineMock(return_value=response)

        result = await self.transport._connect()

        self.assertEqual(result, response)
        self.transport._send_payload.assert_called_with(
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

        self.transport._handshake.assert_called_with([self.transport.name],
                                                     delay=5)
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
                             ["DEBUG:aiocometd.transport:No reconnect advice "
                              "provided, no more operations will be "
                              "scheduled."])
            self.transport._handshake.assert_not_called()
            self.transport._connect.assert_not_called()
            self.transport._start_connect_task.assert_not_called()
            self.assertEqual(self.transport.state, TransportState.DISCONNECTED)

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

        result = await self.transport._send_payload(payload)

        self.assertEqual(result, response)
        self.transport._finalize_payload.assert_called_with(payload)
        self.transport._send_final_payload.assert_called_with(payload)


class TestLongPollingTransport(TestCase):
    def setUp(self):
        self.transport = LongPollingTransport(endpoint="example.com/cometd",
                                              incoming_queue=None,
                                              loop=None)

    def test_name(self):
        self.assertEqual(self.transport.name, "long-polling")

    async def test_send_payload(self):
        resp_data = [{
            "channel": "test/channel3",
            "data": {},
            "id": 4
        }]
        response_mock = mock.MagicMock()
        response_mock.json = mock.CoroutineMock(return_value=resp_data)
        session = mock.MagicMock()
        session.post = mock.CoroutineMock(return_value=response_mock)
        self.transport._get_http_session = \
            mock.CoroutineMock(return_value=session)
        self.transport._http_semaphore = mock.MagicMock()
        payload = [object(), object()]
        self.transport.ssl = object()
        self.transport._consume_payload = \
            mock.CoroutineMock(return_value=resp_data[0])

        response = await self.transport._send_final_payload(payload)

        self.assertEqual(response, resp_data[0])
        self.transport._http_semaphore.__aenter__.assert_called()
        self.transport._http_semaphore.__aexit__.assert_called()
        session.post.assert_called_with(self.transport._endpoint,
                                        json=payload,
                                        ssl=self.transport.ssl)
        self.transport._consume_payload.assert_called_with(
            resp_data,
            find_response_for=payload[0])

    async def test_send_payload_client_error(self):
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

        with self.assertLogs("aiocometd.transport", level="DEBUG") as log:
            with self.assertRaisesRegex(TransportError, str(post_exception)):
                await self.transport._send_final_payload(payload)

        log_message = "DEBUG:aiocometd.transport:" \
                      "Failed to send payload, {}".format(post_exception)
        self.assertEqual(log.output, [log_message])
        self.transport._http_semaphore.__aenter__.assert_called()
        self.transport._http_semaphore.__aexit__.assert_called()
        session.post.assert_called_with(self.transport._endpoint,
                                        json=payload,
                                        ssl=self.transport.ssl)
        self.transport._consume_payload.assert_not_called()
