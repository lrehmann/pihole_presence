DOMAIN = "pihole_presence"

CONF_AWAY_TIME = "away_time"
CONF_API_MODE = "api_mode"
CONF_API_TOKEN = "api_token"
CONF_HOST = "host"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_STALE_DEVICE_DAYS = "stale_device_days"

DEFAULT_HOST = "http://pi.hole"
DEFAULT_API_MODE = "auto"
DEFAULT_SCAN_INTERVAL = 30  # seconds
DEFAULT_AWAY_TIME = 900  # seconds, 15 min
DEFAULT_STALE_DEVICE_DAYS = 30

API_MODE_AUTO = "auto"
API_MODE_V6 = "v6"
API_MODE_LEGACY = "legacy"
API_MODE_OPTIONS = {
    API_MODE_AUTO: "Auto detect",
    API_MODE_V6: "Pi-hole v6 API",
    API_MODE_LEGACY: "Pi-hole pre-v6 PHP API",
}

ATTR_INTERFACE = "interface"
ATTR_FIRST_SEEN = "first_seen"
ATTR_LAST_QUERY = "last_query"
ATTR_NUM_QUERIES = "num_queries"
ATTR_MAC_VENDOR = "mac_vendor"
ATTR_IPS = "ips"
ATTR_IP_ADDRESSES = "ip_addresses"
ATTR_PRIMARY_IP = "primary_ip"
ATTR_NAME = "name"
ATTR_DHCP_EXPIRES = "dhcp_expires"
ATTR_LAST_SEEN = "last_seen"

LEASES_ENDPOINT = "/api/dhcp/leases"
DEVICES_ENDPOINT = "/api/network/devices?max_devices=999&max_addresses=24"
QUERIES_ENDPOINT = "/api/queries"
AUTH_ENDPOINT = "/api/auth"
SYSTEM_ENDPOINT = "/api/info/system"
SENSORS_ENDPOINT = "/api/info/sensors"
LEGACY_NETWORK_ENDPOINT = "/admin/api_db.php"
