"""Long polling transport class definition"""
import logging

import aiohttp

from .constants import ConnectionType
from .registry import register_transport
from .base import TransportBase
from ..exceptions import TransportError


LOGGER = logging.getLogger(__name__)


@register_transport(ConnectionType.LONG_POLLING)
class LongPollingTransport(TransportBase):
    """Long-polling type transport"""

    async def _send_final_payload(self, payload, *, headers):
        try:
            session = await self._get_http_session()
            async with self._http_semaphore:
                response = await session.post(self._endpoint, json=payload,
                                              ssl=self.ssl, headers=headers)
            response_payload = await response.json()
            headers = response.headers
        except aiohttp.client_exceptions.ClientError as error:
            LOGGER.warning("Failed to send payload, %s", error)
            raise TransportError(str(error)) from error
        return await self._consume_payload(response_payload, headers=headers,
                                           find_response_for=payload[0])
