import re


class AiocometdException(Exception):
    """Base exception type.

    All exceptions of the package inherit from this class.
    """


class TransportError(AiocometdException):
    """Error during the transportation of messages"""


class ServerError(AiocometdException):
    """CometD server side error"""
    def __init__(self, message):
        """If the response *message* contains an error field it gets parsed
        according to the \
        `specs <https://docs.cometd.org/current/reference/#_code_error_code>`_

        :param dict message: Error response message
        """
        self.message = message

    @property
    def error(self):
        """The complete error message"""
        return self.message.get("error")

    @property
    def error_code(self):
        """Error code part of the error message"""
        if self.error is not None:
            match = re.search(r"^\d{3}", self.error)
            if match:
                return int(match[0])
        return None

    @property
    def error_message(self):
        """Description of the error"""
        if self.error is not None:
            message_string = self.error.split(":")[2]
            if message_string:
                return message_string
        return None

    @property
    def error_args(self):
        """Error message arguments"""
        if self.error is not None:
            args_string = self.error.split(":")[1]
            if args_string:
                return args_string.split(",")
        return []


class ClientError(AiocometdException):
    """ComtedD client side error"""
