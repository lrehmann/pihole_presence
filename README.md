# Pi-hole Presence

[![Validate](https://github.com/lrehmann/pihole_presence/actions/workflows/validate.yml/badge.svg)](https://github.com/lrehmann/pihole_presence/actions/workflows/validate.yml)

**Domain:** `pihole_presence`
**IoT Class:** `local_polling`
**Keywords:** Home Assistant, HACS, Pi-hole, Pi-hole v6, presence detection, device tracker, DNS activity, host diagnostics

Pi-hole Presence is a Home Assistant custom integration for HACS that uses Pi-hole DNS activity to track device presence. It matches Pi-hole network rows to Home Assistant devices by MAC address, creates one `device_tracker` per active MAC, and adds Pi-hole host diagnostics for temperature, CPU, and memory on Pi-hole v6.

For existing installs with a large old registry, remove the old diagnostic sensor entities after upgrading. Current releases keep per-device diagnostics on the tracker entity instead of creating separate per-device sensors.

## Compatibility

Supports Home Assistant **2023.1.7 and newer**, Pi-hole **v5's PHP network API**, and Pi-hole **v6's REST API**. Pi-hole v6 can run with no password, a web password, or an application password. Use an application password if two-factor authentication is enabled. Pi-hole v5 uses its API token.

The regression suite runs against real Home Assistant classes from **2023.1.7, 2024.11.3, 2025.12.5, and 2026.10.4**, with isolated HTTP tests for legacy, unauthenticated v6, and authenticated v6 servers. These checks cover the API contracts used by the integration; they do not imply every Pi-hole firmware and Home Assistant patch has been tested on hardware.

## What's new in 0.7.0

* Fixes the Configure HTTP 500 on newer Home Assistant and sensor import errors on older Home Assistant.
* Validates connection settings, normalizes host/IP/admin URLs, and applies saved options through an automatic integration reload.
* Reuses Pi-hole API sessions, refreshes rejected sessions once, and logs out on unload, failed setup, and Home Assistant shutdown.
* Reports authentication failures through Home Assistant's reauthentication flow and gives useful errors for web/API timeouts.
* Limits optional query requests, respects rate limits, closes HTTP connections explicitly, and keeps missing diagnostics from disabling presence tracking.
* Adds privacy-preserving downloadable diagnostics and compatibility regression tests. Existing tracker and sensor unique IDs stay unchanged.

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
  Incrementally fetches real-time query activity, refreshes supplemental DHCP and host metrics every five minutes, and backs off repeated connection failures for up to five minutes. HTTP `Retry-After` can extend that wait. Each HTTP connection is closed after use while the API authentication session is reused, reducing idle connections on embedded web servers.

## Logo

The logo combines Home Assistant-style presence, Pi-hole monitoring, and local-network diagnostics. Home Assistant and HACS use the assets in `custom_components/pihole_presence/brand`.

## Installation

### HACS

1. Open this repository in HACS using the button below, or add it as a custom integration repository.
2. Install **Pi-hole Presence**.
3. Restart Home Assistant.
4. Add **Pi-hole Presence** from Settings > Devices & services.

To upgrade an existing installation, update the integration in HACS and restart Home Assistant. Keep the existing integration entry; its devices, entity IDs, and options are retained. Changes saved under **Configure** take effect through an integration reload without another Home Assistant restart.

[![Open your Home Assistant instance and add this repository to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=lrehmann&repository=pihole_presence&category=integration)

### Manual

1. Copy `custom_components/pihole_presence` into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Add **Pi-hole Presence** from Settings > Devices & services.

## Configuration

| Option | Description | Default |
| --- | --- | --- |
| **Host/IP** | Hostname, IP, or HTTP/HTTPS URL. Supports custom ports, IPv6, and reverse proxy prefixes; `/admin` or `/api` suffixes are normalized | `http://pi.hole` |
| **API Mode** | API selection. `Auto detect` tries Pi-hole v6 first, then the pre-v6 PHP API | `Auto detect` |
| **Password** | Optional Pi-hole v6 web or application password. Used to request a reusable session from `/api/auth` | empty |
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
* **Unauthorized on Pi-hole v6:** Complete the reauthentication prompt or set the web/application password under Configure. The password is used exactly as entered, including spaces.
* **Older Pi-hole with web password enabled:** Add the pre-v6 API token in integration options, or force API Mode to `Pi-hole pre-v6 PHP API`.
* **Host sensors unavailable:** CPU, memory, and temperature sensors require the Pi-hole v6 info API. Legacy pre-v6 installs continue to provide presence tracking only.
* **Duplicate devices:** Ensure other integrations do not use conflicting MAC connections, then clear stale device registry entries if needed.
* **Presence always away:** Verify the away threshold and that the device is actually making DNS queries through Pi-hole.
* **Busy networks or restricted query access:** Optional query history is limited to five pages of 1,000 results and an eight-second fetch budget per poll. Missing or incomplete query history falls back to Pi-hole's network-table timestamps, which can update less frequently. Downloaded diagnostics report whether the most recent query fetch completed.
* **Reporting a problem:** Use the integration entry's menu to download diagnostics. The file includes API mode, update status, counts, and query-fetch completeness. It excludes the host address, credentials, MAC/IP addresses, device names, and DNS queries. When setup has not completed, only saved non-secret settings and loaded status are available.

## Development

Install the Home Assistant version you want to test and the test tools in an isolated environment:

```sh
python -m pip install "homeassistant==2026.10.4" "pytest>=8,<9" "pytest-asyncio==1.3.0" "setuptools<81" ruff
python -m pytest -q
ruff check custom_components tests
ruff format --check custom_components tests
```

Use the Python version corresponding to that Home Assistant release; the CI matrix documents the combinations. The setuptools constraint is needed by the oldest Home Assistant release's test environment, not by the integration. Tests do not contact a live Home Assistant or Pi-hole.

For older releases, install with the matching Home Assistant `homeassistant/package_constraints.txt`, as CI does. The 2024.11.3 test environment also needs `josepy<2` because its ACME dependency uses an API removed in josepy 2. These constraints only affect test environments; this integration adds no runtime packages to Home Assistant.

## License

MIT
