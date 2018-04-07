import asyncio
import reprlib

from asynctest import TestCase, mock

from aiocometd.client import Client
from aiocometd.exceptions import ServerError, ClientInvalidOperation, \
    TransportError, TransportTimeoutError


class TestClient(TestCase):
    def setUp(self):
        self.client = Client("")

    def test_init_with_loop(self):
        loop = object()

        client = Client(endpoint=None, loop=loop)

        self.assertIs(client._loop, loop)

    async def long_task(self, result, timeout=None):
        if timeout:
            await asyncio.sleep(timeout, loop=self.loop)
        if not isinstance(result, Exception):
            return result
        else:
            raise result

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
        self.client.ssl = object()
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
        transport.name = "transport name"
        transport.handshake = \
            mock.CoroutineMock(return_value=handshake_response)
        transport.connect = mock.CoroutineMock(return_value=connect_response)
        transport_cls_mock.return_value = transport

        await self.client.open()

        self.assertIsInstance(self.client._incoming_queue, asyncio.Queue)
        transport_cls_mock.assert_called_with(
            endpoint=self.client.endpoint,
            incoming_queue=self.client._incoming_queue,
            ssl=self.client.ssl
        )
        transport.handshake.assert_called_with([transport.name])
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
        self.client.ssl = object()
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
        transport.name = "transport name"
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
            incoming_queue=self.client._incoming_queue,
            ssl=self.client.ssl
        )
        transport.handshake.assert_called_with([transport.name])
        self.assertTrue(self.client.closed)

    @mock.patch("aiocometd.client.transport.LongPollingTransport")
    async def test_open_connect_error(self, transport_cls_mock):
        self.client.endpoint = "http://example.com"
        self.client._incoming_queue = None
        self.client.ssl = object()
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
        transport.name = "transport name"
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
            incoming_queue=self.client._incoming_queue,
            ssl=self.client.ssl
        )
        transport.handshake.assert_called_with([transport.name])
        self.assertTrue(self.client.closed)

    async def test_close(self):
        self.client._closed = False
        self.client._transport = mock.MagicMock()
        self.client._transport.client_id = "client_id"
        self.client._transport.disconnect = mock.CoroutineMock()
        self.client._transport.close = mock.CoroutineMock()

        await self.client.close()

        self.client._transport.disconnect.assert_called()
        self.client._transport.close.assert_called()
        self.assertTrue(self.client.closed)

    async def test_close_no_client_id(self):
        self.client._closed = False
        self.client._transport = mock.MagicMock()
        self.client._transport.client_id = None
        self.client._transport.disconnect = mock.CoroutineMock()
        self.client._transport.close = mock.CoroutineMock()

        await self.client.close()

        self.client._transport.disconnect.assert_not_called()
        self.client._transport.close.assert_called()
        self.assertTrue(self.client.closed)

    async def test_close_if_already_closed(self):
        self.client._closed = True
        self.client._transport = mock.MagicMock()
        self.client._transport.client_id = "client_id"
        self.client._transport.disconnect = mock.CoroutineMock()
        self.client._transport.close = mock.CoroutineMock()

        await self.client.close()

        self.client._transport.disconnect.assert_called()
        self.client._transport.close.assert_called()
        self.assertTrue(self.client.closed)

    async def test_close_on_transport_error(self):
        self.client._closed = False
        self.client._transport = mock.MagicMock()
        self.client._transport.client_id = "client_id"
        error = TransportError("description")
        self.client._transport.disconnect = mock.CoroutineMock(
            side_effect=error
        )
        self.client._transport.close = mock.CoroutineMock()
        expected_log = ["DEBUG:aiocometd.client:"
                        "Disconnect request failed, {}".format(error)]

        with self.assertLogs("aiocometd.client", "DEBUG") as log:
            await self.client.close()

        self.assertEqual(log.output, expected_log)
        self.client._transport.disconnect.assert_called()
        self.client._transport.close.assert_called()
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
        self.client._incoming_queue = mock.MagicMock()
        self.client._incoming_queue.qsize.return_value = 1
        self.client._get_message = mock.CoroutineMock(return_value=response)
        self.client._verify_response = mock.MagicMock()

        result = await self.client.receive()

        self.assertEqual(result, response)
        self.client._get_message.assert_called_with(
            self.client.connection_timeout)
        self.client._verify_response.assert_called_with(response)

    async def test_receive_on_open(self):
        self.client._closed = False
        response = {
            "channel": "/channel1",
            "data": {},
            "id": "1"
        }
        self.client._incoming_queue = mock.MagicMock()
        self.client._incoming_queue.qsize.return_value = 1
        self.client._get_message = mock.CoroutineMock(return_value=response)
        self.client._verify_response = mock.MagicMock()

        result = await self.client.receive()

        self.assertEqual(result, response)
        self.client._get_message.assert_called_with(
            self.client.connection_timeout)
        self.client._verify_response.assert_called_with(response)

    async def test_receive_on_connection_timeout(self):
        self.client._closed = True
        self.client._incoming_queue = mock.MagicMock()
        self.client._incoming_queue.qsize.return_value = 1
        self.client._get_message = mock.CoroutineMock(
            side_effect=TransportTimeoutError())
        self.client._verify_response = mock.MagicMock()

        with self.assertRaises(TransportTimeoutError):
            await self.client.receive()

        self.client._get_message.assert_called_with(
            self.client.connection_timeout)
        self.client._verify_response.assert_not_called()

    async def test_aiter(self):
        responses = [
            {
                "channel": "/channel1",
                "data": {},
                "id": "1"
            },
            {
                "channel": "/channel2",
                "data": {},
                "id": "2"
            }
        ]
        self.client.receive = mock.CoroutineMock(
            side_effect=responses + [ClientInvalidOperation()])

        result = []
        async for message in self.client:
            result.append(message)

        self.assertEqual(result, responses)

    async def test_context_manager(self):
        self.client.open = mock.CoroutineMock()
        self.client.close = mock.CoroutineMock()

        async with self.client as client:
            pass

        self.assertIs(client, self.client)
        self.client.open.assert_called()
        self.client.close.assert_called()

    async def test_context_manager_on_enter_error(self):
        self.client.open = mock.CoroutineMock(
            side_effect=TransportError()
        )
        self.client.close = mock.CoroutineMock()

        with self.assertRaises(TransportError):
            async with self.client:
                pass

        self.client.open.assert_called()
        self.client.close.assert_called()

    @mock.patch("aiocometd.client.asyncio")
    async def test_wait_connection_timeout_on_timeout(self, asyncio_mock):
        self.client._transport = mock.MagicMock()
        self.client._transport.wait_for_connecting = mock.CoroutineMock()
        self.client._transport.wait_for_connected = mock.MagicMock(
            return_value=object()
        )
        timeout = 2
        asyncio_mock.wait_for = mock.CoroutineMock(
            side_effect=asyncio.TimeoutError()
        )
        asyncio_mock.TimeoutError = asyncio.TimeoutError

        await self.client._wait_connection_timeout(timeout)

        self.client._transport.wait_for_connecting.assert_called_once()
        self.client._transport.wait_for_connected.assert_called_once()
        asyncio_mock.wait_for.assert_called_with(
            self.client._transport.wait_for_connected.return_value,
            timeout,
            loop=self.client._loop
        )

    @mock.patch("aiocometd.client.asyncio")
    async def test_wait_connection_timeout_iterations(self, asyncio_mock):
        self.client._transport = mock.MagicMock()
        self.client._transport.wait_for_connecting = mock.CoroutineMock()
        self.client._transport.wait_for_connected = mock.MagicMock(
            return_value=object()
        )
        timeout = 2
        asyncio_mock.wait_for = mock.CoroutineMock(
            side_effect=[None, asyncio.TimeoutError()]
        )
        asyncio_mock.TimeoutError = asyncio.TimeoutError

        await self.client._wait_connection_timeout(timeout)

        self.client._transport.wait_for_connecting.assert_has_calls(
            [mock.call()] * 2
        )
        self.client._transport.wait_for_connecting.assert_has_calls(
            [mock.call()] * 2
        )
        asyncio_mock.wait_for.assert_has_calls(
            [mock.call(
                self.client._transport.wait_for_connected.return_value,
                timeout,
                loop=self.client._loop)] * 2
        )

    async def test_get_message_no_timeout(self):
        self.client._incoming_queue = mock.MagicMock()
        self.client._incoming_queue.get = mock.CoroutineMock(
            return_value=object()
        )
        self.client._wait_connection_timeout = mock.CoroutineMock()

        result = await self.client._get_message(None)

        self.assertIs(result, self.client._incoming_queue.get.return_value)
        self.client._wait_connection_timeout.assert_not_called()

    async def test_get_message_with_timeout_not_triggered(self):
        self.client._incoming_queue = mock.MagicMock()
        get_result = object()
        self.client._incoming_queue.get = mock.MagicMock(
            return_value=self.long_task(get_result, timeout=None)
        )
        self.client._wait_connection_timeout = mock.MagicMock(
            return_value=self.long_task(None, timeout=1)
        )
        timeout = 2

        result = await self.client._get_message(timeout)

        self.assertIs(result, get_result)
        self.client._wait_connection_timeout.assert_called_with(timeout)

    async def test_get_message_with_timeout_triggered(self):
        self.client._incoming_queue = mock.MagicMock()
        get_result = object()
        self.client._incoming_queue.get = mock.MagicMock(
            return_value=self.long_task(get_result, timeout=1)
        )
        self.client._wait_connection_timeout = mock.MagicMock(
            return_value=self.long_task(None, timeout=None)
        )
        timeout = 2

        with self.assertRaises(TransportTimeoutError,
                               msg="Lost connection with the server"):
            await self.client._get_message(timeout)

        self.client._wait_connection_timeout.assert_called_with(timeout)

    @mock.patch("aiocometd.client.asyncio")
    async def test_get_message_cancelled(self, asyncio_mock):
        self.client._incoming_queue = mock.MagicMock()
        self.client._wait_connection_timeout = mock.MagicMock()
        asyncio_mock.ensure_future = mock.MagicMock(
            side_effect=[mock.MagicMock(), mock.MagicMock()]
        )
        asyncio_mock.wait = mock.CoroutineMock(
            side_effect=asyncio.CancelledError()
        )
        asyncio_mock.CancelledError = asyncio.CancelledError

        with self.assertRaises(asyncio.CancelledError):
            await self.client._get_message(1)

        for task in asyncio_mock.ensure_future.side_effect:
            task.cancel.assert_called()
