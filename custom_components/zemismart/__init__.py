"""Zemismart ZM208 Display Switch integration.

Automatically discovers ZM208 switches already paired via the Matter
integration and adds display-label control (text entities) to them.
Also watches for new Zemismart devices added via Matter at runtime.
"""
from __future__ import annotations

import base64
import logging
import re
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

# Pattern to extract node_id from Matter deviceid identifier
# Format: deviceid_FABRICID-NODEID16HEX-MatterNodeDevice
_DEVICEID_RE = re.compile(r"deviceid_[0-9A-Fa-f]+-([0-9A-Fa-f]{16})-", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Integration-level setup — runs once, before any config entries
# ---------------------------------------------------------------------------

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Scan for existing Zemismart Matter devices and watch for new ones."""

    @callback
    def _discover_after_start(_event=None) -> None:
        """Scan device registry for Zemismart ZM208s and fire discovery flows."""
        already_configured = {
            entry.data.get("ha_device_id")
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.data.get("ha_device_id")
        }

        for info in _scan_zemismart_devices(hass):
            if info["ha_device_id"] in already_configured:
                _LOGGER.debug(
                    "Zemismart %s already configured, skipping", info["name"]
                )
                continue
            _LOGGER.info(
                "Discovered Zemismart ZM208 at %s (MAC %s) — firing config flow",
                info["host"], info.get("mac"),
            )
            _fire_discovery_flow(hass, info)

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _discover_after_start)

    @callback
    def _on_device_registry_updated(event) -> None:
        """Watch for newly added Zemismart devices and auto-configure them."""
        # HA 2026+: event is an Event object; .data holds the payload
        data = event.data if hasattr(event, "data") else event
        if data.get("action") != "create":
            return
        dev_reg = dr.async_get(hass)
        device = dev_reg.async_get(data.get("device_id"))
        if not device or device.manufacturer != _ZEMISMART_MANUFACTURER:
            return

        info = _device_to_discovery_info(hass, device)
        if not info:
            return

        # Skip if already configured
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.data.get("ha_device_id") == info["ha_device_id"]:
                return

        _LOGGER.info(
            "New Zemismart ZM208 added via Matter: %s — firing config flow",
            info["name"],
        )
        _fire_discovery_flow(hass, info)

    hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, _on_device_registry_updated)
    return True


@callback
def _fire_discovery_flow(hass: HomeAssistant, info: dict) -> None:
    from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY  # noqa: PLC0415
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
# Discovery helpers — run in the event loop (NOT in executor threads)
# ---------------------------------------------------------------------------

def _scan_zemismart_devices(hass: HomeAssistant) -> list[dict]:
    """Find all Zemismart ZM208 devices in the HA device registry.

    Uses the device registry directly (not Matter client internals), so this
    works reliably regardless of how the Matter integration stores its data.
    For each Zemismart Matter device, extracts the node_id from its identifier
    and fetches the IP from the Matter node's cached attributes.
    """
    results = []
    dev_reg = dr.async_get(hass)

    for device in dev_reg.devices.values():
        if device.manufacturer != _ZEMISMART_MANUFACTURER:
            continue
        # Must have a Matter deviceid identifier (not just any Zemismart device)
        node_id = _node_id_from_device(device)
        if node_id is None:
            continue

        info = _device_to_discovery_info(hass, device)
        if info:
            results.append(info)

    if not results:
        _LOGGER.info(
            "No Zemismart ZM208 devices found in HA (manufacturer=%r). "
            "Pair the ZM208 via Matter first, then restart HA.",
            _ZEMISMART_MANUFACTURER,
        )
    else:
        _LOGGER.info("Found %d Zemismart ZM208 device(s): %s",
                     len(results), [r["name"] for r in results])
    return results


def _device_to_discovery_info(hass: HomeAssistant, device) -> dict | None:
    """Build discovery info dict for a Zemismart device from the device registry."""
    node_id = _node_id_from_device(device)
    if node_id is None:
        return None

    ip = _ip_for_node(hass, node_id)
    if not ip:
        _LOGGER.debug(
            "Could not get IP for Zemismart device '%s' (node %s) — "
            "Matter network diagnostics not yet available",
            device.name, node_id,
        )
        return None

    mac = next((c[1] for c in (device.connections or []) if c[0] == "mac"), "")
    name = device.name_by_user or device.name or "ZM208"

    return {
        "host": ip,
        "mac": mac,
        "name": name,
        "node_id": node_id,
        "ha_device_id": device.id,
    }


def _node_id_from_device(device) -> int | None:
    """Extract Matter node_id from a device's identifiers.

    Identifier format: ['matter', 'deviceid_FABRICID-NODEID16HEX-MatterNodeDevice']
    """
    for ident in (device.identifiers or []):
        if ident[0] == "matter" and "deviceid" in ident[1]:
            m = _DEVICEID_RE.search(ident[1])
            if m:
                try:
                    return int(m.group(1), 16)
                except ValueError:
                    pass
    return None


def _ip_for_node(hass: HomeAssistant, node_id: int) -> str | None:
    """Get IPv4 address for a Matter node from the cached node attributes."""
    try:
        from homeassistant.components.matter import DOMAIN as MATTER_DOMAIN  # noqa: PLC0415

        for entry in hass.config_entries.async_entries(MATTER_DOMAIN):
            adapter = hass.data.get(MATTER_DOMAIN, {}).get(entry.entry_id)
            if not adapter:
                continue

            # Try get_node(node_id) first — most direct and efficient
            node = None
            try:
                node = adapter.matter_client.get_node(node_id)
            except Exception:  # noqa: BLE001
                pass

            # Fall back to scanning all nodes
            if node is None:
                try:
                    for n in adapter.matter_client.get_nodes():
                        if getattr(n, "node_id", None) == node_id:
                            node = n
                            break
                except Exception:  # noqa: BLE001
                    pass

            if node:
                ip = _extract_ipv4(getattr(node, "attributes", {}).get("0/51/0", []))
                if ip:
                    _LOGGER.debug("Got IP %s for Matter node %s", ip, node_id)
                    return ip

    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Error getting IP for Matter node %s: %s", node_id, err)
    return None


def _extract_ipv4(iface_list: list) -> str | None:
    for iface in iface_list:
        for b64 in iface.get("5", []):
            try:
                return socket.inet_ntoa(base64.b64decode(b64))
            except Exception:  # noqa: BLE001
                pass
    return None


def _find_matter_ha_device_id_for_node(hass: HomeAssistant, node_id: int | None) -> str | None:
    """Return the HA device registry UUID for a Matter node (used in _node_to_info)."""
    if node_id is None:
        return None
    dev_reg = dr.async_get(hass)
    node_id_hex = format(node_id, "016X")
    for device in dev_reg.devices.values():
        for ident in (device.identifiers or []):
            if ident[0] == "matter" and node_id_hex in ident[1].upper():
                return device.id
    return None
