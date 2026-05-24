"""UDP JSON protocol for Zemismart ZM208 display switches (port 3678).

Protocol discovered 2026-05-25 by AP-level packet capture.
Plain JSON over UDP, no encryption or authentication required from the local network.

Supports ZM208 variants:
  - ZM208-1: 1-gang (1 button, 1 display label)
  - ZM208-2: 2-gang (2 buttons, 2 display labels)
  - ZM208-3: 3-gang (3 buttons, 3 display labels)
  - ZM208-4: 4-gang (4 buttons, 4 display labels)
  Horizontal and vertical form factors share the same protocol.
"""
from __future__ import annotations

import json
import logging
import socket
import time
from dataclasses import dataclass, field

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 3678
DEFAULT_TIMEOUT = 3

# Zemismart Matter vendor ID — used for mDNS discovery
ZEMISMART_VENDOR_ID = 5020

# ZM208 product IDs (from mDNS VP= field: "5020+PPPP")
# 4383 confirmed on ZM208-4 (4-gang); others may vary
ZM208_PRODUCT_IDS = {4383, 4928}

MODEL_NAMES = {
    1: "ZM208-1",
    2: "ZM208-2",
    3: "ZM208-3",
    4: "ZM208-4",
}


@dataclass
class ZM208State:
    mac: str = ""
    firmware: str = ""
    labels: dict[int, str] = field(default_factory=dict)
    display_enable: bool = True
    backlight: int = 1
    endpoints: list[int] = field(default_factory=list)

    @property
    def gang_count(self) -> int:
        return len(self.endpoints)

    @property
    def model_name(self) -> str:
        return MODEL_NAMES.get(self.gang_count, f"ZM208-{self.gang_count}")


class ZM208Client:
    """Client for the Zemismart ZM208 display switch local UDP protocol.

    The protocol uses plain JSON datagrams on UDP port 3678.
    No authentication is required — any host on the same LAN can send commands.

    The ZM208 comes in 1-gang through 4-gang variants (both horizontal and vertical).
    The gang count is auto-detected from the device's status reply.
    """

    def __init__(self, host: str, port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_state(self) -> ZM208State:
        """Poll the device for its current state without changing any labels."""
        reply = self._send({"display_panel_text": []})
        return self._parse(reply)

    def set_label(self, endpoint: int, text: str) -> ZM208State:
        """Set the display label for a single button endpoint (1-based)."""
        return self.set_labels({endpoint: text})

    def set_labels(self, labels: dict[int, str]) -> ZM208State:
        """Set display labels for one or more button endpoints.

        Args:
            labels: Mapping of endpoint number → label text.
                    Endpoint numbers are 1-based and match the Matter endpoint IDs.
                    e.g. {1: "Lights", 2: "Fan", 3: "AC", 4: "Blinds"}

        Returns:
            Full device state after the update (confirms what is now on the display).
        """
        reply = self._send({
            "display_panel_text": [
                {"endpoint": ep, "diy_text": text}
                for ep, text in labels.items()
            ]
        })
        return self._parse(reply)

    def probe(self) -> ZM208State:
        """Test connectivity and return device info. Raises on failure."""
        return self.get_state()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _send(self, data: dict) -> dict:
        msg = {
            "payload": {
                "id": str(int(time.time() * 1000)),
                "data": data,
            },
            "msg_type": "device_status_set",
        }
        payload = json.dumps(msg).encode()

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(DEFAULT_TIMEOUT)
        try:
            sock.sendto(payload, (self.host, self.port))
            resp, _ = sock.recvfrom(4096)
            return json.loads(resp)
        except socket.timeout as err:
            raise TimeoutError(
                f"No response from {self.host}:{self.port} — "
                "check the device is on the same local network as Home Assistant"
            ) from err
        except (json.JSONDecodeError, OSError) as err:
            raise ConnectionError(f"Protocol error from {self.host}: {err}") from err
        finally:
            sock.close()

    @staticmethod
    def _parse(data: dict) -> ZM208State:
        payload = data.get("payload", {})
        prop = payload.get("data", {}).get("property", {})

        labels: dict[int, str] = {}
        endpoints: list[int] = []

        for item in prop.get("display_panel_text", []):
            ep = item["endpoint"]
            endpoints.append(ep)
            hex_text = item.get("diy_text", "")
            try:
                labels[ep] = bytes.fromhex(hex_text).decode("utf-8", errors="replace")
            except ValueError:
                # Some firmware versions return plain text instead of hex
                labels[ep] = hex_text

        return ZM208State(
            mac=payload.get("mac", ""),
            firmware=payload.get("softversion", ""),
            labels=labels,
            display_enable=prop.get("display_panel_enable", True),
            backlight=prop.get("backlight", 1),
            endpoints=sorted(endpoints),
        )
