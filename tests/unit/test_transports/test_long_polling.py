from asynctest import TestCase, mock

from aiohttp import client_exceptions

from aiocometd.transports.long_polling import LongPollingTransport
from aiocometd.constants import ConnectionType
from aiocometd.exceptions import TransportError


class TestLongPollingTransport(TestCase):
    def setUp(self):
        self.transport = LongPollingTransport(url="example.com/cometd",
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
        session.post.assert_called_with(self.transport._url,
                                        json=payload,
                                        ssl=self.transport.ssl,
                                        headers=headers,
                                        timeout=self.transport.request_timeout)
        response_mock.json.assert_called_with(loads=self.transport._json_loads)
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

        with self.assertLogs(LongPollingTransport.__module__,
                             level="DEBUG") as log:
            with self.assertRaisesRegex(TransportError, str(post_exception)):
                await self.transport._send_final_payload(payload,
                                                         headers=headers)

        log_message = "WARNING:{}:Failed to send payload, {}"\
            .format(LongPollingTransport.__module__, post_exception)
        self.assertEqual(log.output, [log_message])
        self.transport._http_semaphore.__aenter__.assert_called()
        self.transport._http_semaphore.__aexit__.assert_called()
        session.post.assert_called_with(self.transport._url,
                                        json=payload,
                                        ssl=self.transport.ssl,
                                        headers=headers,
                                        timeout=self.transport.request_timeout)
        self.transport._consume_payload.assert_not_called()

    async def test_send_payload_final_payload_missing_response(self):
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
            mock.CoroutineMock(return_value=None)
        headers = dict(key="value")
        error_message = "No response message received for the " \
                        "first message in the payload"

        with self.assertLogs(LongPollingTransport.__module__,
                             level="DEBUG") as log:
            with self.assertRaisesRegex(TransportError, error_message):
                await self.transport._send_final_payload(payload,
                                                         headers=headers)

        log_message = "WARNING:{}:{}" \
            .format(LongPollingTransport.__module__, error_message)
        self.assertEqual(log.output, [log_message])
        self.transport._http_semaphore.__aenter__.assert_called()
        self.transport._http_semaphore.__aexit__.assert_called()
        session.post.assert_called_with(self.transport._url,
                                        json=payload,
                                        ssl=self.transport.ssl,
                                        headers=headers,
                                        timeout=self.transport.request_timeout)
        response_mock.json.assert_called_with(loads=self.transport._json_loads)
        self.transport._consume_payload.assert_called_with(
            resp_data,
            headers=response_mock.headers,
            find_response_for=payload[0])
