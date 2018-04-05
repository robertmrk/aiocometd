import asyncio

from asynctest import TestCase, mock
from aiohttp import ClientSession, client_exceptions

from aiocometd.transport import LongPollingTransport, TransportState
from aiocometd.exceptions import TransportError, TransportInvalidOperation


class TestLongPollingTransport(TestCase):
    def setUp(self):
        self.transport = LongPollingTransport(endpoint="example.com/cometd",
                                              incoming_queue=None,
                                              loop=None)

    async def long_task(self, result, timeout=None):
        if timeout:
            asyncio.sleep(timeout, loop=self.loop)
        if not isinstance(result, Exception):
            return result
        else:
            raise result

    def test_init_with_loop(self):
        loop = object()

        transport = LongPollingTransport(endpoint=None,
                                         incoming_queue=None,
                                         loop=loop)

        self.assertIs(transport._loop, loop)
        self.assertEqual(transport.state, TransportState.DISCONNECTED)

    @mock.patch("aiocometd.transport.asyncio")
    def test_init_without_loop(self, asyncio_mock):
        loop = object()
        asyncio_mock.get_event_loop.return_value = loop

        transport = LongPollingTransport(endpoint=None,
                                         incoming_queue=None)

        self.assertIs(transport._loop, loop)
        self.assertEqual(transport.state, TransportState.DISCONNECTED)

    def test_finalize_message_updates_fields(self):
        message = {
            "field": "value",
            "id": None,
            "clientId": None
        }
        self.transport._client_id = "client_id"

        self.transport._finalize_message(message)

        self.assertEqual(message["id"], str(0))
        self.assertEqual(self.transport._message_id, 1)
        self.assertEqual(message["clientId"], self.transport.client_id)

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
                "clientId": None
            },
            {
                "field2": "value2",
                "id": None,
                "clientId": None
            }
        ]
        self.transport._finalize_message = mock.MagicMock()

        self.transport._finalize_payload(payload)

        self.transport._finalize_message.assert_has_calls([
            mock.call(payload[0]), mock.call(payload[1])
        ])

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

    async def test_send_payload(self):
        self.transport._client_id = "clientId"
        self._message_id = 0
        resp_data = [{
            "channel": "test/channel3",
            "id": 4
        }]
        response_mock = mock.MagicMock()
        response_mock.json = mock.CoroutineMock(return_value=resp_data)
        session = mock.MagicMock()
        session.post = mock.CoroutineMock(return_value=response_mock)
        self.transport._get_http_session = \
            mock.CoroutineMock(return_value=session)
        self.transport._http_semaphore = mock.MagicMock()
        payload = [
            {
                "id": None,
                "clientId": None,
                "channel": "/test/channel1"
            },
            {
                "id": None,
                "clientId": None,
                "channel": "/test/channel2"
            }
        ]

        response = await self.transport._send_payload(payload)

        self.assertEqual(response, resp_data)
        self.transport._http_semaphore.__aenter__.assert_called()
        self.transport._http_semaphore.__aexit__.assert_called()
        session.post.assert_called_with(self.transport._endpoint,
                                        json=payload)
        for i, message in enumerate(payload):
            self.assertEqual(message["id"], str(i))
            self.assertEqual(message["clientId"], self.transport.client_id)

    async def test_send_payload_client_error(self):
        self.transport._client_id = "clientId"
        self._message_id = 0
        resp_data = [{
            "channel": "test/channel3",
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
        payload = [
            {
                "id": None,
                "clientId": None,
                "channel": "/test/channel1"
            },
            {
                "id": None,
                "clientId": None,
                "channel": "/test/channel2"
            }
        ]

        with self.assertLogs("aiocometd.transport", level="DEBUG") as log:
            with self.assertRaisesRegex(TransportError, str(post_exception)):
                await self.transport._send_payload(payload)

        log_message = "DEBUG:aiocometd.transport:" \
                      "Failed to send payload, {}".format(post_exception)
        self.assertEqual(log.output, [log_message])
        self.transport._http_semaphore.__aenter__.assert_called()
        self.transport._http_semaphore.__aexit__.assert_called()
        session.post.assert_called_with(self.transport._endpoint,
                                        json=payload)
        for i, message in enumerate(payload):
            self.assertEqual(message["id"], str(i))
            self.assertEqual(message["clientId"], self.transport.client_id)

    def test_is_confirmation(self):
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

        self.assertTrue(self.transport._is_confirmation(response, message))

    def test_is_confirmation_without_id(self):
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

        self.assertTrue(self.transport._is_confirmation(response, message))

    def test_is_confirmation_different_id(self):
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

        self.assertFalse(self.transport._is_confirmation(response, message))

    def test_is_confirmation_different_channel(self):
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

        self.assertFalse(self.transport._is_confirmation(response, message))

    def test_is_confirmation_without_successful_field(self):
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

        self.assertFalse(self.transport._is_confirmation(response, message))

    async def test_consume_payload(self):
        payload = [
            # event message
            {
                "channel": "/test/channel1",
                "data": {"key": "value"},
                "id": "1"
            },
            # connect confirmation
            {
                "channel": "/meta/connect",
                "successful": True,
                "advice": {"interval": 0, "reconnect": "retry"},
                "id": "2"
            },
            # subscribe confirmation, success
            {
                "channel": "/meta/subscribe",
                "subscription": "/test/channel1",
                "successful": True,
                "id": "3"
            },
            # subscribe confirmation, failure
            {
                "channel": "/meta/subscribe",
                "subscription": "/test/channel2",
                "successful": False,
                "id": "4"
            },
            # connect confirmation
            {
                "channel": "/meta/connect",
                "successful": True,
                "advice": {"interval": 2, "reconnect": "none"},
                "id": "5"
            },
            # service confirmation, failure
            {
                "channel": "/service/test",
                "successful": False,
                "id": "6"
            },
            # unsubscribe confirmation, success
            {
                "channel": "/meta/unsubscribe",
                "subscription": "/test/channel3",
                "successful": True,
                "id": "7"
            },
            # unsubscribe confirmation, failure
            {
                "channel": "/meta/unsubscribe",
                "subscription": "/test/channel4",
                "successful": False,
                "id": "8"
            }
        ]
        self.transport.incoming_queue = asyncio.Queue()
        self.transport._subscriptions = {"/test/channel2",
                                         "/test/channel3",
                                         "/test/channel4"}

        result = await self.transport._consume_payload(payload)

        self.assertIsNone(result)
        self.assertEqual(self.transport._reconnect_advice,
                         payload[4]["advice"])
        consumed_messages = []
        while not self.transport.incoming_queue.empty():
            consumed_messages.append(await self.transport.incoming_queue.get())
        self.assertEqual(consumed_messages, [payload[0]])
        self.assertEqual(self.transport.subscriptions,
                         {"/test/channel1", "/test/channel4"})

    async def test_consume_payload_with_confirm_and_subscription(self):
        message = {
            "channel": "/meta/subscribe",
            "subscription": "/test/channel1",
            "id": "3"
        }
        payload = [
            # event message
            {
                "channel": "/test/channel1",
                "data": {"key": "value"},
                "id": "1"
            },
            # connect confirmation
            {
                "channel": "/meta/connect",
                "successful": True,
                "advice": {"interval": 0, "reconnect": "retry"},
                "id": "2"
            },
            # subscribe confirmation, success
            {
                "channel": "/meta/subscribe",
                "subscription": "/test/channel1",
                "successful": True,
                "id": "3"
            },
            # subscribe confirmation, failure
            {
                "channel": "/meta/subscribe",
                "subscription": "/test/channel2",
                "successful": False,
                "id": "4"
            },
            # connect confirmation
            {
                "channel": "/meta/connect",
                "successful": True,
                "advice": {"interval": 2, "reconnect": "none"},
                "id": "5"
            },
            # service confirmation, failure
            {
                "channel": "/service/test",
                "successful": False,
                "id": "6"
            },
            # unsubscribe confirmation, success
            {
                "channel": "/meta/unsubscribe",
                "subscription": "/test/channel3",
                "successful": True,
                "id": "7"
            },
            # unsubscribe confirmation, failure
            {
                "channel": "/meta/unsubscribe",
                "subscription": "/test/channel4",
                "successful": False,
                "id": "8"
            }
        ]
        self.transport.incoming_queue = asyncio.Queue()
        self.transport._subscriptions = {"/test/channel2",
                                         "/test/channel3",
                                         "/test/channel4"}

        result = \
            await self.transport._consume_payload(payload,
                                                  confirm_for=message,
                                                  consume_server_errors=True)

        self.assertIs(result, payload[2])
        self.assertEqual(self.transport._reconnect_advice,
                         payload[4]["advice"])

        consumed_messages = []
        while not self.transport.incoming_queue.empty():
            consumed_messages.append(await self.transport.incoming_queue.get())
        self.assertEqual(len(consumed_messages), 4)
        self.assertEqual(consumed_messages[0], payload[0])
        self.assertEqual(consumed_messages[1], payload[3])
        self.assertEqual(consumed_messages[2], payload[5])
        self.assertEqual(consumed_messages[3], payload[7])
        self.assertEqual(self.transport.subscriptions,
                         {"/test/channel1", "/test/channel4"})

    async def test_send_message(self):
        message = {
            "channel": "/test/channel1",
            "data": {},
            "clientId": None,
            "id": "1"
        }
        response = object()
        response_payload = object()
        self.transport._send_payload = \
            mock.CoroutineMock(return_value=response_payload)
        self.transport._consume_payload = \
            mock.CoroutineMock(return_value=response)

        result = await self.transport._send_message(message,
                                                    clientId="fake_id",
                                                    id="2")

        self.assertIs(result, response)
        self.assertEqual(message["clientId"], "fake_id")
        self.assertEqual(message["id"], "2")
        self.transport._send_payload.assert_called_with(message)
        self.transport._consume_payload.assert_called_with(response_payload,
                                                           confirm_for=message)

    async def test_send_message_with_additional_messages(self):
        message = {
            "channel": "/test/channel1",
            "data": {},
            "clientId": None,
            "id": "1"
        }
        additional_messages = [
            {
                "channel": "/test/channel2",
                "data": {},
                "clientId": None,
                "id": "2"
            }
        ]
        response = object()
        response_payload = object()
        self.transport._send_payload = \
            mock.CoroutineMock(return_value=response_payload)
        self.transport._consume_payload = \
            mock.CoroutineMock(return_value=response)

        result = await self.transport._send_message(
            message,
            additional_messages=additional_messages,
            clientId="fake_id",
            id="2")

        self.assertIs(result, response)
        self.assertEqual(message["clientId"], "fake_id")
        self.assertEqual(message["id"], "2")
        self.transport._send_payload.assert_called_with(
            [message] + additional_messages)
        self.transport._consume_payload.assert_called_with(response_payload,
                                                           confirm_for=message)

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
            supportedConnectionTypes=connection_types + ["long-polling"])
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
            supportedConnectionTypes=connection_types + ["long-polling"])
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
        self.transport._send_message = \
            mock.CoroutineMock(return_value=response)

        result = await self.transport._connect()

        self.assertEqual(result, response)
        sleep.assert_not_called()
        self.transport._send_message.assert_called_with(
            self.transport._CONNECT_MESSAGE,
            additional_messages=None,
            consume_server_errors=True
        )
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
        self.transport._send_message = \
            mock.CoroutineMock(return_value=response)

        result = await self.transport._connect(5)

        self.assertEqual(result, response)
        sleep.assert_called_with(5, loop=self.transport._loop)
        self.transport._send_message.assert_called_with(
            self.transport._CONNECT_MESSAGE,
            additional_messages=None,
            consume_server_errors=True
        )
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
        self.transport._send_message = \
            mock.CoroutineMock(return_value=response)

        result = await self.transport._connect()

        self.assertEqual(result, response)
        self.transport._send_message.assert_called_with(
            self.transport._CONNECT_MESSAGE,
            additional_messages=additional_messages,
            consume_server_errors=True
        )
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
        self.transport._send_message = \
            mock.CoroutineMock(return_value=response)

        result = await self.transport._connect()

        self.assertEqual(result, response)
        self.transport._send_message.assert_called_with(
            self.transport._CONNECT_MESSAGE,
            additional_messages=additional_messages,
            consume_server_errors=True
        )
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

    async def test_connect_done_with_error(self):
        error = RuntimeError("error")
        task = asyncio.ensure_future(self.long_task(error))
        await asyncio.wait([task])
        self.transport._follow_advice = mock.MagicMock()
        self.transport._state = TransportState.CONNECTED
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

        self.transport._handshake.assert_called_with([self.transport.NAME],
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
        for state in [TransportState.CONNECTED, TransportState.CONNECTING]:
            self.transport._state = state
            self.transport._stop_connect_task = mock.CoroutineMock()
            self.transport._send_message = mock.CoroutineMock()
            self.transport._close_http_session = mock.CoroutineMock()

            await self.transport.disconnect()

            self.assertEqual(self.transport.state, TransportState.DISCONNECTED)
            self.transport._stop_connect_task.assert_called()
            self.transport._send_message.assert_called_with(
                self.transport._DISCONNECT_MESSAGE)
            self.transport._close_http_session.assert_called()

    async def test_disconnect_does_nothing_if_not_connected(self):
        for state in TransportState:
            if state not in [TransportState.CONNECTED,
                             TransportState.CONNECTING]:
                self.transport._state = state
                self.transport._stop_connect_task = mock.CoroutineMock()
                self.transport._send_message = mock.CoroutineMock()
                self.transport._close_http_session = mock.CoroutineMock()

                await self.transport.disconnect()

                self.assertEqual(self.transport.state, state)
                self.transport._stop_connect_task.assert_not_called()
                self.transport._send_message.assert_not_called()
                self.transport._close_http_session.assert_not_called()

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
