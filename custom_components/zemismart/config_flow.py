"""Config flow for Zemismart ZM208 Display Switch.

Three entry paths:
1. INTEGRATION_DISCOVERY — automatic, triggered when a Zemismart Matter device
   is found. Shows a simple confirm dialog. No user input required.
2. ZEROCONF — triggered by mDNS _matterc._udp.local. advertisement with VP=5020+.
3. USER — manual fallback: enter IP address.

In all paths, we store the HA device registry UUID of the existing Matter device
so DeviceInfo can attach our entities to that device (not create a new one).
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    SOURCE_INTEGRATION_DISCOVERY,
)
from homeassistant.const import CONF_HOST
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import CONF_PORT, DOMAIN, PORT
from .protocol import ZM208Client

_LOGGER = logging.getLogger(__name__)

_ZEMISMART_VENDOR_ID_PREFIX = "5020+"


def _find_matter_ha_device_id(hass, node_id: int | None = None) -> str | None:
    """Return the HA device registry UUID for the Zemismart Matter device.

    When node_id is provided, matches by Matter node_id encoded in identifiers.
    Otherwise falls back to matching by Zemismart manufacturer name.
    """
    dev_reg = dr.async_get(hass)

    # First try: match by Matter node_id (reliable for multi-switch setups)
    if node_id is not None:
        node_id_hex = format(node_id, "016X")
        for device in dev_reg.devices.values():
            for ident in (device.identifiers or []):
                if ident[0] == "matter" and node_id_hex in ident[1].upper():
                    return device.id

    # Fallback: match by Zemismart manufacturer with a Matter deviceid identifier
    for device in dev_reg.devices.values():
        if device.manufacturer == "Zemismart Technology Limited":
            if any(
                i[0] == "matter" and "deviceid" in i[1]
                for i in (device.identifiers or [])
            ):
                return device.id

    return None


class ZemismartConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle config flow for Zemismart ZM208 Display Switch."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None
        self._port: int = PORT
        self._mac: str | None = None
        self._name: str | None = None
        self._ha_device_id: str | None = None
        self._node_id: int | None = None

    # ------------------------------------------------------------------
    # Path 1: Automatic — triggered from __init__.py when a Zemismart
    # Matter device is found in the device registry
    # ------------------------------------------------------------------

    async def async_step_integration_discovery(
        self, discovery_info: dict[str, Any]
    ) -> ConfigFlowResult:
        self._host = discovery_info["host"]
        self._mac = discovery_info.get("mac", "")
        self._name = discovery_info.get("name", "ZM208")
        self._node_id = discovery_info.get("node_id")
        # ha_device_id already looked up in __init__._node_to_info
        self._ha_device_id = discovery_info.get("ha_device_id")

        unique_id = self._mac.replace(":", "").lower() if self._mac else self._host
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        client = ZM208Client(self._host, self._port)
        try:
            state = await self.hass.async_add_executor_job(client.probe)
            if state.mac:
                self._mac = state.mac
                await self.async_set_unique_id(state.mac.replace(":", "").lower())
                self._abort_if_unique_id_configured()
        except (TimeoutError, ConnectionError):
            return self.async_abort(reason="cannot_connect")

        if not self._ha_device_id:
            self._ha_device_id = _find_matter_ha_device_id(self.hass, self._node_id)

        # Auto-create without asking — device is already trusted via Matter pairing
        return self.async_create_entry(
            title=f"{self._name} — Display Labels",
            data={
                CONF_HOST: self._host,
                CONF_PORT: self._port,
                "mac": self._mac,
                "ha_device_id": self._ha_device_id,
            },
        )

    # ------------------------------------------------------------------
    # Path 2: mDNS zeroconf — _matterc._udp.local. with VP=5020+
    # ------------------------------------------------------------------

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        props = discovery_info.properties
        vp = props.get("VP", "")
        if not str(vp).startswith(_ZEMISMART_VENDOR_ID_PREFIX):
            return self.async_abort(reason="not_zemismart")

        host = discovery_info.host
        if not host:
            return self.async_abort(reason="no_host")

        client = ZM208Client(host, PORT)
        try:
            state = await self.hass.async_add_executor_job(client.probe)
        except (TimeoutError, ConnectionError):
            return self.async_abort(reason="cannot_connect")

        mac = state.mac.replace(":", "").lower() if state.mac else ""
        if not mac:
            return self.async_abort(reason="unknown")

        await self.async_set_unique_id(mac)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self._host = host
        self._mac = state.mac
        self._name = state.model_name
        self._ha_device_id = _find_matter_ha_device_id(self.hass)
        self.context["title_placeholders"] = {"name": self._name, "host": host}
        return await self.async_step_confirm()

    # ------------------------------------------------------------------
    # Shared confirm step
    # ------------------------------------------------------------------

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=f"{self._name} — Display Labels",
                data={
                    CONF_HOST: self._host,
                    CONF_PORT: self._port,
                    "mac": self._mac,
                    "ha_device_id": self._ha_device_id,
                },
            )

        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "name": self._name or "ZM208",
                "host": self._host or "unknown",
                "mac": self._mac or "unknown",
            },
        )

    # ------------------------------------------------------------------
    # Path 3: Manual fallback
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input.get(CONF_PORT, PORT)
            client = ZM208Client(host, port)

            try:
                state = await self.hass.async_add_executor_job(client.probe)
            except TimeoutError:
                errors["base"] = "cannot_connect"
            except ConnectionError:
                errors["base"] = "unknown"
            else:
                mac = state.mac.replace(":", "").lower() if state.mac else ""
                if not mac:
                    errors["base"] = "unknown"
                else:
                    await self.async_set_unique_id(mac)
                    self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                    ha_device_id = _find_matter_ha_device_id(self.hass)
                    return self.async_create_entry(
                        title=f"{state.model_name} — Display Labels",
                        data={
                            CONF_HOST: host,
                            CONF_PORT: port,
                            "mac": state.mac,
                            "ha_device_id": ha_device_id,
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_PORT, default=PORT): int,
            }),
            errors=errors,
        )
