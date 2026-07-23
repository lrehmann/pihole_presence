# Pi-hole Presence

**Domain:** `pihole_presence`
**IoT Class:** `local_polling`
**Keywords:** Home Assistant, HACS, Pi-hole, Pi-hole v6, presence detection, device tracker, DNS activity, host diagnostics

Pi-hole Presence is a Home Assistant custom integration for HACS that uses Pi-hole DNS activity to track device presence. It matches Pi-hole network rows to Home Assistant devices by MAC address, creates one `device_tracker` per active MAC, and adds Pi-hole host diagnostics for temperature, CPU, and memory on Pi-hole v6.

For existing installs with a large old registry, remove the old diagnostic sensor entities after upgrading. Current releases keep per-device diagnostics on the tracker entity instead of creating separate per-device sensors.

## Features

* **Unified Device Registry**
  Merges Pi-hole network statistics and DHCP data with existing HA devices based on MAC address connections.

* **Presence Tracking**
  Devices are `home` when their latest real-time Pi-hole DNS query is within the configured away threshold, otherwise `not_home`. Pi-hole v6 query activity is joined to the slower network table by IP and MAC so short away thresholds remain accurate.

* **Compact Diagnostics**
  Tracker attributes include last query time, seconds since query, first seen, last seen, query count, IP addresses, DHCP expiry, MAC vendor, and Pi-hole name.

* **Stale Device Filter**
  Ignores Pi-hole network rows whose last DNS query is older than the configured stale-device threshold. The default is 30 days.

* **Authenticated Pi-hole Support**
  Supports Pi-hole v6 session authentication and the legacy pre-v6 API token.

* **Legacy API Fallback**
  Uses the Pi-hole v6 API when available and falls back to the pre-v6 PHP network endpoint for older installs.

* **Pi-hole Host Sensors**
  Adds host temperature, CPU usage, and memory usage from the Pi-hole v6 info API. Temperature is enabled by default. CPU and memory are disabled by default and can be enabled from Home Assistant's entity registry.

* **API Load Protection**
  Polls only the required presence data on each interval, incrementally fetches real-time query activity, refreshes supplemental DHCP and host metrics every five minutes, and backs off repeated connection failures for up to five minutes. This keeps Pi-hole API trouble from creating an aggressive retry loop.

## Logo

The logo combines Home Assistant-style presence, Pi-hole monitoring, and local-network diagnostics. HACS uses `piholepresence.png`; Home Assistant uses the matching component `logo.png`, `icon.png`, and `dark_icon.png` assets.

## Installation

### HACS

1. Add this repository as a custom integration repository.
2. Install **Pi-hole Presence**.
3. Restart Home Assistant.
4. Add **Pi-hole Presence** from Settings > Devices & services.

### Manual

1. Copy `custom_components/pihole_presence` into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Add **Pi-hole Presence** from Settings > Devices & services.

## Configuration

| Option | Description | Default |
| --- | --- | --- |
| **Host/IP** | Pi-hole API base URL, such as `http://pi.hole` or an IP address | `http://pi.hole` |
| **API Mode** | API selection. `Auto detect` tries Pi-hole v6 first, then the pre-v6 PHP API | `Auto detect` |
| **Password** | Optional Pi-hole v6 web password. Used to request a session from `/api/auth` when the v6 API requires authentication | empty |
| **API Token** | Optional pre-v6 Pi-hole API token. Used as `auth` with `/admin/api_db.php?network` | empty |
| **Poll Frequency (s)** | Seconds between API polls | `30` |
| **Consider Away (s)** | Seconds without a DNS query before a device is `not_home` | `900` |
| **Stale Device Days** | Ignore devices with no DNS query within this many days | `30` |

## Entities

| Entity pattern | Name | Default | Description |
| --- | --- | --- | --- |
| `device_tracker.<mac>_pihole` | Pi-hole Presence | enabled | Home if last query is within the away timeout; otherwise away |
| `sensor.pi_hole_temperature` | Pi-hole Temperature | enabled | CPU temperature from `/api/info/sensors` |
| `sensor.pi_hole_cpu_usage` | Pi-hole CPU Usage | disabled | CPU percentage from `/api/info/system` |
| `sensor.pi_hole_memory_usage` | Pi-hole Memory Usage | disabled | RAM percentage from `/api/info/system` |

## Troubleshooting

* **No entities created:** Check the Pi-hole API base URL and network connectivity.
* **Entities suddenly unavailable while DNS still works:** Check whether the Pi-hole web/API server responds. The integration backs off repeated failures automatically, but Pi-hole FTL may need to be restarted if its embedded web server has stopped accepting connections.
* **Unauthorized on Pi-hole v6:** Add the Pi-hole web password in integration options.
* **Older Pi-hole with web password enabled:** Add the pre-v6 API token in integration options, or force API Mode to `Pi-hole pre-v6 PHP API`.
* **Host sensors unavailable:** CPU, memory, and temperature sensors require the Pi-hole v6 info API. Legacy pre-v6 installs continue to provide presence tracking only.
* **Duplicate devices:** Ensure other integrations do not use conflicting MAC connections, then clear stale device registry entries if needed.
* **Presence always away:** Verify the away threshold and that the device is actually making DNS queries through Pi-hole.

## License

MIT
