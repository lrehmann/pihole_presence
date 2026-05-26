DOMAIN = "pihole_presence"

CONF_AWAY_TIME = "away_time"
CONF_HOST = "host"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_STALE_DEVICE_DAYS = "stale_device_days"

DEFAULT_HOST = "http://pi.hole"
DEFAULT_SCAN_INTERVAL = 30  # seconds
DEFAULT_AWAY_TIME = 900  # seconds, 15 min
DEFAULT_STALE_DEVICE_DAYS = 30

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
