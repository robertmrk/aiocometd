from unittest import TestCase

from aiocometd.exceptions import ServerError


class TestServerError(TestCase):
    def test_parse_none_error_message(self):
        response = {
            "channel": "/meta/subscription",
            "successful": False,
            "id": "0"
        }

        error = ServerError("description message", response)

        self.assertEqual(error.message, "description message")
        self.assertEqual(error.response, response)
        self.assertEqual(error.error, None)
        self.assertEqual(error.error_code, None)
        self.assertEqual(error.error_message, None)
        self.assertEqual(error.error_args, None)

    def test_parse_invalid_error_message(self):
        response = {
            "channel": "/meta/subscription",
            "successful": False,
            "id": "0",
            "error": "invalid response"
        }

        error = ServerError("description message", response)

        self.assertEqual(error.message, "description message")
        self.assertEqual(error.response, response)
        self.assertEqual(error.error, response["error"])
        self.assertEqual(error.error_code, None)
        self.assertEqual(error.error_message, None)
        self.assertEqual(error.error_args, None)

    def test_parse_valid_error_message(self):
        response = {
            "channel": "/meta/subscription",
            "successful": False,
            "id": "0",
            "error": "403:xj3sjdsjdsjad,/foo/bar:Subscription denied"
        }

        error = ServerError("description message", response)

        self.assertEqual(error.message, "description message")
        self.assertEqual(error.response, response)
        self.assertEqual(error.error, response["error"])
        self.assertEqual(error.error_code, 403)
        self.assertEqual(error.error_message, "Subscription denied")
        self.assertEqual(error.error_args, ["xj3sjdsjdsjad", "/foo/bar"])

    def test_parse_valid_error_message_empty_parts(self):
        response = {
            "channel": "/meta/subscription",
            "successful": False,
            "id": "0",
            "error": "::"
        }

        error = ServerError("description message", response)

        self.assertEqual(error.message, "description message")
        self.assertEqual(error.response, response)
        self.assertEqual(error.error, response["error"])
        self.assertEqual(error.error_code, None)
        self.assertEqual(error.error_message, "")
        self.assertEqual(error.error_args, [])
