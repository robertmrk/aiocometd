import asyncio
import reprlib

from asynctest import TestCase, mock

from aiocometd.client import Client
from aiocometd.exceptions import ServerError, ClientInvalidOperation


class TestClient(TestCase):
    def setUp(self):
        self.client = Client("")

    def test_init_with_loop(self):
        loop = object()

        client = Client(endpoint=None, loop=loop)

        self.assertIs(client._loop, loop)

    @mock.patch("aiocometd.client.asyncio")
    def test_init_without_loop(self, asyncio_mock):
        loop = object()
        asyncio_mock.get_event_loop.return_value = loop

        client = Client(endpoint=None)

        self.assertIs(client._loop, loop)

    def test_subscriptions(self):
        self.client._transport = mock.MagicMock()
        self.client._transport.subscriptions = {"channel1", "channel2"}

        result = self.client.subscriptions

        self.assertEqual(result, self.client._transport.subscriptions)

    def test_subscriptions_emtpy_on_none_transport(self):
        self.client._transport = None

        result = self.client.subscriptions

        self.assertEqual(result, set())

    def test_closed(self):
        self.assertIs(self.client.closed, self.client._closed)

    def test_closed_read_only(self):
        with self.assertRaises(AttributeError):
            self.client.closed = False

    @mock.patch("aiocometd.client.transport.LongPollingTransport")
    async def test_open(self, transport_cls_mock):
        self.client.endpoint = "http://example.com"
        self.client._incoming_queue = None
        handshake_response = {
            "channel": "/meta/handshake",
            "version": "1.0",
            "supportedConnectionTypes": ["long-polling"],
            "id": "1",
            "clientId": "clientId1",
            "successful": True
        }
        connect_response = {
            "channel": "/meta/connect",
            "successful": True,
            "id": "2"
        }
        transport = mock.MagicMock()
        transport.NAME = "transport name"
        transport.handshake = \
            mock.CoroutineMock(return_value=handshake_response)
        transport.connect = mock.CoroutineMock(return_value=connect_response)
        transport_cls_mock.return_value = transport

        await self.client.open()

        self.assertIsInstance(self.client._incoming_queue, asyncio.Queue)
        transport_cls_mock.assert_called_with(
            endpoint=self.client.endpoint,
            incoming_queue=self.client._incoming_queue
        )
        transport.handshake.assert_called_with([transport.NAME])
        transport.connect.assert_called()
        self.assertFalse(self.client.closed)

    @mock.patch("aiocometd.client.transport.LongPollingTransport")
    async def test_open_already_opened(self, transport_cls_mock):
        self.client.endpoint = "http://example.com"
        self.client._incoming_queue = None
        self.client._transport = None
        self.client._closed = False

        with self.assertRaises(ClientInvalidOperation,
                               msg="Client is already open."):
            await self.client.open()

        self.assertIsNone(self.client._incoming_queue)
        self.assertIsNone(self.client._transport)
        self.assertFalse(self.client.closed)

    @mock.patch("aiocometd.client.transport.LongPollingTransport")
    async def test_open_handshake_error(self, transport_cls_mock):
        self.client.endpoint = "http://example.com"
        self.client._incoming_queue = None
        handshake_response = {
            "channel": "/meta/handshake",
            "version": "1.0",
            "supportedConnectionTypes": ["long-polling"],
            "id": "1",
            "successful": False,
            "error": "401::Handshake failure"
        }
        connect_response = {
            "channel": "/meta/connect",
            "successful": True,
            "id": "2"
        }
        transport = mock.MagicMock()
        transport.NAME = "transport name"
        transport.handshake = \
            mock.CoroutineMock(return_value=handshake_response)
        transport.connect = mock.CoroutineMock(return_value=connect_response)
        transport_cls_mock.return_value = transport

        error = ServerError("Handshake request failed.", handshake_response)
        with self.assertRaises(ServerError, msg=str(error)):
            await self.client.open()

        self.assertIsInstance(self.client._incoming_queue, asyncio.Queue)
        transport_cls_mock.assert_called_with(
            endpoint=self.client.endpoint,
            incoming_queue=self.client._incoming_queue
        )
        transport.handshake.assert_called_with([transport.NAME])
        self.assertTrue(self.client.closed)

    @mock.patch("aiocometd.client.transport.LongPollingTransport")
    async def test_open_connect_error(self, transport_cls_mock):
        self.client.endpoint = "http://example.com"
        self.client._incoming_queue = None
        handshake_response = {
            "channel": "/meta/handshake",
            "version": "1.0",
            "supportedConnectionTypes": ["long-polling"],
            "id": "1",
            "clientId": "clientId1",
            "successful": True
        }
        connect_response = {
            "channel": "/meta/connect",
            "successful": False,
            "id": "2",
            "error": "401::Connection declined"
        }
        transport = mock.MagicMock()
        transport.NAME = "transport name"
        transport.handshake = \
            mock.CoroutineMock(return_value=handshake_response)
        transport.connect = mock.CoroutineMock(return_value=connect_response)
        transport_cls_mock.return_value = transport

        error = ServerError("Connect request failed.", connect_response)
        with self.assertRaises(ServerError, msg=str(error)):
            await self.client.open()

        self.assertIsInstance(self.client._incoming_queue, asyncio.Queue)
        transport_cls_mock.assert_called_with(
            endpoint=self.client.endpoint,
            incoming_queue=self.client._incoming_queue
        )
        transport.handshake.assert_called_with([transport.NAME])
        self.assertTrue(self.client.closed)

    async def test_disconnect(self):
        self.client._closed = False
        self.client._transport = mock.MagicMock()
        self.client._transport.disconnect = mock.CoroutineMock()

        await self.client.close()

        self.client._transport.disconnect.assert_called()
        self.assertTrue(self.client.closed)

    async def test_disconnect_if_closed(self):
        self.client._closed = True
        self.client._transport = mock.MagicMock()
        self.client._transport.disconnect = mock.CoroutineMock()

        await self.client.close()

        self.client._transport.disconnect.assert_not_called()
        self.assertTrue(self.client.closed)

    async def test_subscribe(self):
        response = {
            "channel": "/meta/subscribe",
            "successful": True,
            "subscription": "channel1",
            "id": "1"
        }
        self.client._transport = mock.MagicMock()
        self.client._transport.subscribe = mock.CoroutineMock(
            return_value=response
        )
        self.client._closed = False

        await self.client.subscribe("channel1")

        self.client._transport.subscribe.assert_called_with("channel1")

    async def test_subscribe_on_closed(self):
        self.client._closed = True

        with self.assertRaises(ClientInvalidOperation,
                               msg="Can't send subscribe request while, "
                                   "the client is closed."):
            await self.client.subscribe("channel1")

    async def test_subscribe_error(self):
        response = {
            "channel": "/meta/subscribe",
            "successful": False,
            "subscription": "channel1",
            "id": "1"
        }
        self.client._transport = mock.MagicMock()
        self.client._transport.subscribe = mock.CoroutineMock(
            return_value=response
        )
        self.client._closed = False
        error = ServerError("Subscribe request failed.", response)

        with self.assertRaises(ServerError, msg=str(error)):
            await self.client.subscribe("channel1")

        self.client._transport.subscribe.assert_called_with("channel1")

    async def test_unsubscribe(self):
        response = {
            "channel": "/meta/unsubscribe",
            "successful": True,
            "subscription": "channel1",
            "id": "1"
        }
        self.client._transport = mock.MagicMock()
        self.client._transport.unsubscribe = mock.CoroutineMock(
            return_value=response
        )
        self.client._closed = False

        await self.client.unsubscribe("channel1")

        self.client._transport.unsubscribe.assert_called_with("channel1")

    async def test_unsubscribe_on_closed(self):
        self.client._closed = True

        with self.assertRaises(ClientInvalidOperation,
                               msg="Can't send unsubscribe request while, "
                                   "the client is closed."):
            await self.client.unsubscribe("channel1")

    async def test_unsubscribe_error(self):
        response = {
            "channel": "/meta/unsubscribe",
            "successful": False,
            "subscription": "channel1",
            "id": "1"
        }
        self.client._transport = mock.MagicMock()
        self.client._transport.unsubscribe = mock.CoroutineMock(
            return_value=response
        )
        self.client._closed = False
        error = ServerError("Unsubscribe request failed.", response)

        with self.assertRaises(ServerError, msg=str(error)):
            await self.client.unsubscribe("channel1")

        self.client._transport.unsubscribe.assert_called_with("channel1")

    async def test_publish(self):
        response = {
            "channel": "/channel1",
            "successful": True,
            "id": "1"
        }
        data = {}
        self.client._transport = mock.MagicMock()
        self.client._transport.publish = mock.CoroutineMock(
            return_value=response
        )
        self.client._closed = False

        await self.client.publish("channel1", data)

        self.client._transport.publish.assert_called_with("channel1", data)

    async def test_publish_on_closed(self):
        self.client._closed = True

        with self.assertRaises(ClientInvalidOperation,
                               msg="Can't publish data while, "
                                   "the client is closed."):
            await self.client.publish("channel1", {})

    async def test_publish_error(self):
        response = {
            "channel": "/channel1",
            "successful": False,
            "id": "1"
        }
        data = {}
        self.client._transport = mock.MagicMock()
        self.client._transport.publish = mock.CoroutineMock(
            return_value=response
        )
        self.client._closed = False
        error = ServerError("Publish request failed.", response)

        with self.assertRaises(ServerError, msg=str(error)):
            await self.client.publish("channel1", data)

        self.client._transport.publish.assert_called_with("channel1", data)

    def test_repr(self):
        self.client.endpoint = "http://example.com"
        expected = "Client(endpoint={}, loop={})".format(
            reprlib.repr(self.client.endpoint),
            reprlib.repr(self.client._loop)
        )

        result = repr(self.client)

        self.assertEqual(result, expected)

    def test_verify_response_on_success(self):
        self.client._raise_server_error = mock.MagicMock()
        response = {
            "channel": "/channel1",
            "successful": True,
            "id": "1"
        }

        self.client._verify_response(response)

        self.client._raise_server_error.assert_not_called()

    def test_verify_response_on_error(self):
        self.client._raise_server_error = mock.MagicMock()
        response = {
            "channel": "/channel1",
            "successful": False,
            "id": "1"
        }

        self.client._verify_response(response)

        self.client._raise_server_error.assert_called_with(response)

    def test_verify_response_no_successful_status(self):
        self.client._raise_server_error = mock.MagicMock()
        response = {
            "channel": "/channel1",
            "id": "1"
        }

        self.client._verify_response(response)

        self.client._raise_server_error.assert_not_called()

    def test_raise_server_error_meta(self):
        response = {
            "channel": "/meta/subscribe",
            "successful": False,
            "id": "1"
        }
        error_message = \
            type(self.client)._SERVER_ERROR_MESSAGES[response["channel"]]

        with self.assertRaises(ServerError, msg=error_message):
            self.client._raise_server_error(response)

    def test_raise_server_error_service(self):
        response = {
            "channel": "/service/test",
            "successful": False,
            "id": "1"
        }

        with self.assertRaises(
                ServerError,
                msg="Service request failed."):
            self.client._raise_server_error(response)

    def test_raise_server_error_publish(self):
        response = {
            "channel": "/some/channel",
            "successful": False,
            "id": "1"
        }

        with self.assertRaises(
                ServerError,
                msg="Publish request failed."):
            self.client._raise_server_error(response)

    async def test_pending_count(self):
        self.client._incoming_queue = asyncio.Queue()
        await self.client._incoming_queue.put(1)
        await self.client._incoming_queue.put(2)

        self.assertEqual(self.client.pending_count, 2)

    async def test_pending_count_if_none_queue(self):
        self.client._incoming_queue = None

        self.assertEqual(self.client.pending_count, 0)

    async def test_has_pending_messages(self):
        self.client._incoming_queue = asyncio.Queue()
        await self.client._incoming_queue.put(1)

        self.assertTrue(self.client.has_pending_messages)

    async def test_has_pending_messages_false(self):
        self.client._incoming_queue = None

        self.assertFalse(self.client.has_pending_messages)

    async def test_receive_on_closed(self):
        self.client._closed = True
        self.client._incoming_queue = None

        with self.assertRaises(ClientInvalidOperation,
                               msg="The client is closed and there are "
                                   "no pending messages."):
            await self.client.receive()

    async def test_receive_on_closed_and_pending_messages(self):
        self.client._closed = True
        response = {
            "channel": "/channel1",
            "data": {},
            "id": "1"
        }
        self.client._incoming_queue = asyncio.Queue()
        await self.client._incoming_queue.put(response)
        self.client._verify_response = mock.MagicMock()

        result = await self.client.receive()

        self.assertEqual(result, response)
        self.client._verify_response.assert_called_with(response)

    async def test_receive_on_open(self):
        self.client._closed = False
        response = {
            "channel": "/channel1",
            "data": {},
            "id": "1"
        }
        self.client._incoming_queue = asyncio.Queue()
        await self.client._incoming_queue.put(response)
        self.client._verify_response = mock.MagicMock()

        result = await self.client.receive()

        self.assertEqual(result, response)
        self.client._verify_response.assert_called_with(response)
