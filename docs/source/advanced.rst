Advanced Usage
==============

.. py:currentmodule:: aiocometd

Connection types
----------------

The Bayeux_ protocol used by CometD_ is a transport-independent protocol,  that
can be carried over HTTP or over WebSocket (or other transport protocols),
so that an application is not bound to a specific transport technology.

aiocometd supports the :py:obj:`~ConnectionType.LONG_POLLING` and
:py:obj:`~ConnectionType.WEBSOCKET` transports.

When a client connects to a CometD_ server, a so called handshake operation is
executed first using the default transport that all CometD_ servers should
support. Based on the types of transports that the server offers and what
the client supports, the client picks one of the transports that it will use
to communicate with the server.

By default, if the preferred connection types are not specified when the
:py:obj:`Client` is created, it will use the
:py:obj:`~ConnectionType.WEBSOCKET` transport if it's supported by the server
or otherwise fall back to using :py:obj:`~ConnectionType.LONG_POLLING`.

If you prefer a different ordering then it can be specified when the
:py:obj:`Client` is created:

.. code-block:: python

    client = Client("http://example.com/cometd",
                    connection_types=[ConnectionType.LONG_POLLING,
                                      ConnectionType.WEBSOCKET])

If there is only a single connection type that you would wan't your client to
accept or fail if it's not available on the server, then instead of a list
specify a single connection type:

.. code-block:: python

    client = Client("http://example.com/cometd",
                    connection_types=ConnectionType.WEBSOCKET)

Extensions
----------

Extensions allow the modification of a message just after receiving it but
before the rest of the message processing takes place, or just before sending
it. An extension normally adds fields to the message being sent or received in
the ext_ object that the Bayeux_ protocol specification defines.
An extension is not a way to add business fields to a message, but rather a
way to process all messages, including the meta messages the Bayeux_ protocol
uses, and to extend the Bayeux_ protocol itself.

aiocometd provides abstract base classes for implementing custom extensions
using the :py:obj:`Extension` and :py:obj:`AuthExtension` classes.

Extension
~~~~~~~~~

To create a new extension use the :py:obj:`Extension` class as the base class:

.. code-block:: python

    class MyExtension(Extension):
        async def incoming(payload, headers=None):
            pass

        async def outgoing(payload, headers):
            pass

The incoming message payload, which is a list of messages, is first passed to
the :py:meth:`~Extension.incoming` method along with the received headers.
The incoming headers might or might not be empty, it depends on the type of
transport used, whether it receives headers for responses.

The outgoing payload along with the headers are passed to the
:py:meth:`~Extension.outgoing` method before sending.

Custom extension implementation can use these two methods to inspect or alter
the messages or headers. The list of extension objects that you would want to
use should be passed to the :py:obj:`Client`.

.. code-block:: python

    client = Client("http://example.com/cometd",
                    extensions=[MyExtension()])

AuthExtension
~~~~~~~~~~~~~

The :py:obj:`AuthExtension` class, which is based on :py:obj:`Extension`, can
be used to implement authentication extensions.

For authentication schemes where the credentials are static it doesn't
makes much sense to use :py:obj:`AuthExtension` instead of :py:obj:`Extension`.
However for schemes where the credentials can expire (like OAuth, JWT...)
:py:meth:`~AuthExtension.authenticate` method can be reimplemented to update
those credentials. The :py:meth:`~AuthExtension.authenticate` method is called
by the client after an authentication failure.

.. code-block:: python

    class MyAuthExtension(AuthExtension):
        async def incoming(payload, headers=None):
            pass

        async def outgoing(payload, headers):
            pass

        async def authenticate():
            # get new JWT

An auth extension should be passed to the client separately from the other
extensions.

.. code-block:: python

    client = Client("http://example.com/cometd",
                    extensions=[MyExtension()]
                    auth=MyAuthExtension())

Network failures
----------------

When a :py:obj:`Client` object is opened, it will try to maintain a continuous
connection in the background with the server. If any network failures happen
while waiting to :py:meth:`~Client.receive` messages, the client will reconnect
to the server transparently, it will resubscribe to the subscribed channels,
and continue to wait for incoming messages.

To avoid waiting for a server which went offline permanently, a
``connection_timeout`` can be passed to the :py:obj:`Client`, to limit how
many seconds the client object should wait before raising a
:py:obj:`~exceptions.TransportTimeoutError` if it can't reconnect to the
server.

.. code-block:: python

    client = Client("http://example.com/cometd",
                    connection_timeout=60)

    try:
        message = await client.receive()
    except TransportTimeoutError:
        print("Connection is lost with the server. "
              "Couldn't reconnect in 60 seconds.")

The defaul value is ``10`` seconds. If you pass ``None`` as the
``connection_timeout`` value, then the client will keep on trying indefinitely.

Prefetch and backpressure
-------------------------

When a :py:obj:`Client` is opened it will start and maintain a connection in
the background with the server. It will start to fetch messages from the
server as soon as it's connected, even before :py:meth:`~Client.receive` is
called.

Firstly, prefetching messages has the advantage, that incoming messages will
wait in a buffer for users to consume them when :py:meth:`~Client.receive`
is called, without any delay. Secondly, the client has no choice but to accept
incoming messages.

The Bayeux_ protocol is modelled very heavily around long-polling type HTTP
transports. Which requires from clients to send periodic requests to the server
to simulate a continuous connection, otherwise the server will terminate the
session. This makes it impossible to use backpressure, even with the type of
transports like WebSocket which would otherwise support it. So the connection
can not be suspended if the client can't keep up with receiving the incoming
messages, or otherwise the session will be closed.

To avoid consuming all the available memory by the incoming messages, which are
not consumed yet, the number of prefetched messages can be limited with the
``max_pending_count`` parameter of the :py:obj:`Client`. The default value is
``100``.

.. code-block:: python

    client = Client("http://example.com/cometd",
                    max_pending_count=42)

The current number of messages waiting to be consumed can be obtained from the
:py:obj:`Client.pending_count` attribute.

JSON encoder/decoder
--------------------

Besides the standard :obj:`json` module, many third party libraries offer
JSON serialization/deserilization functionality. To use a different library for
handling JSON data types, you can specify the callable to use for serialization
with the ``json_dumps`` and the callable for deserialization with the
``json_loads`` parameters of the :py:obj:`Client`.

.. code-block:: python

    import ujson

    client = Client("http://example.com/cometd",
                    json_dumps=ujson.dumps,
                    json_loads=ujson.loads)

.. include:: global.rst
