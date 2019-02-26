import asyncio

from asynctest import TestCase, mock

from aiocometd.utils import get_error_message, get_error_code, get_error_args,\
    defer, is_auth_error_message, is_event_message, is_server_error_message, \
    is_matching_response
from aiocometd.constants import MetaChannel, SERVICE_CHANNEL_PREFIX


class TestGetErrorCode(TestCase):
    def test_get_error_code(self):
        error_field = "123::"

        result = get_error_code(error_field)

        self.assertEqual(result, 123)

    def test_get_error_code_none_field(self):
        error_field = None

        result = get_error_code(error_field)

        self.assertIsNone(result)

    def test_get_error_code_empty_field(self):
        error_field = ""

        result = get_error_code(error_field)

        self.assertIsNone(result)

    def test_get_error_code_invalid_field(self):
        error_field = "invalid"

        result = get_error_code(error_field)

        self.assertIsNone(result)

    def test_get_error_code_short_invalid_field(self):
        error_field = "12::"

        result = get_error_code(error_field)

        self.assertIsNone(result)

    def test_get_error_code_empty_code_field(self):
        error_field = "::"

        result = get_error_code(error_field)

        self.assertIsNone(result)


class TestGetErrorMessage(TestCase):
    def test_get_error_message(self):
        error_field = "::message"

        result = get_error_message(error_field)

        self.assertEqual(result, "message")

    def test_get_error_message_none_field(self):
        error_field = None

        result = get_error_message(error_field)

        self.assertIsNone(result)

    def test_get_error_message_empty_field(self):
        error_field = ""

        result = get_error_message(error_field)

        self.assertIsNone(result)

    def test_get_error_message_invalid_field(self):
        error_field = "invalid"

        result = get_error_message(error_field)

        self.assertIsNone(result)

    def test_get_error_message_empty_code_field(self):
        error_field = "::"

        result = get_error_message(error_field)

        self.assertEqual(result, "")


class TestGetErrorArgs(TestCase):
    def test_get_error_args(self):
        error_field = "403:xj3sjdsjdsjad,/foo/bar:Subscription denied"

        result = get_error_args(error_field)

        self.assertEqual(result, ["xj3sjdsjdsjad", "/foo/bar"])

    def test_get_error_args_none_field(self):
        error_field = None

        result = get_error_args(error_field)

        self.assertIsNone(result)

    def test_get_error_args_empty_field(self):
        error_field = ""

        result = get_error_args(error_field)

        self.assertIsNone(result)

    def test_get_error_args_invalid_field(self):
        error_field = "invalid"

        result = get_error_args(error_field)

        self.assertIsNone(result)

    def test_get_error_args_empty_code_field(self):
        error_field = "::"

        result = get_error_args(error_field)

        self.assertEqual(result, [])


class TestDefer(TestCase):
    def setUp(self):
        async def coro_func(value):
            return value

        self.coro_func = coro_func

    @mock.patch("aiocometd.utils.asyncio.sleep")
    async def test_defer(self, sleep):
        argument = object()
        delay = 10
        wrapper = defer(self.coro_func, delay, loop=self.loop)

        result = await wrapper(argument)

        self.assertIs(result, argument)
        sleep.assert_called_with(delay, loop=self.loop)

    @mock.patch("aiocometd.utils.asyncio.sleep")
    async def test_defer_no_loop(self, sleep):
        argument = object()
        delay = 10
        wrapper = defer(self.coro_func, delay)

        result = await wrapper(argument)

        self.assertIs(result, argument)
        sleep.assert_called_with(delay, loop=None)

    @mock.patch("aiocometd.utils.asyncio.sleep")
    async def test_defer_none_delay(self, sleep):
        argument = object()
        wrapper = defer(self.coro_func)

        result = await wrapper(argument)

        self.assertIs(result, argument)
        sleep.assert_not_called()

    @mock.patch("aiocometd.utils.asyncio.sleep")
    async def test_defer_zero_delay(self, sleep):
        argument = object()
        delay = 0
        wrapper = defer(self.coro_func, delay)

        result = await wrapper(argument)

        self.assertIs(result, argument)
        sleep.assert_not_called()

    @mock.patch("aiocometd.utils.asyncio.sleep")
    async def test_defer_sleep_canceled(self, sleep):
        argument = object()
        delay = 10
        wrapper = defer(self.coro_func, delay)
        sleep.side_effect = asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            await wrapper(argument)

        sleep.assert_called_with(delay, loop=None)


class TestIsAuthErrorMessage(TestCase):
    @mock.patch("aiocometd.utils.get_error_code")
    def test_is_auth_error_message(self, get_error_code):
        response = {
            "error": "error"
        }
        get_error_code.return_value = 401

        result = is_auth_error_message(response)

        self.assertTrue(result)
        get_error_code.assert_called_with(response["error"])

    @mock.patch("aiocometd.utils.get_error_code")
    def test_is_auth_error_message_forbidden(self, get_error_code):
        response = {
            "error": "error"
        }
        get_error_code.return_value = 403

        result = is_auth_error_message(response)

        self.assertTrue(result)
        get_error_code.assert_called_with(response["error"])

    @mock.patch("aiocometd.utils.get_error_code")
    def test_is_auth_error_message_not_an_auth_error(self, get_error_code):
        response = {
            "error": "error"
        }
        get_error_code.return_value = 400

        result = is_auth_error_message(response)

        self.assertFalse(result)
        get_error_code.assert_called_with(response["error"])

    @mock.patch("aiocometd.utils.get_error_code")
    def test_is_auth_error_message_not_an_error(self, get_error_code):
        response = {}
        get_error_code.return_value = None

        result = is_auth_error_message(response)

        self.assertFalse(result)
        get_error_code.assert_called_with(None)


class TestIsEventMessage(TestCase):
    def assert_event_message_for_channel(self, channel, has_data, has_id,
                                         expected_result):
        message = dict(channel=channel)
        if has_data:
            message["data"] = None
        if has_id:
            message["id"] = None

        result = is_event_message(message)

        self.assertEqual(result, expected_result)

    def test_is_event_message_subscribe(self):
        channel = MetaChannel.SUBSCRIBE
        self.assert_event_message_for_channel(channel, False, False, False)
        self.assert_event_message_for_channel(channel, True, False, False)
        self.assert_event_message_for_channel(channel, False, True, False)
        self.assert_event_message_for_channel(channel, True, True, False)

    def test_is_event_message_unsubscribe(self):
        channel = MetaChannel.UNSUBSCRIBE
        self.assert_event_message_for_channel(channel, False, False, False)
        self.assert_event_message_for_channel(channel, True, False, False)
        self.assert_event_message_for_channel(channel, False, True, False)
        self.assert_event_message_for_channel(channel, True, True, False)

    def test_is_event_message_non_meta_channel(self):
        channel = "/test/channel"
        self.assert_event_message_for_channel(channel, False, False, False)
        self.assert_event_message_for_channel(channel, True, False, True)
        self.assert_event_message_for_channel(channel, False, True, False)
        self.assert_event_message_for_channel(channel, True, True, True)

    def test_is_event_message_service_channel(self):
        channel = SERVICE_CHANNEL_PREFIX + "test"
        self.assert_event_message_for_channel(channel, False, False, False)
        self.assert_event_message_for_channel(channel, True, False, True)
        self.assert_event_message_for_channel(channel, False, True, False)
        self.assert_event_message_for_channel(channel, True, True, False)

    def test_is_event_message_handshake(self):
        channel = MetaChannel.HANDSHAKE
        self.assert_event_message_for_channel(channel, False, False, False)
        self.assert_event_message_for_channel(channel, True, False, False)
        self.assert_event_message_for_channel(channel, False, True, False)
        self.assert_event_message_for_channel(channel, True, True, False)

    def test_is_event_message_connect(self):
        channel = MetaChannel.CONNECT
        self.assert_event_message_for_channel(channel, False, False, False)
        self.assert_event_message_for_channel(channel, True, False, False)
        self.assert_event_message_for_channel(channel, False, True, False)
        self.assert_event_message_for_channel(channel, True, True, False)

    def test_is_event_message_disconnect(self):
        channel = MetaChannel.DISCONNECT
        self.assert_event_message_for_channel(channel, False, False, False)
        self.assert_event_message_for_channel(channel, True, False, False)
        self.assert_event_message_for_channel(channel, False, True, False)
        self.assert_event_message_for_channel(channel, True, True, False)


class TestIsServerErrorMessage(TestCase):
    def test_successful(self):
        message = {
            "successful": True
        }

        self.assertFalse(is_server_error_message(message))

    def test_not_successful(self):
        message = {
            "successful": False
        }

        self.assertTrue(is_server_error_message(message))

    def test_no_success_status(self):
        message = {}

        self.assertFalse(is_server_error_message(message))


class TestIsMatchingResponse(TestCase):
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

        self.assertTrue(is_matching_response(response, message))

    def test_is_matching_response_response_none(self):
        message = {
            "channel": "/test/channel1",
            "data": {},
            "clientId": "clientId",
            "id": "1"
        }
        response = None

        self.assertFalse(is_matching_response(response, message))

    def test_is_matching_response_message_none(self):
        message = None
        response = {
            "channel": "/test/channel1",
            "successful": True,
            "clientId": "clientId",
            "id": "1"
        }

        self.assertFalse(is_matching_response(response, message))

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

        self.assertTrue(is_matching_response(response, message))

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

        self.assertFalse(is_matching_response(response, message))

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

        self.assertFalse(is_matching_response(response, message))

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

        self.assertFalse(is_matching_response(response, message))
