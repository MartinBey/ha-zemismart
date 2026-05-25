"""Text entities for Zemismart ZM208 display switch button labels."""
from __future__ import annotations

import logging

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_PORT, DOMAIN, PORT
from .coordinator import ZM208Coordinator
from .protocol import ZM208Client, ZM208State

_LOGGER = logging.getLogger(__name__)

DISPLAY_MAX_CHARS = 10


def _build_device_info(hass: HomeAssistant, entry: ConfigEntry, state: ZM208State) -> DeviceInfo:
    """Compute DeviceInfo once at setup time.

    Creates a Zemismart device per switch (identified by DOMAIN + mac) linked
    to the Matter device via via_device. Using our own identifier per switch
    ensures each switch gets its own device — we cannot reliably use Matter
    identifiers because HA's async_get_or_create matches them to the same device.
    """
    # Find the Matter device to link via via_device
    via: tuple[str, str] | None = None
    device_name: str = state.model_name
    ha_device_id = entry.data.get("ha_device_id")
    if ha_device_id:
        dev_reg = dr.async_get(hass)
        matter_device = dev_reg.async_get(ha_device_id)
        if matter_device:
            device_name = matter_device.name_by_user or matter_device.name or state.model_name
            # Link to Matter device using its first identifier
            for ident in (matter_device.identifiers or []):
                if ident[0] == "matter":
                    via = tuple(ident)
                    break

    return DeviceInfo(
        identifiers={(DOMAIN, state.mac)},   # Unique per switch — never conflicts
        name=f"Zemismart {device_name}",
        manufacturer="Zemismart",
        model=state.model_name,
        sw_version=state.firmware,
        via_device=via,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ZM208Coordinator = hass.data[DOMAIN][entry.entry_id]
    state = coordinator.data
    _LOGGER.warning("ZEMISMART setup_entry host=%s mac=%s", entry.data.get("host"), state.mac)

    # Build DeviceInfo once — device registry is fully loaded at this point
    device_info = _build_device_info(hass, entry, state)

    # Fix any stale entity registry assignments
    _fix_entity_device_assignments(hass, entry, state, device_info)

    entities = [
        ZM208LabelEntity(coordinator, entry, endpoint, device_info)
        for endpoint in state.endpoints
    ]
    async_add_entities(entities)


def _fix_entity_device_assignments(
    hass: HomeAssistant,
    entry: ConfigEntry,
    state: ZM208State,
    device_info: DeviceInfo,
) -> None:
    """Ensure entity registry entries point to the correct device (by DOMAIN+mac)."""
    dev_reg = dr.async_get(hass)
    our_id = (DOMAIN, state.mac)
    target_device = next(
        (d for d in dev_reg.devices.values()
         if any(tuple(i) == our_id for i in (d.identifiers or []))),
        None,
    )
    if not target_device:
        return

    ent_reg = er.async_get(hass)
    for endpoint in state.endpoints:
        unique_id = f"{state.mac}_label_{endpoint}"
        entity_id = ent_reg.async_get_entity_id("text", DOMAIN, unique_id)
        if entity_id:
            entity_entry = ent_reg.async_get(entity_id)
            if entity_entry and entity_entry.device_id != target_device.id:
                ent_reg.async_update_entity(entity_id, device_id=target_device.id)


class ZM208LabelEntity(CoordinatorEntity[ZM208Coordinator], TextEntity):
    """A writable text entity for one button's display label."""

    _attr_mode = TextMode.TEXT
    _attr_native_max = DISPLAY_MAX_CHARS
    _attr_native_min = 0
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ZM208Coordinator,
        entry: ConfigEntry,
        endpoint: int,
        device_info: DeviceInfo,
    ) -> None:
        # Set _attr_device_info FIRST — in HA 2026.x, Entity.__init__() may
        # access cached_property "device_info" which would cache None if we
        # set this after super().__init__().
        self._attr_device_info = device_info
        self._attr_unique_id = f"{coordinator.data.mac}_label_{endpoint}"
        self._attr_name = f"Button {endpoint} label"
        super().__init__(coordinator)
        self._endpoint = endpoint
        self._entry = entry

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
