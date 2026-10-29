# Changelog

## 0.7.0 — 2026-10-29

### Configuration and compatibility

- Fix the Configure HTTP 500 caused by assigning the now read-only `OptionsFlow.config_entry` property (issue #6).
- Match mutable and frozen sensor description classes across Home Assistant releases, and pass config entries to coordinators where supported.
- Validate required API data before saving settings. Accept bare hosts/IPs, IPv6, admin URLs, custom ports, and reverse proxy prefixes.
- Reload when options change and offer reauthentication for invalid or changed credentials, retaining existing entries and entity unique IDs.

### Reliability

- Reuse sliding-expiry Pi-hole v6 sessions until rejected; retry session authentication once. Release owned sessions on failed setup, unload, shutdown, and connection validation.
- Explicitly close HTTP connections after each response without closing Home Assistant's shared HTTP client or recreating API authentication sessions.
- Give timeouts a useful message instead of a blank retry reason, respect HTTP rate limits and `Retry-After`, and retain bounded exponential backoff.
- Cache API discovery while allowing a v5-to-v6 upgrade when the legacy endpoint disappears. Never treat authentication or connection failures as evidence of an older API.
- Handle legacy numeric timestamps and empty unauthorized PHP responses; reject malformed required responses rather than treating them as empty successful polls.
- Bound recent-query fetching to five 1,000-result pages and eight seconds. Follow server cursors even when a server caps page length. Missing optional endpoints continue to fall back to network timestamps.
- Keep optional rate limits from disabling required presence polls, and reject non-finite sensor readings. Support Kelvin temperature readings.
- Add diagnostics that omit credentials and local network identities, including whether optional query fetching completed.

### Validation

- Add regression and isolated HTTP tests covering both API families, configuration, authentication, lifecycle cleanup, sensors, diagnostics, and recovery from failures.
- Run tests on Home Assistant 2023.1.7, 2024.11.3, 2025.12.5, and 2026.10.4, alongside HACS and Hassfest validation.
- Update GitHub Actions and add monthly Actions dependency checks.

Upgrade through HACS and restart Home Assistant. Keep the existing integration entry; no device or entity migration is required.
