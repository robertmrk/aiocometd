API Reference
=============

.. py:currentmodule:: aiocometd

Client
------

.. autoclass:: Client

    .. autocomethod:: open
    .. autocomethod:: close
    .. autocomethod:: publish
    .. autocomethod:: subscribe
    .. autocomethod:: unsubscribe
    .. autocomethod:: receive
    .. autoattribute:: closed
    .. autoattribute:: subscriptions
    .. autoattribute:: connection_type
    .. autoattribute:: pending_count
    .. autoattribute:: has_pending_messages

ConnectionType
--------------

.. autoclass:: aiocometd.ConnectionType
    :members:
    :undoc-members:

Extensions
----------

.. autoclass:: aiocometd.Extension
    :members:
    :undoc-members:
    :show-inheritance:


.. autoclass:: aiocometd.AuthExtension
    :members:
    :undoc-members:
    :show-inheritance:


Exceptions
----------

.. automodule:: aiocometd.exceptions
    :members:
    :undoc-members:
