import asyncio

from asynctest import TestCase, mock

from aiocometd.utils import get_error_message, get_error_code, get_error_args,\
    defer


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
