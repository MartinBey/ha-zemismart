"""Config flow for Zemismart display switches."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import CONF_PORT, DOMAIN, PORT
from .protocol import ZM208Client

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=PORT): int,
    }
)


class ZemismartConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle config flow for Zemismart display switch."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None
        self._port: int = PORT
        self._discovered_mac: str | None = None

    # ------------------------------------------------------------------
    # Manual setup
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
                mac = state.mac.replace(":", "").lower()
                if not mac:
                    errors["base"] = "unknown"
                else:
                    await self.async_set_unique_id(mac)
                    self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                    return self.async_create_entry(
                        title=f"Zemismart Switch ({host})",
                        data={CONF_HOST: host, CONF_PORT: port},
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Zeroconf (mDNS) auto-discovery
    # Zemismart switches advertise _matterc._udp.local. with VP=5020+...
    # ------------------------------------------------------------------

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle discovery via mDNS _matterc._udp.local."""
        props = discovery_info.properties
        vp = props.get("VP", "")

        # VP field is "VendorID+ProductID" — Zemismart vendor ID is 5020
        if not vp.startswith("5020+"):
            return self.async_abort(reason="not_zemismart")

        host = discovery_info.host
        if not host:
            return self.async_abort(reason="no_host")

        # Probe port 3678 to confirm it's a display switch
        client = ZM208Client(host, PORT)
        try:
            state = await self.hass.async_add_executor_job(client.probe)
        except (TimeoutError, ConnectionError):
            return self.async_abort(reason="cannot_connect")

        mac = state.mac.replace(":", "").lower()
        if not mac:
            return self.async_abort(reason="unknown")

        await self.async_set_unique_id(mac)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self._host = host
        self._discovered_mac = state.mac
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=f"Zemismart Switch ({self._host})",
                data={CONF_HOST: self._host, CONF_PORT: PORT},
            )

        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={
                "host": self._host,
                "mac": self._discovered_mac,
            },
        )
