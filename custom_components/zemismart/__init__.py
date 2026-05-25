"""Zemismart ZM208 Display Switch integration.

Automatically discovers ZM208 switches already paired via the Matter
integration and adds display-label control (text entities) to them.
Also watches for new Zemismart devices added via Matter at runtime.
"""
from __future__ import annotations

import base64
import logging
import socket

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.discovery_flow import async_create_flow

from .const import CONF_PORT, DOMAIN, PORT
from .coordinator import ZM208Coordinator
from .protocol import ZM208Client

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.TEXT]

_ZEMISMART_MANUFACTURER = "Zemismart Technology Limited"


# ---------------------------------------------------------------------------
# Integration-level setup — runs once, before any config entries
# ---------------------------------------------------------------------------

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Scan for existing Zemismart Matter devices and watch for new ones."""

    @callback
    def _discover_after_start(_event=None) -> None:
        # Run directly in the event loop — hass.data access is not thread-safe
        for info in _scan_matter_devices(hass):
            _LOGGER.debug("Auto-discovered Zemismart ZM208 at %s (MAC %s)", info["host"], info.get("mac"))
            _fire_discovery_flow(hass, info)

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _discover_after_start)

    @callback
    def _on_device_registry_updated(event: dr.EventDeviceRegistryUpdatedData) -> None:
        if event["action"] != "create":
            return
        dev_reg = dr.async_get(hass)
        device = dev_reg.async_get(event["device_id"])
        if device and device.manufacturer == _ZEMISMART_MANUFACTURER:
            info = _device_to_info(hass, device)
            if info:
                _fire_discovery_flow(hass, info)

    hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, _on_device_registry_updated)
    return True


@callback
def _fire_discovery_flow(hass: HomeAssistant, info: dict) -> None:
    from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY
    async_create_flow(
        hass,
        DOMAIN,
        context={"source": SOURCE_INTEGRATION_DISCOVERY},
        data=info,
    )


# ---------------------------------------------------------------------------
# Config-entry setup — runs per configured device
# ---------------------------------------------------------------------------

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = ZM208Client(
        entry.data[CONF_HOST],
        entry.data.get(CONF_PORT, PORT),
    )
    coordinator = ZM208Coordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded


# ---------------------------------------------------------------------------
# Discovery helpers — all run in the event loop (NOT in executor threads)
# ---------------------------------------------------------------------------

def _scan_matter_devices(hass: HomeAssistant) -> list[dict]:
    """Find all Zemismart ZM208 devices via the Matter integration's node cache."""
    results = []
    try:
        from homeassistant.components.matter import DOMAIN as MATTER_DOMAIN  # noqa: PLC0415
    except ImportError:
        _LOGGER.debug("Matter integration not available")
        return results

    for entry in hass.config_entries.async_entries(MATTER_DOMAIN):
        adapter = hass.data.get(MATTER_DOMAIN, {}).get(entry.entry_id)
        if not adapter:
            continue

        try:
            nodes = list(adapter.matter_client.get_nodes())
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not read Matter nodes: %s", err)
            continue

        for node in nodes:
            info = _node_to_info(hass, node)
            if info:
                results.append(info)

    if not results:
        _LOGGER.debug(
            "No Zemismart ZM208 devices found in Matter. "
            "Make sure the ZM208 is paired via Matter and HA has fully started."
        )
    return results


def _node_to_info(hass: HomeAssistant, node) -> dict | None:
    """Extract host/MAC/name from a Matter node if it is a Zemismart ZM208."""
    attrs = getattr(node, "attributes", {})

    vendor_id = attrs.get("0/40/2")       # VendorID (int)
    vendor_name = str(attrs.get("0/40/1", ""))

    if vendor_id != 5020 and _ZEMISMART_MANUFACTURER not in vendor_name:
        return None

    # IPv4 from General Diagnostics (cluster 51, attr 0), field "5" = IPv4 list (base64)
    ip = _extract_ipv4(attrs.get("0/51/0", []))
    if not ip:
        _LOGGER.debug("Zemismart node %s has no IPv4 address yet", getattr(node, "node_id", "?"))
        return None

    mac, name = _mac_and_name_for_node(hass, node)
    product = attrs.get("0/40/3", "ZM208") or "ZM208"

    return {
        "host": ip,
        "mac": mac,
        "name": name or product,
        "node_id": getattr(node, "node_id", None),
    }


def _device_to_info(hass: HomeAssistant, device) -> dict | None:
    """Get discovery info for a newly added device-registry entry."""
    try:
        from homeassistant.components.matter import DOMAIN as MATTER_DOMAIN  # noqa: PLC0415
        for entry in hass.config_entries.async_entries(MATTER_DOMAIN):
            adapter = hass.data.get(MATTER_DOMAIN, {}).get(entry.entry_id)
            if not adapter:
                continue
            # Find the node whose device registry entry matches this device
            for node in adapter.matter_client.get_nodes():
                _, _ = _mac_and_name_for_node(hass, node)  # side-effect: check identifiers
                info = _node_to_info(hass, node)
                if info and info.get("mac"):
                    # Verify this node belongs to the new device
                    dev_reg = dr.async_get(hass)
                    for d in dev_reg.devices.values():
                        if d.id == device.id and any(
                            c[0] == "mac" and c[1].lower() == info["mac"].lower()
                            for c in d.connections
                        ):
                            return info
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Error in _device_to_info: %s", err)
    return None


def _extract_ipv4(iface_list: list) -> str | None:
    for iface in iface_list:
        for b64 in iface.get("5", []):
            try:
                return socket.inet_ntoa(base64.b64decode(b64))
            except Exception:  # noqa: BLE001
                pass
    return None


def _mac_and_name_for_node(hass: HomeAssistant, node) -> tuple[str, str]:
    try:
        from homeassistant.components.matter import DOMAIN as MATTER_DOMAIN  # noqa: PLC0415
        dev_reg = dr.async_get(hass)
        node_id = getattr(node, "node_id", None)
        for device in dev_reg.devices.values():
            if any(
                ident[0] == MATTER_DOMAIN and str(node_id) in str(ident[1])
                for ident in device.identifiers
            ):
                mac = next((c[1] for c in device.connections if c[0] == "mac"), "")
                return mac, device.name or ""
    except Exception:  # noqa: BLE001
        pass
    return "", ""
