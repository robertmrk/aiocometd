from unittest import TestCase

from aiocometd.exceptions import ServerError


class TestServerError(TestCase):
    def test_parse_error_message(self):
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

    def test_parse_error_message_without_args(self):
        message = {
            "channel": "/meta/subscription",
            "successful": False,
            "id": "0",
            "error": "401::No client ID"
        }

        error = ServerError(message)

        self.assertEqual(error.message, message)
        self.assertEqual(error.error, message["error"])
        self.assertEqual(error.error_code, 401)
        self.assertEqual(error.error_message, "No client ID")
        self.assertEqual(error.error_args, [])

    def test_parse_error_message_empty_parts(self):
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
        self.assertEqual(error.error_message, None)
        self.assertEqual(error.error_args, [])
