"""Text entities for Zemismart ZM208 display switch button labels."""
from __future__ import annotations

import logging

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_PORT, DOMAIN, PORT
from .coordinator import ZM208Coordinator
from .protocol import ZM208Client

_LOGGER = logging.getLogger(__name__)

# Physical display character limit on ZM208 series
DISPLAY_MAX_CHARS = 10


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ZM208Coordinator = hass.data[DOMAIN][entry.entry_id]
    state = coordinator.data

    # Create one text entity per button endpoint.
    # Gang count is auto-detected: ZM208-1 has ep[1], ZM208-4 has ep[1,2,3,4].
    entities = [
        ZM208LabelEntity(coordinator, entry, endpoint)
        for endpoint in state.endpoints
    ]
    async_add_entities(entities)


class ZM208LabelEntity(CoordinatorEntity[ZM208Coordinator], TextEntity):
    """A writable text entity representing one button's display label.

    One entity is created per button on the switch:
      - ZM208-1: 1 entity
      - ZM208-2: 2 entities
      - ZM208-3: 3 entities
      - ZM208-4: 4 entities
    The entity name reflects the button number (1-based, matching the physical switch).
    """

    _attr_mode = TextMode.TEXT
    _attr_native_max = DISPLAY_MAX_CHARS
    _attr_native_min = 0
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ZM208Coordinator,
        entry: ConfigEntry,
        endpoint: int,
    ) -> None:
        super().__init__(coordinator)
        self._endpoint = endpoint
        self._entry = entry
        self._attr_unique_id = f"{coordinator.data.mac}_label_{endpoint}"
        self._attr_name = f"Button {endpoint} label"

    @property
    def device_info(self) -> DeviceInfo:
        state = self.coordinator.data
        # Use ONLY connections (MAC) — no identifiers — so HA merges these
        # entities onto the existing Matter device rather than creating a new one.
        return DeviceInfo(
            connections={("mac", state.mac)},
        )

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data.labels.get(self._endpoint)

    async def async_set_value(self, value: str) -> None:
        """Write a new label to this button's display."""
        client = ZM208Client(
            self._entry.data[CONF_HOST],
            self._entry.data.get(CONF_PORT, PORT),
        )
        new_state = await self.hass.async_add_executor_job(
            client.set_label, self._endpoint, value
        )
        # Push the fresh state directly to the coordinator so all entities update
        self.coordinator.async_set_updated_data(new_state)
