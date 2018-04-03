from unittest import TestCase

from aiocometd.exceptions import ServerError


class TestServerError(TestCase):
    def test_parse_none_error_message(self):
        message = {
            "channel": "/meta/subscription",
            "successful": False,
            "id": "0"
        }

        error = ServerError(message)

        self.assertEqual(error.message, message)
        self.assertEqual(error.error, None)
        self.assertEqual(error.error_code, None)
        self.assertEqual(error.error_message, None)
        self.assertEqual(error.error_args, None)

    def test_parse_invalid_error_message(self):
        message = {
            "channel": "/meta/subscription",
            "successful": False,
            "id": "0",
            "error": "invalid message"
        }

        error = ServerError(message)

        self.assertEqual(error.message, message)
        self.assertEqual(error.error, message["error"])
        self.assertEqual(error.error_code, None)
        self.assertEqual(error.error_message, None)
        self.assertEqual(error.error_args, None)

    def test_parse_valid_error_message(self):
        message = {
            "channel": "/meta/subscription",
            "successful": False,
            "id": "0",
            "error": "403:xj3sjdsjdsjad,/foo/bar:Subscription denied"
        }

        error = ServerError(message)

        self.assertEqual(error.message, message)
        self.assertEqual(error.error, message["error"])
        self.assertEqual(error.error_code, 403)
        self.assertEqual(error.error_message, "Subscription denied")
        self.assertEqual(error.error_args, ["xj3sjdsjdsjad", "/foo/bar"])

    def test_parse_valid_error_message_empty_parts(self):
        message = {
            "channel": "/meta/subscription",
            "successful": False,
            "id": "0",
            "error": "::"
        }

        error = ServerError(message)

        self.assertEqual(error.message, message)
        self.assertEqual(error.error, message["error"])
        self.assertEqual(error.error_code, None)
        self.assertEqual(error.error_message, "")
        self.assertEqual(error.error_args, [])
