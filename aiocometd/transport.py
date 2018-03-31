"""Transport classes"""
import asyncio
import logging

import aiohttp

from .exceptions import TransportError, ServerError


logger = logging.getLogger(__name__)


class LongPollingTransport:
    """Long-polling type transport"""
    #: The transport type's identifier
    NAME = "long-polling"
    #: Handshake message template
    _HANDSHAKE_MESSAGE = {
        # mandatory
        "channel": "/meta/handshake",
        "version": "1.0",
        "supportedConnectionTypes": None,
        # optional
        "minimumVersion": "1.0",
        "id": None
    }

    def __init__(self, *, endpoint, incoming_queue, loop=None):
        """
        :param str endpoint: CometD service endpoint
        :param asyncio.Queue incoming_queue: Queue for consuming incoming event
                                             messages
        :param loop: Event :obj:`loop <asyncio.BaseEventLoop>` used to
                     schedule tasks. If *loop* is ``None`` then
                     :func:`asyncio.get_event_loop` is used to get the default
                     event loop.
        """
        self.endpoint = endpoint
        self.incoming_queue = incoming_queue
        self.loop = loop or asyncio.get_event_loop()
        #: clinetId value assigned by the server
        self.client_id = None
        #: message id which should be unique for every message during a client
        #: session
        self._message_id = 0
        #: semaphore to limit the number of concurrent HTTP connections to 2
        self._http_semaphore = asyncio.Semaphore(2, loop=self.loop)
        #: http session
        self._http_session = None
        #: reconnection advice parameters returned by the server
        self._reconnect_advice = None

    async def handshake(self, connection_types):
        """Executes the handshake operation

        :param list[str] connection_types: list of connection types
        :return: Handshake response
        :rtype: dict
        """
        # reset message id for a new client session
        self._message_id = 0

        connection_types = list(connection_types)
        # make sure that the supported connection types list contains this
        # transport
        if self.NAME not in connection_types:
            connection_types.append(self.NAME)

        # send message and await its response
        response_message = \
            await self._send_message(self._HANDSHAKE_MESSAGE.copy(),
                                     supportedConnectionTypes=connection_types)
        # store the returned client id or set it to None if it's not in the
        # response
        self.client_id = response_message.get("clientId")
        return response_message

    async def _get_http_session(self):
        """Factory method for getting the current HTTP session

        :return: The current session if it's not None, otherwise it creates a
                 new session.
        """
        # it would be nicer to create the session when the class gets
        # initialized, but this seems to be the right way to do it since
        # aiohttp produces log messages with warnings that a session should be
        # created in a coroutine
        if self._http_session is None:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    def _finalize_message(self, message):
        """Update the ``id`` and ``clientId`` message fields as a side effect
        if they're are present in the *message*.

        :param dict message: Outgoing message
        """
        if "id" in message:
            message["id"] = str(self._message_id)
            self._message_id += 1

        if "clientId" in message:
            message["clientId"] = self.client_id

    def _finalize_payload(self, payload):
        """Update the ``id`` and ``clientId`` message fields in the *payload*,
        as a side effect if they're are present in the *message*. The *payload*
        can be either a single message or a list of messages.

        :param payload: A message or a list of messages
        :type payload: dict or list[dict]
        """
        if isinstance(payload, list):
            for item in payload:
                self._finalize_message(item)
        else:
            self._finalize_message(payload)

    async def _send_message(self, message, **kwargs):
        """Send message to server

        :param dict message: A finalized or a template message
        :param kwargs: Optional key-value pairs that'll be used to update the \
        the values in the *message*
        :return: Response message
        :rtype: dict
        :raises TransportError: When the HTTP request fails.
        """
        message.update(kwargs)
        response_payload = await self._send_payload(message)
        return await self._consume_payload(response_payload,
                                           confirm_for=message)

    async def _send_payload(self, payload):
        """Send payload to server

        :param payload: A message or a list of messages
        :type payload: dict or list[dict]
        :return: Response payload
        :rtype: list[dict]
        :raises TransportError: When the HTTP request fails.
        """
        self._finalize_payload(payload)

        try:
            session = await self._get_http_session()
            async with self._http_semaphore:
                response = await session.post(self.endpoint, json=payload)
            response_payload = await response.json()
        except aiohttp.client_exceptions.ClientError as error:
            logger.debug("Failed to send payload, {}".format(error))
            raise TransportError(str(error)) from error
        return response_payload

    def _is_confirmation(self, response_message, message):
        """Check whether the *response_message* is a confirmation for the
        given *message*.

        :param dict message: A sent message
        :param response_message: A response message
        :return: True if the *response_message* is a match for *message*
                 otherwise False.
        :rtype: bool
        """
        if message is None or response_message is None:
            return False
        # to consider a response message as a pair of the sent message
        # their channel should match, if they contain an id field it should
        # also match (according to the specs an id is always optional),
        # and the response message should contain the successful field
        return (message["channel"] == response_message["channel"] and
                message.get("id") == response_message.get("id") and
                "successful" in response_message)

    async def _consume_payload(self, payload, *, confirm_for=None,
                               consume_server_errors=False):
        """Enqueu event messages for the consumers and update the internal
        state of the transport, based on response messages in the *payload*.

        :param payload: A list of response messages
        :type payload: list[dict]
        :param dict confirm_for: Return the confirmation response message for \
        the given *confirm_for* message.
        :param bool consume_server_errors: Consume server side error \
        messages which could not or should not be handled by the transport. \
        Let the consumers decide how to deal with them. (these errrors are \
        failed confirmation messages for all channels except \
        ``/meta/connect``, ``/meta/disconnect`` and ``/meta/handshake``). \
        If it's True, then these messages will be enqueued for consumers as \
        :obj:`ServerError` objects.
        :return: The confirmation response message for the *confirm_for*
                 message, otherwise ``None``
        :rtype: dict or None
        """
        # return None if no confirmation message is fourn in the payload
        result = None
        for message in payload:
            # if there is an advice in the message then update the transport's
            # reconnect advice
            if "advice" in message:
                self._reconnect_advice = message["advice"]

            # if enabled, consume server side error messages and enqueue them
            # as ServerErrors
            if (consume_server_errors and
                    message["channel"] != "/meta/connect" and
                    message["channel"] != "/meta/disconnect" and
                    message["channel"] != "/meta/handshake" and
                    not message.get("successful", True)):
                await self.incoming_queue.put(ServerError(message))

            # check if the message is the confirmation response we're looking
            # for, if yes then set it as the result and continue
            if result is None and self._is_confirmation(message, confirm_for):
                result = message
                continue

            # if the message's channel doesn't starts with meta or service, it
            # must be an event message which should be enqueud for the consumer
            if (not message["channel"].startswith("/meta/") and
                    not message["channel"].startswith("/service/") and
                    "data" in message):
                await self.incoming_queue.put(message)
        return result
