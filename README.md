# Zemismart Smart Screen Switch 208

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Control the display labels on Zemismart ZM208 WiFi smart switches directly from Home Assistant — no cloud, no app required.

## Supported Devices

| Model | Buttons | Form Factor |
|-------|---------|-------------|
| ZM208-1 | 1 | Horizontal or Vertical |
| ZM208-2 | 2 | Horizontal or Vertical |
| ZM208-3 | 3 | Horizontal or Vertical |
| ZM208-4 | 4 | Horizontal or Vertical |

All variants share the same local protocol and are auto-detected by gang count.

> **Note**: Switch on/off control uses the built-in **Matter** integration. This integration adds display label control only.

## What It Does

Creates a `text` entity per button. Writing to the entity updates the physical label on the switch display immediately — no cloud involved.

```
text.bedroom_switch_button_1_label  →  "Lights"
text.bedroom_switch_button_2_label  →  "Fan"
text.bedroom_switch_button_3_label  →  "Bed"
text.bedroom_switch_button_4_label  →  "Hallway"
```

Use these in automations to show context-aware labels — time of day, which room a scene applies to, current state, etc.

## Requirements

- ZM208 switch on the **same local network** as Home Assistant
- The switch does **not** need to be paired to the Zemismart app — it only needs an IP address
- Works alongside the Matter integration (recommended: also add via Matter for on/off control)

## Installation

### Via HACS (Recommended)

1. Open HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/martinbeyerlab/ha-zemismart` as type **Integration**
3. Install "Zemismart ZM208 Display Switch"
4. Restart Home Assistant

### Manual

Copy `custom_components/zemismart/` to your HA `custom_components/` directory and restart.

## Setup

1. **Settings → Devices & Services → Add Integration → search "Zemismart ZM208"**
2. Enter the switch's IP address (find it in your router's DHCP table or the Omada controller)
3. The integration auto-detects the gang count (1–4 buttons) and creates the text entities

The integration also auto-discovers ZM208 switches via mDNS when they are on the same network.

## Usage in Automations

```yaml
# Set all labels at once
action:
  - service: text.set_value
    target:
      entity_id: text.bedroom_switch_button_1_label
    data:
      value: "Lights"

# Change labels based on time of day
trigger:
  - platform: time
    at: "18:00:00"
action:
  - service: text.set_value
    target:
      entity_id: text.bedroom_switch_button_1_label
    data:
      value: "Evening"
```

## Technical Details

The ZM208 exposes a local UDP API on **port 3678** using plain JSON — no encryption, no authentication. This was discovered in May 2026 via AP-level packet capture. The protocol is completely local and works without any Zemismart cloud connectivity.

**Protocol (write):**
```json
{
  "payload": {
    "id": "1779664710536",
    "data": {
      "display_panel_text": [
        {"endpoint": 1, "diy_text": "Lights"},
        {"endpoint": 2, "diy_text": "Fan"}
      ]
    }
  },
  "msg_type": "device_status_set"
}
```

Full protocol documentation: [zm208-display-research.md](https://github.com/martinbeyerlab/homelab/blob/main/infrastructure/network/zm208-display-research.md)

## Contributing

Pull requests welcome. If you have a ZM208 variant that doesn't work, open an issue with your device's firmware version and gang count.

## License

MIT
