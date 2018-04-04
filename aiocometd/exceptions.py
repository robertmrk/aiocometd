import re


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


class ServerError(AiocometdException):
    """CometD server side error"""
    def __init__(self, message, response):
        """If the *response* contains an error field it gets parsed
        according to the \
        `specs <https://docs.cometd.org/current/reference/#_code_error_code>`_

        :param str message: Error description
        :param dict response: Server response message
        """
        super().__init__(message, response)

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
        """Error code part of the :obj:`error` string"""
        # return the error code as an int if 3 digits can be matched at the
        # beginning of the error string, for all other cases (None or invalid
        # error string) return None
        if self.error is not None:
            match = re.search(r"^\d{3}", self.error)
            if match:
                return int(match[0])
        return None

    @property
    def error_message(self):
        """Description part of :obj:`error` string"""
        # if the error string is None, then return None
        if self.error is not None:
            # if the third part of the error string can be matched then
            # return the error message as a string even if it's empty
            # if the third part can't be matched, then it must be and invalid
            # message, return None
            match = re.search(r"(?<=:)[^:]*$", self.error)
            if match:
                return match[0]
        return None

    @property
    def error_args(self):
        """Arguments part of :obj:`error` string"""
        # if the error string is None, then return None
        if self.error is not None:
            # if the second part can't be matched, then it must be and invalid
            # message, return None
            match = re.search(r"(?<=:).*(?=:)", self.error)
            if match:
                # if the second part is not empty, then return the arguments as
                # a list, on empty second part return an empty list (to signal
                # that the args part exists in the error string, but it's
                # empty)
                if match[0]:
                    return match[0].split(",")
                else:
                    return []
        return None


class ClientError(AiocometdException):
    """ComtedD client side error"""
