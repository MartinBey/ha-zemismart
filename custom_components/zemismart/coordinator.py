"""DataUpdateCoordinator for Zemismart display switches."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, SCAN_INTERVAL
from .protocol import ZM208Client, ZM208State

_LOGGER = logging.getLogger(__name__)


class ZM208Coordinator(DataUpdateCoordinator[ZM208State]):
    """Polls the switch for current label state every SCAN_INTERVAL seconds."""

    def __init__(self, hass: HomeAssistant, client: ZM208Client) -> None:
        self.client = client
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )

    async def _async_update_data(self) -> ZM208State:
        try:
            return await self.hass.async_add_executor_job(self.client.get_state)
        except (TimeoutError, ConnectionError) as err:
            raise UpdateFailed(f"Cannot reach device: {err}") from err
