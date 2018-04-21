from asynctest import TestCase, mock

from aiocometd.transports.registry import create_transport, \
    register_transport, TRANSPORT_CLASSES
from aiocometd.constants import ConnectionType
from aiocometd.exceptions import TransportInvalidOperation


class TestTransportFactoryFunctions(TestCase):
    def tearDown(self):
        TRANSPORT_CLASSES.clear()

    def test_register_transport(self):
        connection_type = ConnectionType.LONG_POLLING

        @register_transport(connection_type)
        class FakeTransport:
            "FakeTransport"

        obj = FakeTransport()

        self.assertEqual(obj.connection_type, connection_type)
        self.assertEqual(TRANSPORT_CLASSES[connection_type], FakeTransport)

    def test_create_transport(self):
        transport = object()
        transport_cls = mock.MagicMock(return_value=transport)
        TRANSPORT_CLASSES[ConnectionType.LONG_POLLING] = transport_cls

        result = create_transport(ConnectionType.LONG_POLLING,
                                  "arg", kwarg="value")

        self.assertEqual(result, transport)
        transport_cls.assert_called_with("arg", kwarg="value")

    def test_create_transport_error(self):
        connection_type = None

        with self.assertRaisesRegex(TransportInvalidOperation,
                                    "There is no transport for connection "
                                    "type {!r}".format(connection_type)):
            create_transport(connection_type)
