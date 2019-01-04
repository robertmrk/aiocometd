"""Client for the CometD Chat Example"""
import asyncio
import argparse
from typing import Dict, Any

from aioconsole import ainput  # type: ignore

from aiocometd import Client, ConnectionType
from aiocometd.exceptions import AiocometdException


async def chat_client(url: str, nickname: str,
                      connection_type: ConnectionType) -> None:
    """Runs the chat client until it's canceled

    :param url: CometD server URL
    :param nickname: The user's nickname
    :param connection_type: Connection type
    """
    try:
        room_name = "demo"
        room_channel = "/chat/" + room_name
        members_changed_channel = "/members/" + room_name
        members_channel = "/service/members"

        # start the client with the given connection type
        async with Client(url, connection_type) as client:
            print(f"Connected to '{url}' using connection "
                  f"type '{connection_type.value}'\n")

            # subscribe to the chat room's channel to receive messages
            await client.subscribe(room_channel)

            # subscribe to the members channel to get notifications when the
            # list of the room's members changes
            await client.subscribe(members_changed_channel)

            # publish to the room's channel that the user has joined
            await client.publish(room_channel, {
                "user": nickname,
                "membership": "join",
                "chat": nickname + " has joined"
            })

            # add the user to the room's members
            await client.publish(members_channel, {
                "user": nickname,
                "room": room_channel
            })

            # start the message publisher task
            input_task = asyncio.ensure_future(
                input_publisher(client, nickname, room_channel))

            last_user = None
            try:
                # listen for incoming messages
                async for message in client:
                    # if a chat message is received
                    if message["channel"] == room_channel:
                        data = message["data"]
                        if data["user"] == last_user:
                            user = "..."
                        else:
                            last_user = data["user"]
                            user = data["user"] + ":"
                        # print the incoming message
                        print(f"{user} {data['chat']}")

                    # if the room's members change
                    elif message["channel"] == members_changed_channel:
                        print("MEMBERS:", ", ".join(message["data"]))
                        last_user = None

            finally:
                input_task.cancel()

    except AiocometdException as error:
        print("Encountered an error: " + str(error))
    except asyncio.CancelledError:
        pass
    finally:
        print("\nExiting...")


async def input_publisher(client: Client, nickname: str,
                          room_channel: str) -> None:
    """Read text from stdin and publish it on the *room_channel*

    :param client: A client object
    :param nickname: The user's nickname
    :param room_channel: The chat room's channel
    """
    up_one_line = "\033[F"
    clear_line = "\033[K"

    while True:
        try:
            # read from stdin
            message_text = await ainput("")
        except asyncio.CancelledError:
            return

        # clear the last printed line
        print(up_one_line, end="")
        print(clear_line, end="", flush=True)

        # publish the message on the room's channel
        await client.publish(room_channel, {
            "user": nickname,
            "chat": message_text
        })


def get_arguments() -> Dict[str, Any]:
    """Returns the argument's parsed from the command line"""
    parser = argparse.ArgumentParser(description="CometD chat example client")
    parser.add_argument("url", metavar="server_url", type=str,
                        help="CometD server URL")
    parser.add_argument("nickname", type=str, help="Chat nickname")
    parser.add_argument("-c", "--connection_type", type=ConnectionType,
                        choices=list(ConnectionType),
                        default=ConnectionType.WEBSOCKET.value,
                        help="Connection type")

    return vars(parser.parse_args())


def main() -> None:
    """Starts the chat client application"""
    arguments = get_arguments()

    loop = asyncio.get_event_loop()
    chat_task = asyncio.ensure_future(chat_client(**arguments), loop=loop)
    try:
        loop.run_until_complete(chat_task)
    except KeyboardInterrupt:
        chat_task.cancel()
        loop.run_until_complete(chat_task)


if __name__ == "__main__":
    main()
