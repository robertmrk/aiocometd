from unittest import TestCase, mock

from aiocometd.exceptions import ServerError


class TestServerError(TestCase):
    def test_properties(self):
        response = {
            "channel": "/meta/subscription",
            "successful": False,
            "id": "0",
            "error": "error"
        }

        error = ServerError("description message", response)

        self.assertEqual(error.message, "description message")
        self.assertEqual(error.response, response)
        self.assertEqual(error.error, "error")

    def test_properties_on_no_error(self):
        response = {
            "channel": "/meta/subscription",
            "successful": False,
            "id": "0"
        }

        error = ServerError("description message", response)

        self.assertEqual(error.message, "description message")
        self.assertEqual(error.response, response)
        self.assertIsNone(error.error)

    def test_properties_on_no_response(self):
        response = None

        error = ServerError("description message", response)

        self.assertEqual(error.message, "description message")
        self.assertIsNone(error.response)
        self.assertIsNone(error.error)

    @mock.patch("aiocometd.exceptions.utils")
    def test_error_code(self, utils):
        response = {
            "channel": "/meta/subscription",
            "successful": False,
            "id": "0",
            "error": "error"
        }
        utils.get_error_code.return_value = 12

        error = ServerError("description message", response)
        result = error.error_code

        self.assertEqual(result, utils.get_error_code.return_value)
        utils.get_error_code.assert_called_with(response["error"])

    @mock.patch("aiocometd.exceptions.utils")
    def test_error_message(self, utils):
        response = {
            "channel": "/meta/subscription",
            "successful": False,
            "id": "0",
            "error": "error"
        }
        utils.get_error_message.return_value = "message"

        error = ServerError("description message", response)
        result = error.error_message

        self.assertEqual(result, utils.get_error_message.return_value)
        utils.get_error_message.assert_called_with(response["error"])

    @mock.patch("aiocometd.exceptions.utils")
    def test_error_args(self, utils):
        response = {
            "channel": "/meta/subscription",
            "successful": False,
            "id": "0",
            "error": "error"
        }
        utils.get_error_args.return_value = ["arg"]

        error = ServerError("description message", response)
        result = error.error_args

        self.assertEqual(result, utils.get_error_args.return_value)
        utils.get_error_args.assert_called_with(response["error"])
