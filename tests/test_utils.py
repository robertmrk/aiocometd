from unittest import TestCase

from aiocometd.utils import get_error_message, get_error_code, get_error_args


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
