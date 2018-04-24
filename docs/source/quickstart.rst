Quickstart
==========

.. py:currentmodule:: aiocometd

:py:class:`Client` is the main interface of the library. It can be used to
to connect to CometD_ servers, and to send and receive messages.

Connecting
----------

After creating a :py:class:`Client` object the :py:meth:`~Client.open` method
should be called to establish a connection with the server. The connection is
closed and the session is terminated by calling the :py:meth:`~Client.close`
method.

.. code-block:: python

    client = Client("http://example.com/cometd")
    await client.open()
    # send and receive messsages...
    await client.close()

:py:class:`Client` objects can be also used as asynchronous context managers.

.. code-block:: python

    async with Client("http://example.com/cometd") as client:
        # send and receive messsages...

Channels
--------

A channel is a string that looks like a URL path such as ``/foo/bar``,
``/meta/connect`` or ``/service/chat``.

The Bayeux_ specification defines three types of channels: *meta channels*,
*service channels* and *broadcast channels*.

A channel that starts with ``/meta/`` is a meta channel, a channel that
starts with ``/service/`` is a service channel, and all other channels are
broadcast channels.

Meta channels
~~~~~~~~~~~~~

*Meta channels* provide to applications information about the Bayeux_ protocol,
they are handled by the client internally, the users of the client shouldn't
send or receive messages from these channels.

Service channels
~~~~~~~~~~~~~~~~

Applications create *service channels*, which are used in the case of
request/response style of communication between client and server
(as opposed to the publish/subscribe style of communication of *broadcast
channels*, see below). A server directly responds to messages sent to these
channels, the sent message is not broadcasted to any other client.

Broadcast channels
~~~~~~~~~~~~~~~~~~

Applications also create *broadcast channels*, which have the semantic of a
messaging topic and are used in the case of the publish/subscribe style of
communication, where one sender wants to broadcast information to multiple
clients.


Subscriptions
-------------

In order to receive messages from `broadcast channels <Broadcast channels_>`_
a client must subscribe to these channels first.

.. code-block:: python

    await client.subscribe("/chat/demo")

If you no longer want to receive messages from one of the channels you're
subscribed to then you must unsubscribe from the channel.

.. code-block:: python

    await client.unsubscribe("/chat/demo")

The current set of subscriptions can be obtained from the
:obj:`Client.subscriptions` attribute.

Receiving messages
------------------

To receive messages broadcasted by the server after
`subscribing <Subscriptions_>`_ to these `channels <Broadcast channels_>`_ the
:py:meth:`~Client.receive` method should be used.

.. code-block:: python

    message = await client.receive()

The :py:meth:`~Client.receive` method will wait until a message is received
or it will raise a :py:obj:`~exceptions.TransportTimeoutError` in case the
connection is lost with the server and the client can't re-establish the
connection or a :py:obj:`~exceptions.ServerError` if the connection gets
closed by the server.

The client can also be used as an asynchronous iterator in a for loop to wait
for incoming messages.

.. code-block:: python

    async for message in client:
        # process message

Sending messages
----------------

To send messages to `service <Service channels_>`_ or
`broadcast <Broadcast channels_>`_ channels the :py:meth:`~Client.publish`
method can be used.

.. code-block:: python

    data = {"foo": "bar"}
    response = await client.publish("/foo/bar", data)

.. include:: global.rst
