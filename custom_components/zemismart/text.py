"""Text entities for Zemismart ZM208 display switch button labels."""
from __future__ import annotations

import logging

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_PORT, DOMAIN, PORT
from .coordinator import ZM208Coordinator
from .protocol import ZM208Client

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ZM208Coordinator = hass.data[DOMAIN][entry.entry_id]
    state = coordinator.data

    # Look up the Matter device for THIS specific switch by ha_device_id.
    # Each switch has its own config entry with its own ha_device_id.
    ha_device_id = entry.data.get("ha_device_id")
    matter_device = None
    if ha_device_id:
        matter_device = dr.async_get(hass).async_get(ha_device_id)
        if matter_device:
            _LOGGER.debug(
                "Attaching %s labels to device: %s",
                entry.data.get("host"),
                matter_device.name_by_user or matter_device.name,
            )
        else:
            _LOGGER.warning(
                "Matter device %s not found for switch %s — "
                "entities will have no device association",
                ha_device_id,
                entry.data.get("host"),
            )

    entities = []
    for endpoint in state.endpoints:
        entity = ZM208LabelEntity(coordinator, entry, endpoint)
        # Set device_entry directly before async_add_entities.
        # When entity.device_info is None, HA's entity_platform falls back
        # to entity.device_entry — this is the correct HA pattern for
        # attaching entities to an existing device from another integration.
        if matter_device:
            entity.device_entry = matter_device
        entities.append(entity)

    async_add_entities(entities)


class ZM208LabelEntity(CoordinatorEntity[ZM208Coordinator], TextEntity):
    """A writable text entity representing one button's display label."""

    _attr_mode = TextMode.TEXT
    _attr_native_max = 10
    _attr_native_min = 0
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ZM208Coordinator,
        entry: ConfigEntry,
        endpoint: int,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._endpoint = endpoint
        # unique_id = MAC + endpoint — unique per physical button across all switches
        self._attr_unique_id = f"{coordinator.data.mac}_label_{endpoint}"
        self._attr_name = f"Button {endpoint} label"

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data.labels.get(self._endpoint)

    async def async_set_value(self, value: str) -> None:
        client = ZM208Client(
            self._entry.data[CONF_HOST],
            self._entry.data.get(CONF_PORT, PORT),
        )
        new_state = await self.hass.async_add_executor_job(
            client.set_label, self._endpoint, value
        )
        self.coordinator.async_set_updated_data(new_state)
