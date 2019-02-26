import asyncio

from asynctest import TestCase, mock

from aiocometd.transports.base import TransportBase
from aiocometd.constants import ConnectionType, MetaChannel, \
    TransportState, CONNECT_MESSAGE, SUBSCRIBE_MESSAGE, DISCONNECT_MESSAGE, \
    PUBLISH_MESSAGE, UNSUBSCRIBE_MESSAGE
from aiocometd.extensions import Extension, AuthExtension
from aiocometd.exceptions import TransportInvalidOperation, TransportError


class TransportBaseImpl(TransportBase):
    async def _send_final_payload(self, payload):
        pass

    @property
    def connection_type(self):
        return ConnectionType.LONG_POLLING


class TestTransportBase(TestCase):
    def setUp(self):
        self.transport = TransportBaseImpl(url="example.com/cometd",
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

        transport = TransportBaseImpl(url=None,
                                      incoming_queue=None,
                                      loop=loop)

        self.assertIs(transport._loop, loop)
        self.assertEqual(transport.state, TransportState.DISCONNECTED)

    @mock.patch("aiocometd.transports.base.asyncio")
    def test_init_without_loop(self, asyncio_mock):
        loop = object()
        asyncio_mock.get_event_loop.return_value = loop

        transport = TransportBaseImpl(url=None,
                                      incoming_queue=None)

        self.assertIs(transport._loop, loop)
        self.assertEqual(transport.state, TransportState.DISCONNECTED)

    def test_init_with_reconnect_advice(self):
        advice = object()

        transport = TransportBaseImpl(url=None,
                                      incoming_queue=None,
                                      reconnect_advice=advice)

        self.assertIs(transport.reconnect_advice, advice)

    def test_init_without_reconnect_advice(self):
        transport = TransportBaseImpl(url=None,
                                      incoming_queue=None)

        self.assertEqual(transport.reconnect_advice, {})

    async def test_get_http_session(self):
        self.transport._http_session = object()

        session = await self.transport._get_http_session()

        self.assertEqual(session, self.transport._http_session)

    @mock.patch("aiocometd.transports.base.aiohttp.ClientSession")
    async def test_get_http_session_creates_session(self, client_session_cls):
        self.transport._http_session = None
        session = object()
        client_session_cls.return_value = session

        session = await self.transport._get_http_session()

        self.assertEqual(session, self.transport._http_session)
        self.assertEqual(self.transport._http_session, session)
        client_session_cls.assert_called_with(
            json_serialize=self.transport._json_dumps
        )

    @mock.patch("aiocometd.transports.base.asyncio")
    async def test_close_http_session(self, asyncio_mock):
        self.transport._http_session = mock.MagicMock()
        self.transport._http_session.closed = False
        self.transport._http_session.close = mock.CoroutineMock()
        asyncio_mock.sleep = mock.CoroutineMock()

        await self.transport._close_http_session()

        self.transport._http_session.close.assert_called()
        asyncio_mock.sleep.assert_called_with(
            self.transport._HTTP_SESSION_CLOSE_TIMEOUT)

    @mock.patch("aiocometd.transports.base.asyncio")
    async def test_close_http_session_already_closed(self, asyncio_mock):
        self.transport._http_session = mock.MagicMock()
        self.transport._http_session.closed = True
        self.transport._http_session.close = mock.CoroutineMock()
        asyncio_mock.sleep = mock.CoroutineMock()

        await self.transport._close_http_session()

        self.transport._http_session.close.assert_not_called()
        asyncio_mock.sleep.assert_not_called()

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

    @mock.patch("aiocometd.transports.base.is_event_message")
    async def test_consume_message_non_event_message(self, is_event_message):
        is_event_message.return_value = False
        self.transport.incoming_queue = mock.MagicMock()
        self.transport.incoming_queue.put = mock.CoroutineMock()
        response_message = object()

        await self.transport._consume_message(response_message)

        is_event_message.assert_called_with(response_message)
        self.transport.incoming_queue.put.assert_not_called()

    @mock.patch("aiocometd.transports.base.is_event_message")
    async def test_consume_message_event_message(self, is_event_message):
        is_event_message.return_value = True
        self.transport.incoming_queue = mock.MagicMock()
        self.transport.incoming_queue.put = mock.CoroutineMock()
        response_message = object()

        await self.transport._consume_message(response_message)

        is_event_message.assert_called_with(response_message)

    def test_update_subscriptions_new_subscription_success(self):
        response_message = {
            "channel": MetaChannel.SUBSCRIBE,
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
            "channel": MetaChannel.SUBSCRIBE,
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
            "channel": MetaChannel.SUBSCRIBE,
            "subscription": "/test/channel1",
            "successful": False,
            "id": "3"
        }
        self.transport._subscriptions = set()

        self.transport._update_subscriptions(response_message)

        self.assertEqual(self.transport.subscriptions, set())

    def test_update_subscriptions_new_subscription_fail_with_error(self):
        response_message = {
            "channel": MetaChannel.SUBSCRIBE,
            "error": "403::subscription_invalid",
            "successful": False,
            "id": "3"
        }
        self.transport._subscriptions = set()

        self.transport._update_subscriptions(response_message)

        self.assertEqual(self.transport.subscriptions, set())

    def test_update_subscriptions_existing_subscription_fail(self):
        response_message = {
            "channel": MetaChannel.SUBSCRIBE,
            "subscription": "/test/channel1",
            "successful": False,
            "id": "3"
        }
        self.transport._subscriptions = set([response_message["subscription"]])

        self.transport._update_subscriptions(response_message)

        self.assertEqual(self.transport.subscriptions, set())

    def test_update_subscriptions_new_unsubscription_success(self):
        response_message = {
            "channel": MetaChannel.UNSUBSCRIBE,
            "subscription": "/test/channel1",
            "successful": True,
            "id": "3"
        }
        self.transport._subscriptions = set()

        self.transport._update_subscriptions(response_message)

        self.assertEqual(self.transport.subscriptions, set())

    def test_update_subscriptions_existing_unsubscription_success(self):
        response_message = {
            "channel": MetaChannel.UNSUBSCRIBE,
            "subscription": "/test/channel1",
            "successful": True,
            "id": "3"
        }
        self.transport._subscriptions = set([response_message["subscription"]])

        self.transport._update_subscriptions(response_message)

        self.assertEqual(self.transport.subscriptions, set())

    def test_update_subscriptions_new_unsubscription_fail(self):
        response_message = {
            "channel": MetaChannel.UNSUBSCRIBE,
            "subscription": "/test/channel1",
            "successful": False,
            "id": "3"
        }
        self.transport._subscriptions = set()

        self.transport._update_subscriptions(response_message)

        self.assertEqual(self.transport.subscriptions, set())

    def test_update_subscriptions_existing_unsubscription_fail(self):
        response_message = {
            "channel": MetaChannel.UNSUBSCRIBE,
            "subscription": "/test/channel1",
            "successful": False,
            "id": "3"
        }
        self.transport._subscriptions = set([response_message["subscription"]])

        self.transport._update_subscriptions(response_message)

        self.assertEqual(self.transport.subscriptions,
                         set([response_message["subscription"]]))

    @mock.patch("aiocometd.transports.base.is_matching_response")
    async def test_consume_payload_matching_without_advice(
            self, is_matching_response):
        payload = [
            {
                "channel": MetaChannel.CONNECT,
                "successful": True,
                "id": "1"
            }
        ]
        message = object()
        self.transport._update_subscriptions = mock.MagicMock()
        is_matching_response.return_value = True
        self.transport._consume_message = mock.MagicMock()

        result = await self.transport._consume_payload(
            payload, find_response_for=message)

        self.assertEqual(result, payload[0])
        self.assertEqual(self.transport.reconnect_advice, {})
        self.transport._update_subscriptions.assert_called_with(payload[0])
        is_matching_response.assert_called_with(payload[0], message)
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

    @mock.patch("aiocometd.transports.base.is_matching_response")
    async def test_consume_payload_matching_without_advice_extension(
            self, is_matching_response):
        payload = [
            {
                "channel": MetaChannel.CONNECT,
                "successful": True,
                "id": "1"
            }
        ]
        message = object()
        self.transport._update_subscriptions = mock.MagicMock()
        is_matching_response.return_value = True
        self.transport._consume_message = mock.MagicMock()
        self.transport._process_incoming_payload = mock.CoroutineMock()
        headers = object()

        result = await self.transport._consume_payload(
            payload, headers=headers, find_response_for=message)

        self.assertEqual(result, payload[0])
        self.assertEqual(self.transport.reconnect_advice, {})
        self.transport._update_subscriptions.assert_called_with(payload[0])
        is_matching_response.assert_called_with(payload[0], message)
        self.transport._consume_message.assert_not_called()
        self.transport._process_incoming_payload.assert_called_with(payload,
                                                                    headers)

    @mock.patch("aiocometd.transports.base.is_matching_response")
    async def test_consume_payload_matching_with_advice(self,
                                                        is_matching_response):
        payload = [
            {
                "channel": MetaChannel.CONNECT,
                "successful": True,
                "advice": {"interval": 0, "reconnect": "retry"},
                "id": "1"
            }
        ]
        message = object()
        self.transport._update_subscriptions = mock.MagicMock()
        is_matching_response.return_value = True
        self.transport._consume_message = mock.MagicMock()
        self.transport._process_incoming_payload = mock.CoroutineMock()

        result = await self.transport._consume_payload(
            payload, find_response_for=message)

        self.assertEqual(result, payload[0])
        self.assertEqual(self.transport.reconnect_advice,
                         payload[0]["advice"])
        self.transport._update_subscriptions.assert_called_with(payload[0])
        is_matching_response.assert_called_with(payload[0], message)
        self.transport._consume_message.assert_not_called()
        self.transport._process_incoming_payload.assert_called_with(payload,
                                                                    None)

    @mock.patch("aiocometd.transports.base.is_matching_response")
    async def test_consume_payload_non_matching(self, is_matching_response):
        payload = [
            {
                "channel": MetaChannel.CONNECT,
                "successful": True,
                "id": "1"
            }
        ]
        message = object()
        self.transport._update_subscriptions = mock.MagicMock()
        is_matching_response.return_value = False
        self.transport._consume_message = mock.CoroutineMock()
        self.transport._process_incoming_payload = mock.CoroutineMock()

        result = await self.transport._consume_payload(
            payload, find_response_for=message)

        self.assertIsNone(result)
        self.assertEqual(self.transport.reconnect_advice, {})
        self.transport._update_subscriptions.assert_called_with(payload[0])
        is_matching_response.assert_called_with(payload[0], message)
        self.transport._consume_message.assert_called_with(payload[0])
        self.transport._process_incoming_payload.assert_called_with(payload,
                                                                    None)

    @mock.patch("aiocometd.transports.base.is_matching_response")
    async def test_consume_payload_none_matching(self, is_matching_response):
        payload = [
            {
                "channel": MetaChannel.CONNECT,
                "successful": True,
                "id": "1"
            }
        ]
        message = None
        self.transport._update_subscriptions = mock.MagicMock()
        is_matching_response.return_value = False
        self.transport._consume_message = mock.CoroutineMock()
        self.transport._process_incoming_payload = mock.CoroutineMock()

        result = await self.transport._consume_payload(
            payload, find_response_for=message)

        self.assertIsNone(result)
        self.assertEqual(self.transport.reconnect_advice, {})
        self.transport._update_subscriptions.assert_called_with(payload[0])
        is_matching_response.assert_called_with(payload[0], message)
        self.transport._consume_message.assert_called_with(payload[0])
        self.transport._process_incoming_payload.assert_called_with(payload,
                                                                    None)

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

    async def test_handshake(self):
        connection_types = [ConnectionType.WEBSOCKET]
        response = {
            "clientId": "id1",
            "successful": True
        }
        self.transport._send_message = \
            mock.CoroutineMock(return_value=response)
        message = {
            "channel": MetaChannel.HANDSHAKE,
            "version": "1.0",
            "supportedConnectionTypes": None,
            "minimumVersion": "1.0",
            "id": None
        }
        self.transport._subscribe_on_connect = False

        result = await self.transport.handshake(connection_types)

        self.assertEqual(result, response)
        final_connection_types = [ConnectionType.WEBSOCKET.value,
                                  self.transport.connection_type.value]
        self.transport._send_message.assert_called_with(
            message,
            supportedConnectionTypes=final_connection_types)
        self.assertEqual(self.transport.client_id, response["clientId"])
        self.assertTrue(self.transport._subscribe_on_connect)

    async def test_handshake_empty_connection_types(self):
        connection_types = []
        response = {
            "clientId": "id1",
            "successful": True
        }
        self.transport._send_message = \
            mock.CoroutineMock(return_value=response)
        message = {
            "channel": MetaChannel.HANDSHAKE,
            "version": "1.0",
            "supportedConnectionTypes": None,
            "minimumVersion": "1.0",
            "id": None
        }
        self.transport._subscribe_on_connect = False

        result = await self.transport.handshake(connection_types)

        self.assertEqual(result, response)
        final_connection_types = [self.transport.connection_type.value]
        self.transport._send_message.assert_called_with(
            message,
            supportedConnectionTypes=final_connection_types)
        self.assertEqual(self.transport.client_id, response["clientId"])
        self.assertTrue(self.transport._subscribe_on_connect)

    async def test_handshake_with_own_connection_type(self):
        connection_types = [self.transport.connection_type]
        response = {
            "clientId": "id1",
            "successful": True
        }
        self.transport._send_message = \
            mock.CoroutineMock(return_value=response)
        message = {
            "channel": MetaChannel.HANDSHAKE,
            "version": "1.0",
            "supportedConnectionTypes": None,
            "minimumVersion": "1.0",
            "id": None
        }
        self.transport._subscribe_on_connect = False

        result = await self.transport.handshake(connection_types)

        self.assertEqual(result, response)
        final_connection_types = [self.transport.connection_type.value]
        self.transport._send_message.assert_called_with(
            message,
            supportedConnectionTypes=final_connection_types)
        self.assertEqual(self.transport.client_id, response["clientId"])
        self.assertTrue(self.transport._subscribe_on_connect)

    async def test_handshake_failure(self):
        connection_types = [ConnectionType.WEBSOCKET]
        response = {
            "clientId": "id1",
            "successful": False
        }
        self.transport._send_message = \
            mock.CoroutineMock(return_value=response)
        message = {
            "channel": MetaChannel.HANDSHAKE,
            "version": "1.0",
            "supportedConnectionTypes": None,
            "minimumVersion": "1.0",
            "id": None
        }
        self.transport._subscribe_on_connect = False

        result = await self.transport.handshake(connection_types)

        self.assertEqual(result, response)
        final_connection_types = [ConnectionType.WEBSOCKET.value,
                                  self.transport.connection_type.value]
        self.transport._send_message.assert_called_with(
            message,
            supportedConnectionTypes=final_connection_types)
        self.assertEqual(self.transport.client_id, None)
        self.assertFalse(self.transport._subscribe_on_connect)

    def test_subscriptions(self):
        self.assertIs(self.transport.subscriptions,
                      self.transport._subscriptions)

    def test_subscriptions_read_only(self):
        with self.assertRaises(AttributeError):
            self.transport.subscriptions = {"channel1", "channel2"}

    async def test__connect(self):
        self.transport._subscribe_on_connect = False
        response = {
            "channel": MetaChannel.CONNECT,
            "successful": True,
            "advice": {"interval": 0, "reconnect": "retry"},
            "id": "2"
        }
        self.transport._send_payload_with_auth = \
            mock.CoroutineMock(return_value=response)

        result = await self.transport._connect()

        self.assertEqual(result, response)
        self.transport._send_payload_with_auth.assert_called_with(
            [CONNECT_MESSAGE])
        self.assertFalse(self.transport._subscribe_on_connect)

    async def test__connect_subscribe_on_connect(self):
        self.transport._subscribe_on_connect = True
        self.transport._subscriptions = {"/test/channel1", "/test/channel2"}
        response = {
            "channel": MetaChannel.CONNECT,
            "successful": True,
            "advice": {"interval": 0, "reconnect": "retry"},
            "id": "2"
        }
        additional_messages = []
        for subscription in self.transport.subscriptions:
            message = SUBSCRIBE_MESSAGE.copy()
            message["subscription"] = subscription
            additional_messages.append(message)
        self.transport._send_payload_with_auth = \
            mock.CoroutineMock(return_value=response)

        result = await self.transport._connect()

        self.assertEqual(result, response)
        self.transport._send_payload_with_auth.assert_called_with(
            [CONNECT_MESSAGE] + additional_messages)
        self.assertFalse(self.transport._subscribe_on_connect)

    async def test__connect_subscribe_on_connect_error(self):
        self.transport._subscribe_on_connect = True
        self.transport._subscriptions = {"/test/channel1", "/test/channel2"}
        response = {
            "channel": MetaChannel.CONNECT,
            "successful": False,
            "advice": {"interval": 0, "reconnect": "retry"},
            "id": "2"
        }
        additional_messages = []
        for subscription in self.transport.subscriptions:
            message = SUBSCRIBE_MESSAGE.copy()
            message["subscription"] = subscription
            additional_messages.append(message)
        self.transport._send_payload_with_auth = \
            mock.CoroutineMock(return_value=response)

        result = await self.transport._connect()

        self.assertEqual(result, response)
        self.transport._send_payload_with_auth.assert_called_with(
            [CONNECT_MESSAGE] + additional_messages)
        self.assertTrue(self.transport._subscribe_on_connect)

    def test__state_initially_disconnected(self):
        self.assertIs(self.transport._state,
                      TransportState.DISCONNECTED)

    def test_state(self):
        self.assertIs(self.transport.state,
                      self.transport._state)

    def test_state_read_only(self):
        with self.assertRaises(AttributeError):
            self.transport.state = TransportState.CONNECTING

    @mock.patch("aiocometd.transports.base.asyncio")
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

    @mock.patch("aiocometd.transports.base.asyncio")
    async def test_stop_connect_task(self, asyncio_mock):
        self.transport._connect_task = mock.MagicMock()
        self.transport._connect_task.done.return_value = False
        asyncio_mock.wait = mock.CoroutineMock()

        await self.transport._stop_connect_task()

        self.transport._connect_task.cancel.assert_called()
        asyncio_mock.wait.assert_called_with([self.transport._connect_task])

    @mock.patch("aiocometd.transports.base.asyncio")
    async def test_stop_connect_task_with_none_task(self, asyncio_mock):
        self.transport._connect_task = None
        asyncio_mock.wait = mock.CoroutineMock()

        await self.transport._stop_connect_task()

        asyncio_mock.wait.assert_not_called()

    @mock.patch("aiocometd.transports.base.asyncio")
    async def test_stop_connect_task_with_done_task(self, asyncio_mock):
        self.transport._connect_task = mock.MagicMock()
        self.transport._connect_task.done.return_value = True
        asyncio_mock.wait = mock.CoroutineMock()

        await self.transport._stop_connect_task()

        asyncio_mock.wait.assert_not_called()

    async def test_connect_error_on_invalid_state(self):
        self.transport._client_id = "id"
        response = {
            "channel": MetaChannel.CONNECT,
            "successful": True,
            "advice": {"interval": 0, "reconnect": "retry"},
            "id": "2"
        }
        self.transport._connect = mock.CoroutineMock(return_value=response)
        for state in TransportState:
            if state not in [TransportState.DISCONNECTED,
                             TransportState.SERVER_DISCONNECTED]:
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
            "channel": MetaChannel.CONNECT,
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

    async def test_connect_in_server_disconnected_state(self):
        self.transport._client_id = "id"
        response = {
            "channel": MetaChannel.CONNECT,
            "successful": True,
            "advice": {"interval": 0, "reconnect": "retry"},
            "id": "2"
        }
        self.transport._connect = mock.CoroutineMock(return_value=response)
        self.transport._connect_done = mock.MagicMock()
        self.transport._state = TransportState.SERVER_DISCONNECTED

        result = await self.transport.connect()

        self.assertEqual(result, response)
        self.assertEqual(self.transport.state, TransportState.CONNECTING)

    async def test_connect_done_with_result(self):
        cases = (
            ("successful",
             {"successful": True},
             "retry"),
            ("unsuccessful without advice",
             {"successful": False},
             "retry"),
            ("unsuccessful with advice and missing reconnect",
             {"successful": False, "advice": {}},
             "retry"),
            ("unsuccessful with advice and reconnect",
             {"successful": False, "advice": {"reconnect": "none"}},
             "none")
        )
        for name, result, expected_advice in cases:
            with self.subTest(msg=name):
                task = self.loop.create_future()
                task.set_result(result)
                self.transport._reconnect_advice = {
                    "interval": 1
                }
                self.transport._follow_advice = mock.MagicMock()
                self.transport._state = TransportState.CONNECTING
                self.transport._reconnect_timeout = 2

                with self.assertLogs(TransportBase.__module__, "DEBUG") as log:
                    self.transport._connect_done(task)

                log_message = "Connect task finished with: {!r}".format(result)
                self.assertEqual(
                    log.output,
                    ["DEBUG:{}:{}".format(TransportBase.__module__,
                                          log_message)])
                self.transport._follow_advice.assert_called_with(
                    expected_advice,
                    1
                )
                self.assertEqual(self.transport.state,
                                 TransportState.CONNECTED)

    async def test_connect_done_with_error(self):
        error = RuntimeError("error")
        task = self.loop.create_future()
        task.set_exception(error)
        self.transport._follow_advice = mock.MagicMock()
        self.transport._state = TransportState.CONNECTED
        self.transport._reconnect_timeout = 2

        with self.assertLogs(TransportBase.__module__, "DEBUG") as log:
            self.transport._connect_done(task)

        log_message = "Connect task finished with: {!r}".format(error)
        self.assertEqual(
            log.output,
            ["DEBUG:{}:{}".format(TransportBase.__module__, log_message)])
        self.transport._follow_advice.assert_called_with("retry", 2)
        self.assertEqual(self.transport.state, TransportState.CONNECTING)

    async def test_connect_dont_follow_advice_on_disconnecting(self):
        error = RuntimeError("error")
        task = self.loop.create_future()
        task.set_exception(error)
        self.transport._follow_advice = mock.MagicMock()
        self.transport._state = TransportState.DISCONNECTING
        self.transport._reconnect_advice = {
            "interval": 1,
            "reconnect": "retry"
        }
        self.transport._reconnect_timeout = 2

        with self.assertLogs(TransportBase.__module__, "DEBUG") as log:
            self.transport._connect_done(task)

        log_message = "Connect task finished with: {!r}".format(error)
        self.assertEqual(
            log.output,
            ["DEBUG:{}:{}".format(TransportBase.__module__, log_message)])
        self.transport._follow_advice.assert_not_called()

    @mock.patch("aiocometd.transports.base.defer")
    def test_follow_advice_handshake(self, defer):
        self.transport.handshake = mock.MagicMock(return_value=object())
        self.transport._connect = mock.MagicMock(return_value=object())
        self.transport._start_connect_task = mock.MagicMock()
        defer.return_value = mock.MagicMock(return_value=object())

        self.transport._follow_advice("handshake", 5)

        defer.assert_called_with(self.transport.handshake,
                                 delay=5,
                                 loop=self.transport._loop)
        defer.return_value.assert_called_with([self.transport.connection_type])
        self.transport._connect.assert_not_called()
        self.transport._start_connect_task.assert_called_with(
            defer.return_value.return_value
        )

    @mock.patch("aiocometd.transports.base.defer")
    def test_follow_advice_retry(self, defer):
        self.transport.handshake = mock.MagicMock(return_value=object())
        self.transport._connect = mock.MagicMock(return_value=object())
        self.transport._start_connect_task = mock.MagicMock()
        defer.return_value = mock.MagicMock(return_value=object())

        self.transport._follow_advice("retry", 5)

        defer.assert_called_with(self.transport._connect,
                                 delay=5,
                                 loop=self.transport._loop)
        defer.return_value.assert_called()
        self.transport.handshake.assert_not_called()
        self.transport._start_connect_task.assert_called_with(
            defer.return_value.return_value
        )

    @mock.patch("aiocometd.transports.base.defer")
    def test_follow_advice_none(self, defer):
        cases = (
            ("none string", "none"),
            ("emtpy string", ""),
            ("None value", None)
        )
        for name, advice in cases:
            with self.subTest(msg=name):
                self.transport._state = TransportState.CONNECTED
                self.transport.handshake = \
                    mock.MagicMock(return_value=object())
                self.transport._connect = mock.MagicMock(return_value=object())
                self.transport._start_connect_task = mock.MagicMock()
                defer.return_value = mock.MagicMock()

                with self.assertLogs(TransportBase.__module__, "DEBUG") as log:
                    self.transport._follow_advice(advice, 5)

                self.assertEqual(log.output,
                                 ["WARNING:{}:No reconnect "
                                  "advice provided, no more operations will"
                                  " be scheduled."
                                  .format(TransportBase.__module__)])
                defer.assert_not_called()
                self.transport.handshake.assert_not_called()
                self.transport._connect.assert_not_called()
                self.transport._start_connect_task.assert_not_called()
                self.assertEqual(self.transport.state,
                                 TransportState.SERVER_DISCONNECTED)

    def test_client_id(self):
        self.assertIs(self.transport.client_id,
                      self.transport._client_id)

    def test_client_id_read_only(self):
        with self.assertRaises(AttributeError):
            self.transport.client_id = "id"

    def test_endpoint(self):
        self.assertIs(self.transport.endpoint,
                      self.transport._url)

    def test_endpoint_read_only(self):
        with self.assertRaises(AttributeError):
            self.transport.endpoint = ""

    async def test_disconnect(self):
        self.transport._state = TransportState.CONNECTED
        self.transport._stop_connect_task = mock.CoroutineMock()
        self.transport._send_message = mock.CoroutineMock()

        await self.transport.disconnect()

        self.assertEqual(self.transport.state, TransportState.DISCONNECTED)
        self.transport._stop_connect_task.assert_called()
        self.transport._send_message.assert_called_with(
            DISCONNECT_MESSAGE)

    async def test_disconnect_transport_error(self):
        self.transport._state = TransportState.CONNECTED
        self.transport._stop_connect_task = mock.CoroutineMock()
        self.transport._send_message = mock.CoroutineMock(
            side_effect=TransportError())

        await self.transport.disconnect()

        self.assertEqual(self.transport.state, TransportState.DISCONNECTED)
        self.transport._stop_connect_task.assert_called()
        self.transport._send_message.assert_called_with(
            DISCONNECT_MESSAGE)

    async def test_disconnect_if_not_connected(self):
        for state in (s for s in TransportState
                      if s != TransportState.CONNECTED):
            self.transport._state = state
            self.transport._stop_connect_task = mock.CoroutineMock()
            self.transport._send_message = mock.CoroutineMock()

            await self.transport.disconnect()

            self.assertEqual(self.transport.state, TransportState.DISCONNECTED)
            self.transport._stop_connect_task.assert_called()
            self.transport._send_message.assert_not_called()

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
                SUBSCRIBE_MESSAGE,
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
                UNSUBSCRIBE_MESSAGE,
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
                PUBLISH_MESSAGE,
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

    async def test_wait_for_state(self):
        state = TransportState.CONNECTING
        event = self.transport._state_events[state]
        event.wait = mock.CoroutineMock()

        await self.transport.wait_for_state(state)

        event.wait.assert_called()

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

    async def test_process_outgoing_payload_without_auth(self):
        extension = mock.create_autospec(spec=Extension)
        self.transport._extensions = [extension]
        self.transport._auth = None
        payload = object()
        headers = object()

        await self.transport._process_outgoing_payload(payload, headers)

        extension.outgoing.assert_called_with(payload, headers)

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

    @mock.patch("aiocometd.transports.base.is_auth_error_message")
    async def test_send_payload_with_auth_with_extension(
            self, is_auth_error_message):
        response = object()
        payload = object()
        self.transport._send_payload = mock.CoroutineMock(
            return_value=response)
        self.transport._auth = mock.create_autospec(spec=AuthExtension)
        is_auth_error_message.return_value = False

        result = await self.transport._send_payload_with_auth(payload)

        self.assertIs(result, response)
        self.transport._send_payload.assert_called_with(payload)
        is_auth_error_message.assert_called_with(response)
        self.transport._auth.authenticate.assert_not_called()

    @mock.patch("aiocometd.transports.base.is_auth_error_message")
    async def test_send_payload_with_auth_with_extension_error(
            self, is_auth_error_message):
        response = object()
        response2 = object()
        payload = object()
        self.transport._send_payload = mock.CoroutineMock(
            side_effect=[response, response2])
        self.transport._auth = mock.create_autospec(spec=AuthExtension)
        is_auth_error_message.return_value = True

        result = await self.transport._send_payload_with_auth(payload)

        self.assertIs(result, response2)
        self.transport._send_payload.assert_has_calls([
            mock.call(payload), mock.call(payload)
        ])
        is_auth_error_message.assert_called_with(response)
        self.transport._auth.authenticate.assert_called()

    def test_state_sunder(self):
        result = self.transport._state

        self.assertEqual(result, self.transport.__dict__["_state"])

    def test_state_sunder_setter(self):
        state = TransportState.CONNECTED
        self.assertNotEqual(self.transport.__dict__["_state"], state)
        old_state = self.transport._state
        self.transport._set_state_event = mock.MagicMock()

        self.transport._state = state

        self.assertEqual(self.transport.__dict__["_state"], state)
        self.transport._set_state_event.assert_called_with(old_state, state)

    def test_set_state_event(self):
        old_state = TransportState.DISCONNECTED
        new_state = TransportState.CONNECTED
        self.transport._state_events[old_state].set()
        self.transport._state_events[new_state].clear()

        self.transport._set_state_event(old_state, new_state)

        self.assertFalse(self.transport._state_events[old_state].is_set())
        self.assertTrue(self.transport._state_events[new_state].is_set())

    def test_set_state_event_unchanged_state(self):
        state = TransportState.CONNECTED
        event_mock = mock.MagicMock()
        self.transport._state_events[state] = event_mock

        self.transport._set_state_event(state, state)

        event_mock.set.assert_not_called()
        event_mock.clear.assert_not_called()

    def test_last_connect_result(self):
        self.transport._connect_task = mock.MagicMock()
        self.transport._connect_task.done.return_value = True
        self.transport._connect_task.result.return_value = object()

        result = self.transport.last_connect_result

        self.assertIs(result, self.transport._connect_task.result.return_value)

    def test_last_connect_result_on_no_connect_task(self):
        self.transport._connect_task = None

        result = self.transport.last_connect_result

        self.assertIsNone(result)

    def test_request_timeout_int(self):
        self.transport._reconnect_advice = {
            "timeout": 2000
        }

        self.assertEqual(self.transport.request_timeout,
                         (self.transport.reconnect_advice["timeout"] / 1000) *
                         type(self.transport).REQUEST_TIMEOUT_INCREASE_FACTOR)

    def test_request_timeout_float(self):
        self.transport._reconnect_advice = {
            "timeout": 2000.0
        }

        self.assertEqual(self.transport.request_timeout,
                         (self.transport.reconnect_advice["timeout"] / 1000) *
                         type(self.transport).REQUEST_TIMEOUT_INCREASE_FACTOR)

    def test_request_timeout_none(self):
        self.transport._reconnect_advice = {}

        self.assertIsNone(self.transport.request_timeout)

    def test_request_timeout_none_on_unsupported_timeout_type(self):
        self.transport._reconnect_advice = {
            "timeout": "2000"
        }

        self.assertIsNone(self.transport.request_timeout)
