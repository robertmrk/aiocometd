"""Long polling transport class definition"""
import asyncio
import logging

import aiohttp

from ..constants import ConnectionType
from .registry import register_transport
from .base import TransportBase
from ..exceptions import TransportError


LOGGER = logging.getLogger(__name__)


@register_transport(ConnectionType.LONG_POLLING)
class LongPollingTransport(TransportBase):
    """Long-polling type transport"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        #: semaphore to limit the number of concurrent HTTP connections to 2
        self._http_semaphore = asyncio.Semaphore(2, loop=self._loop)

    async def _send_final_payload(self, payload, *, headers):
        try:
            session = await self._get_http_session()
            async with self._http_semaphore:
                response = await session.post(self._url, json=payload,
                                              ssl=self.ssl, headers=headers,
                                              timeout=self.request_timeout)
            response_payload = await response.json(loads=self._json_loads)
            headers = response.headers
        except aiohttp.client_exceptions.ClientError as error:
            LOGGER.warning("Failed to send payload, %s", error)
            raise TransportError(str(error)) from error
        return await self._consume_payload(response_payload, headers=headers,
                                           find_response_for=payload[0])
