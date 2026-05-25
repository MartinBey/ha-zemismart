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

    Looks up the stored Matter device by ha_device_id and uses its own identifiers
    so HA merges our entities onto the existing Matter device page.
    Called from async_setup_entry when the device registry is fully loaded.
    """
    ha_device_id = entry.data.get("ha_device_id")
    _LOGGER.debug("Building device_info: ha_device_id=%s", ha_device_id)

    if ha_device_id:
        dev_reg = dr.async_get(hass)
        device = dev_reg.async_get(ha_device_id)
        _LOGGER.debug("Device lookup result: %s (identifiers=%s)",
                      device.name if device else None,
                      device.identifiers if device else None)
        if device and device.identifiers:
            idents = set(map(tuple, device.identifiers))
            _LOGGER.debug("Using Matter device identifiers: %s", idents)
            return DeviceInfo(identifiers=idents)

    # Fallback: create standalone device (Matter device not found)
    _LOGGER.warning(
        "Could not find Matter device (ha_device_id=%s) — creating standalone device. "
        "Label entities will appear on a separate 'Zemismart %s' device.",
        ha_device_id, state.model_name,
    )
    return DeviceInfo(
        connections={("mac", state.mac)},
        name=f"Zemismart {state.model_name}",
        manufacturer="Zemismart",
        model=state.model_name,
        sw_version=state.firmware,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ZM208Coordinator = hass.data[DOMAIN][entry.entry_id]
    state = coordinator.data

    # Build DeviceInfo once here — device registry is fully loaded at this point
    device_info = _build_device_info(hass, entry, state)
    _LOGGER.debug("device_info for %s: %s", entry.title, device_info)

    # Find the target device for our entities and fix any stale registry assignments.
    # HA doesn't re-assign device_id from device_info when an entity already exists
    # in the entity registry — we must update it explicitly here.
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
    """Ensure entity registry entries point to the correct device.

    HA caches device assignments in the entity registry and doesn't update them
    automatically when device_info changes. This function explicitly updates any
    stale assignments.
    """
    # Find the target device from device_info identifiers
    target_device_id: str | None = None
    idents = device_info.get("identifiers")
    if idents:
        dev_reg = dr.async_get(hass)
        for device in dev_reg.devices.values():
            dev_idents = set(map(tuple, device.identifiers or []))
            if dev_idents & idents:
                target_device_id = device.id
                break

    if not target_device_id:
        return

    ent_reg = er.async_get(hass)
    for endpoint in state.endpoints:
        unique_id = f"{state.mac}_label_{endpoint}"
        entity_id = ent_reg.async_get_entity_id("text", DOMAIN, unique_id)
        if entity_id:
            entity_entry = ent_reg.async_get(entity_id)
            if entity_entry and entity_entry.device_id != target_device_id:
                _LOGGER.debug(
                    "Reassigning %s from device %s to %s",
                    entity_id, entity_entry.device_id, target_device_id,
                )
                ent_reg.async_update_entity(entity_id, device_id=target_device_id)


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
        super().__init__(coordinator)
        self._endpoint = endpoint
        self._entry = entry
        self._attr_unique_id = f"{coordinator.data.mac}_label_{endpoint}"
        self._attr_name = f"Button {endpoint} label"
        # Set once at construction — avoids repeated lookups and ensures
        # the device registry is fully loaded when DeviceInfo is computed
        self._attr_device_info = device_info

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
