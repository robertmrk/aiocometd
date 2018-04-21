"""Functions for transport class registration and instantiation"""
from ..exceptions import TransportInvalidOperation


TRANSPORT_CLASSES = {}


def register_transport(conn_type):
    """Class decorator for registering transport classes

    The class' connection_type property will be also defined to return the
    given *connection_type*
    :param ConnectionType conn_type: A connection type
    :return: The updated class
    """
    # pylint: disable=unused-argument, missing-docstring
    def decorator(cls):
        TRANSPORT_CLASSES[conn_type] = cls

        @property
        def connection_type(instance):
            return conn_type

        cls.connection_type = connection_type
        return cls
    return decorator


def create_transport(connection_type, *args, **kwargs):
    """Create a transport object that can be used for the given
    *connection_type*

    :param ConnectionType connection_type: A connection type
    :param args: Positional arguments to pass to the transport
    :param kwargs: Keyword arguments to pass to the transport
    :return: A transport object
    :rtype: Transport
    """
    if connection_type not in TRANSPORT_CLASSES:
        raise TransportInvalidOperation("There is no transport for connection "
                                        "type {!r}".format(connection_type))

    return TRANSPORT_CLASSES[connection_type](*args, **kwargs)
