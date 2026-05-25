"""Text entities for Zemismart ZM208 display switch button labels."""
from __future__ import annotations

import logging

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_PORT, DOMAIN, PORT
from .coordinator import ZM208Coordinator
from .protocol import ZM208Client

_LOGGER = logging.getLogger(__name__)

DISPLAY_MAX_CHARS = 10


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ZM208Coordinator = hass.data[DOMAIN][entry.entry_id]
    state = coordinator.data
    entities = [
        ZM208LabelEntity(coordinator, entry, endpoint)
        for endpoint in state.endpoints
    ]
    async_add_entities(entities)


class ZM208LabelEntity(CoordinatorEntity[ZM208Coordinator], TextEntity):
    """A writable text entity for one button's display label.

    Attaches to the existing Matter device by using its own identifiers,
    so the label fields appear on the same HA device card as the switches.
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
        """Return device info that attaches these entities to the Matter device.

        We look up the stored ha_device_id (the HA device registry UUID of the
        existing Matter device) and return its own identifiers. HA uses the
        identifiers to find the existing device and adds our entities to it,
        so the label fields appear on the same device card as the Matter switches.
        """
        ha_device_id = self._entry.data.get("ha_device_id")
        if ha_device_id:
            dev_reg = dr.async_get(self.hass)
            device = dev_reg.async_get(ha_device_id)
            if device and device.identifiers:
                return DeviceInfo(identifiers=set(map(tuple, device.identifiers)))

        # Fallback: standalone device (used when Matter device not found)
        state = self.coordinator.data
        return DeviceInfo(
            connections={("mac", state.mac)},
            name=f"Zemismart {state.model_name}",
            manufacturer="Zemismart",
            model=state.model_name,
            sw_version=state.firmware,
        )

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
