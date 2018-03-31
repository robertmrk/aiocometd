import asyncio

from asynctest import TestCase, mock
from aiohttp import ClientSession, client_exceptions

from aiocometd.transport import LongPollingTransport
from aiocometd.exceptions import TransportError, ServerError


class TestLongPollingTransport(TestCase):
    def setUp(self):
        self.transport = LongPollingTransport(endpoint="example.com/cometd",
                                              incoming_queue=None,
                                              loop=None)

    def test_init_with_loop(self):
        loop = object()

        transport = LongPollingTransport(endpoint=None,
                                         incoming_queue=None,
                                         loop=loop)

        self.assertIs(transport.loop, loop)

    @mock.patch("aiocometd.transport.asyncio")
    def test_init_without_loop(self, asyncio_mock):
        loop = object()
        asyncio_mock.get_event_loop.return_value = loop

        transport = LongPollingTransport(endpoint=None,
                                         incoming_queue=None)

        self.assertIs(transport.loop, loop)

    def test_finalize_message_updates_fields(self):
        message = {
            "field": "value",
            "id": None,
            "clientId": None
        }
        self.transport.client_id = "client_id"

        self.transport._finalize_message(message)

        self.assertEqual(message["id"], str(0))
        self.assertEqual(self.transport._message_id, 1)
        self.assertEqual(message["clientId"], self.transport.client_id)

    def test_finalize_message_ignores_non_existing_fields(self):
        message = {
            "field": "value"
        }
        self.transport.client_id = "client_id"

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

    async def test_send_payload(self):
        self.transport.client_id = "clientId"
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
        session.post.assert_called_with(self.transport.endpoint,
                                        json=payload)
        for i, message in enumerate(payload):
            self.assertEqual(message["id"], str(i))
            self.assertEqual(message["clientId"], self.transport.client_id)

    async def test_send_payload_client_error(self):
        self.transport.client_id = "clientId"
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
        session.post.assert_called_with(self.transport.endpoint,
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
                "id": "3"
            }
        ]
        self.transport.incoming_queue = asyncio.Queue()

        result = await self.transport._consume_payload(payload)

        self.assertIsNone(result)
        self.assertEqual(self.transport._reconnect_advice,
                         payload[4]["advice"])
        consumed_messages = []
        while not self.transport.incoming_queue.empty():
            consumed_messages.append(await self.transport.incoming_queue.get())
        self.assertEqual(consumed_messages, [payload[0]])

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
                "id": "3"
            }
        ]
        self.transport.incoming_queue = asyncio.Queue()

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
        self.assertEqual(len(consumed_messages), 3)
        self.assertEqual(consumed_messages[0], payload[0])
        self.assertIsInstance(consumed_messages[1], ServerError)
        self.assertEqual(consumed_messages[1].message, payload[3])
        self.assertIsInstance(consumed_messages[2], ServerError)
        self.assertEqual(consumed_messages[2].message, payload[5])

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

    async def test_handshake(self):
        connection_types = ["type1"]
        response = {
            "clientId": "id1"
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

        result = await self.transport.handshake(connection_types)

        self.assertEqual(result, response)
        self.transport._send_message.assert_called_with(
            message,
            supportedConnectionTypes=connection_types + ["long-polling"])
        self.assertEqual(self.transport.client_id, response["clientId"])
