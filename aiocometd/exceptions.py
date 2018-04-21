"""Exception types

Exception hierarchy::

    AiocometdException
        ClientError
            ClientInvalidOperation
        TransportError
            TransportInvalidOperation
            TransportTimeoutError
            TransportConnectionClosed
        ServerError
"""
from . import utils


class AiocometdException(Exception):
    """Base exception type.

    All exceptions of the package inherit from this class.
    """


class TransportError(AiocometdException):
    """Error during the transportation of messages"""


class TransportInvalidOperation(TransportError):
    """The requested operation can't be executed on the current state of the
    transport"""


class TransportTimeoutError(TransportError):
    """Transport timeout"""


class TransportConnectionClosed(TransportError):
    """The connection unexpectedly closed"""


class ServerError(AiocometdException):
    """CometD server side error

    If the *response* contains an error field it gets parsed
    according to the \
    `specs <https://docs.cometd.org/current/reference/#_code_error_code>`_

    :param str message: Error description
    :param dict response: Server response message
    """

    @property
    def message(self):
        """Error description"""
        return self.args[0]

    @property
    def response(self):
        """Server response message"""
        return self.args[1]

    @property
    def error(self):
        """Error field in the :obj:`response`"""
        return self.response.get("error")

    @property
    def error_code(self):
        """Error code part of the error code part of the `error\
        <https://docs.cometd.org/current/reference/#_code_error_code>`_, \
        message field"""
        return utils.get_error_code(self.error)

    @property
    def error_message(self):
        """Description part of the `error\
        <https://docs.cometd.org/current/reference/#_code_error_code>`_, \
        message field"""
        return utils.get_error_message(self.error)

    @property
    def error_args(self):
        """Arguments part of the `error\
        <https://docs.cometd.org/current/reference/#_code_error_code>`_, \
        message field"""
        return utils.get_error_args(self.error)


class ClientError(AiocometdException):
    """ComtedD client side error"""


class ClientInvalidOperation(ClientError):
    """The requested operation can't be executed on the current state of the
    client"""
