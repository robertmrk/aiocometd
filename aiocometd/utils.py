"""Utility functions"""
import re
import asyncio
from functools import wraps


def get_error_code(error_field):
    """Get the error code part of the `error\
    <https://docs.cometd.org/current/reference/#_code_error_code>`_, message \
    field

    :param error_field: `Error\
    <https://docs.cometd.org/current/reference/#_code_error_code>`_, message \
    field
    :type error_field: str or None
    :return: The error code as an int if 3 digits can be matched at the \
    beginning of the error field, for all other cases (``None`` or invalid \
    error field) return ``None``
    :rtype: int or None
    """
    result = None
    if error_field is not None:
        match = re.search(r"^\d{3}", error_field)
        if match:
            result = int(match[0])
    return result


def get_error_message(error_field):
    """Get the description part of the `error\
    <https://docs.cometd.org/current/reference/#_code_error_code>`_, message \
    field

    :param error_field: `Error\
    <https://docs.cometd.org/current/reference/#_code_error_code>`_, message \
    field
    :type error_field: str or None
    :return: The third part of the error field as a string if it can be \
    matched otherwise return ``None``
    :rtype: str or None
    """
    result = None
    if error_field is not None:
        match = re.search(r"(?<=:)[^:]*$", error_field)
        if match:
            result = match[0]
    return result


def get_error_args(error_field):
    """Get the arguments part of the `error\
    <https://docs.cometd.org/current/reference/#_code_error_code>`_, message \
    field

    :param error_field: `Error\
    <https://docs.cometd.org/current/reference/#_code_error_code>`_, message \
    field
    :type error_field: str or None
    :return: The second part of the error field as a list of strings if it \
    can be matched otherwise return ``None``
    :rtype: list[str] or None
    """
    result = None
    if error_field is not None:
        match = re.search(r"(?<=:).*(?=:)", error_field)
        if match:
            if match[0]:
                result = match[0].split(",")
            else:
                result = []
    return result


def defer(coro_func, delay=None, *, loop=None):
    """Returns a coroutine function that will defer the call to the given
    *coro_func* by *delay* seconds

    :param asyncio.coroutine coro_func: A coroutine function
    :param delay: Delay in seconds
    :type delay: int, float or None
    :param loop: An event loop
    :type loop: asyncio.BaseEventLoop or None
    :return: Coroutine function wrapper
    """
    @wraps(coro_func)
    async def wrapper(*args, **kwargs):  # pylint: disable=missing-docstring
        if delay:
            await asyncio.sleep(delay, loop=loop)
        return await coro_func(*args, **kwargs)

    return wrapper
