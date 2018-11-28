import asyncio

from asynctest import TestCase, TestSuite

from aiocometd import Client, ConnectionType
from aiocometd.exceptions import TransportTimeoutError
from tests.integration.helpers import DockerContainer


class BaseTestCase(TestCase):
    #: name of the docker image containing the CometD demo services
    IMAGE_NAME = "robertmrk/cometd-demos:alpine"
    #: a name for the container
    CONTAINER_NAME = "aiocometd-integration-test"
    #: TCP port exposed by the container
    CONTAINER_PORT = 8080
    #: TCP port where the container's port will be published
    HOST_PORT = 9999
    #: URL of the CometD service
    COMETD_URL = f"http://localhost:{HOST_PORT}/cometd"
    #: CometD connection type
    CONNECTION_TYPE = None

    #: container instance
    container = None

    #: name of the chat room
    CHAT_ROOM = "demo"
    #: channel where the room's messages get published
    CHAT_ROOM_CHANNEL = "/chat/" + CHAT_ROOM
    #: channel where the room's memeber get published
    MEMBERS_CHANGED_CHANNEL = "/members/" + CHAT_ROOM
    #: channel for adding user's to the room
    MEMBERS_CHANNEL = "/service/members"
    #: name of the first user
    USER_NAME1 = "user1"
    #: name of the second user
    USER_NAME2 = "user2"

    def setUp(self):
        self.container.ensure_reachable()

    @classmethod
    def setUpClass(cls):
        cls.container = DockerContainer(cls.IMAGE_NAME,
                                        cls.CONTAINER_NAME,
                                        cls.CONTAINER_PORT,
                                        cls.HOST_PORT)

    @classmethod
    def tearDownClass(cls):
        cls.container.stop()


class TestChat(BaseTestCase):
    async def test_single_client_chat(self):
        # create client
        async with Client(self.COMETD_URL,
                          self.CONNECTION_TYPE) as client:
            # subscribe to channels
            await client.subscribe(self.CHAT_ROOM_CHANNEL)
            await client.subscribe(self.MEMBERS_CHANGED_CHANNEL)

            # send initial message
            join_message = {
                "user": self.USER_NAME1,
                "membership": "join",
                "chat": self.USER_NAME1 + " has joined"
            }
            await client.publish(self.CHAT_ROOM_CHANNEL, join_message)
            # add the user to the room's members
            await client.publish(self.MEMBERS_CHANNEL, {
                "user": self.USER_NAME1,
                "room": self.CHAT_ROOM_CHANNEL
            })

            # verify the reception of the initial and members messages
            message = await client.receive()
            self.assertEqual(message, {
                "data": join_message,
                "channel": self.CHAT_ROOM_CHANNEL
            })
            message = await client.receive()
            self.assertEqual(message, {
                "data": [self.USER_NAME1],
                "channel": self.MEMBERS_CHANGED_CHANNEL
            })

            # send a chat message
            chat_message = {
                "user": self.USER_NAME1,
                "chat": "test_message"
            }
            await client.publish(self.CHAT_ROOM_CHANNEL, chat_message)
            # verify chat message
            message = await client.receive()
            self.assertEqual(message, {
                "data": chat_message,
                "channel": self.CHAT_ROOM_CHANNEL
            })

    async def test_multi_client_chat(self):
        # create two clients
        async with Client(self.COMETD_URL, self.CONNECTION_TYPE) as client1, \
                Client(self.COMETD_URL, self.CONNECTION_TYPE) as client2:
            # subscribe to channels with client1
            await client1.subscribe(self.CHAT_ROOM_CHANNEL)
            await client1.subscribe(self.MEMBERS_CHANGED_CHANNEL)

            # send initial message with client1
            join_message1 = {
                "user": self.USER_NAME1,
                "membership": "join",
                "chat": self.USER_NAME1 + " has joined"
            }
            await client1.publish(self.CHAT_ROOM_CHANNEL, join_message1)
            # add the user1 to the room's members
            await client1.publish(self.MEMBERS_CHANNEL, {
                "user": self.USER_NAME1,
                "room": self.CHAT_ROOM_CHANNEL
            })

            # verify the reception of the initial and members messages
            # for client1
            message = await client1.receive()
            self.assertEqual(message, {
                "data": join_message1,
                "channel": self.CHAT_ROOM_CHANNEL
            })
            message = await client1.receive()
            self.assertEqual(message, {
                "data": [self.USER_NAME1],
                "channel": self.MEMBERS_CHANGED_CHANNEL
            })

            # subscribe to channels with client2
            await client2.subscribe(self.CHAT_ROOM_CHANNEL)
            await client2.subscribe(self.MEMBERS_CHANGED_CHANNEL)

            # send initial message with client2
            join_message2 = {
                "user": self.USER_NAME2,
                "membership": "join",
                "chat": self.USER_NAME2 + " has joined"
            }
            await client2.publish(self.CHAT_ROOM_CHANNEL, join_message2)
            # add the user2 to the room's members
            await client2.publish(self.MEMBERS_CHANNEL, {
                "user": self.USER_NAME2,
                "room": self.CHAT_ROOM_CHANNEL
            })

            # verify the reception of the initial and members messages of
            # client2 for client1
            message = await client1.receive()
            self.assertEqual(message, {
                "data": join_message2,
                "channel": self.CHAT_ROOM_CHANNEL
            })
            message = await client1.receive()
            self.assertEqual(message, {
                "data": [self.USER_NAME1, self.USER_NAME2],
                "channel": self.MEMBERS_CHANGED_CHANNEL
            })

            # verify the reception of the initial and members messages
            # for client2
            message = await client2.receive()
            self.assertEqual(message, {
                "data": join_message2,
                "channel": self.CHAT_ROOM_CHANNEL
            })
            message = await client2.receive()
            self.assertEqual(message, {
                "data": [self.USER_NAME1, self.USER_NAME2],
                "channel": self.MEMBERS_CHANGED_CHANNEL
            })


class TestTimeoutDetection(BaseTestCase):
    async def test_timeout_on_server_termination(self):
        # create client
        async with Client(self.COMETD_URL, self.CONNECTION_TYPE,
                          connection_timeout=1) as client:
            # subscribe to the room's channel
            await client.subscribe(self.CHAT_ROOM_CHANNEL)

            # stop the service
            self.container.stop()
            # give a few seconds for the client to detect the lost connection
            await asyncio.sleep(3)

            with self.assertRaises(TransportTimeoutError):
                await client.receive()

    async def test_timeout_network_outage(self):
        # create client
        async with Client(self.COMETD_URL, self.CONNECTION_TYPE,
                          connection_timeout=1) as client:
            # subscribe to the room's channel
            await client.subscribe(self.CHAT_ROOM_CHANNEL)

            # pause the service
            self.container.pause()
            # wait for the server's connect request timeout to elapse to be
            # able to detect the problem
            await asyncio.sleep(client._transport.request_timeout)
            # give a few seconds for the client to detect the lost connection
            await asyncio.sleep(3)

            with self.assertRaises(TransportTimeoutError):
                await client.receive()


class TestErrorRecovery(BaseTestCase):
    async def test_revover_on_server_restart(self):
        # create client
        async with Client(self.COMETD_URL, self.CONNECTION_TYPE,
                          connection_timeout=3*60) as client:
            # subscribe to the room's channel
            await client.subscribe(self.CHAT_ROOM_CHANNEL)

            # stop the service
            self.container.stop()
            # give a few seconds for the client to detect the lost connection
            await asyncio.sleep(3)

            # start the service
            self.container.ensure_reachable()
            # give a few seconds for the client to recover the connection
            await asyncio.sleep(3)

            # send a chat message
            chat_message = {
                "user": self.USER_NAME1,
                "chat": "test_message"
            }
            await client.publish(self.CHAT_ROOM_CHANNEL, chat_message)
            # verify chat message
            message = await client.receive()
            self.assertEqual(message, {
                "data": chat_message,
                "channel": self.CHAT_ROOM_CHANNEL
            })

    async def test_recover_on_temporary_network_outage(self):
        # create client
        async with Client(self.COMETD_URL, self.CONNECTION_TYPE,
                          connection_timeout=1) as client:
            # subscribe to the room's channel
            await client.subscribe(self.CHAT_ROOM_CHANNEL)

            # pause the service
            self.container.pause()
            # wait for the server's connect request timeout to elapse to be
            # able to detect the problem
            await asyncio.sleep(client._transport.request_timeout)
            # give a few seconds for the client to detect the lost connection
            await asyncio.sleep(3)

            # start the service
            self.container.ensure_reachable()
            # give a few seconds for the client to recover the connection
            await asyncio.sleep(3)

            # send a chat message
            chat_message = {
                "user": self.USER_NAME1,
                "chat": "test_message"
            }
            await client.publish(self.CHAT_ROOM_CHANNEL, chat_message)
            # verify chat message
            message = await client.receive()
            self.assertEqual(message, {
                "data": chat_message,
                "channel": self.CHAT_ROOM_CHANNEL
            })


class TestChatLongPolling(TestChat):
    CONNECTION_TYPE = ConnectionType.LONG_POLLING


class TestChatWebsocket(TestChat):
    CONNECTION_TYPE = ConnectionType.WEBSOCKET


class TestTimeoutDetectionLongPolling(TestTimeoutDetection):
    CONNECTION_TYPE = ConnectionType.LONG_POLLING


class TestTimeoutDetectionWebsocket(TestTimeoutDetection):
    CONNECTION_TYPE = ConnectionType.WEBSOCKET


class TestErrorRecoveryLongPolling(TestErrorRecovery):
    CONNECTION_TYPE = ConnectionType.LONG_POLLING


class TestErrorRecoveryWebsocket(TestErrorRecovery):
    CONNECTION_TYPE = ConnectionType.WEBSOCKET


def load_tests(loader, tests, pattern):
    suite = TestSuite()
    cases = (
        TestChatLongPolling,
        TestChatWebsocket,
        TestTimeoutDetectionLongPolling,
        TestTimeoutDetectionWebsocket,
        TestErrorRecoveryLongPolling,
        TestErrorRecoveryWebsocket
    )
    for case in cases:
        tests = loader.loadTestsFromTestCase(case)
        suite.addTests(tests)
    return suite
