# Pi-hole Presence

**Domain:** `pihole_presence`
**IoT Class:** `local_polling`

A Home Assistant custom integration that uses Pi-hole's network status endpoint to monitor device presence. It unifies Pi-hole data with existing HA devices by matching on MAC address.

For existing installs with a large old registry, remove the old diagnostic sensor entities after upgrading. Current releases only create one `device_tracker` per active MAC address.

## Features

* **Unified Device Registry**
  Merges Pi-hole network statistics and DHCP data with existing HA devices based on MAC address connections.

* **Presence Tracking**
  Implements a `device_tracker` named `Pi-hole Presence` with a `_pihole` suffix. Devices are `home` when their last Pi-hole DNS query is within the configured away threshold, otherwise `not_home`.

* **Tracker Attributes**
  Adds useful details to each tracker as attributes: last query time, seconds since last query, first seen, last seen, query count, IP addresses, DHCP expiry, MAC vendor, and Pi-hole device name.

* **Stale Device Filter**
  Ignores Pi-hole network rows whose last DNS query is older than the configured stale-device threshold. The default is 30 days.

* **Efficient Polling**
  Fetches only two endpoints: `/api/dhcp/leases` and `/api/network/devices`.

## Installation

### HACS

1. Ensure HACS is installed.
2. In Home Assistant, navigate to HACS -> Custom repositories.
3. Add repository `https://github.com/lrehmann/pihole_presence` as an integration.
4. Restart Home Assistant.

### Manual

1. Clone or download this repo.
2. Copy `custom_components/pihole_presence/` into `<config>/custom_components/`.
3. Restart Home Assistant.

## Configuration

After restart, go to **Settings -> Devices & Services -> Add Integration** and search **Pi-hole Presence**.

| Option | Description | Default |
| --- | --- | --- |
| **Host/IP** | Pi-hole API base URL, such as `http://pi.hole` or an IP address | `http://pi.hole` |
| **Poll Frequency (s)** | Seconds between API polls | `30` |
| **Consider Away (s)** | Seconds without a DNS query before a device is `not_home` | `900` |
| **Stale Device Days** | Ignore devices with no DNS query within this many days | `30` |

## Entities

| Entity ID Pattern | Friendly Name | Description |
| --- | --- | --- |
| `device_tracker.<mac>_pihole` | Pi-hole Presence | Home if last query <= away timeout; otherwise away. |

Each tracker includes attributes for diagnostics instead of creating separate per-device sensor entities.

## Troubleshooting

* **No entities created:** Check the Pi-hole API base URL and network connectivity.
* **Duplicate devices:** Ensure other integrations do not use conflicting MAC connections, then clear stale device registry entries if needed.
* **Presence always away:** Verify the away threshold and that the device is actually making DNS queries through Pi-hole.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
