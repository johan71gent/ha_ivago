"""Constants for the IVAGO integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "ivago"

CONF_STREET = "street"
CONF_NUMBER = "number"
CONF_STREET_QUERY = "street_query"

# Options
CONF_SCAN_INTERVAL_HOURS = "scan_interval_hours"
CONF_LOOKAHEAD_DAYS = "lookahead_days"
DEFAULT_SCAN_INTERVAL_HOURS = 12
DEFAULT_LOOKAHEAD_DAYS = 90

BASE_URL = "https://www.ivago.be"
URL_PICKUP_PAGE = f"{BASE_URL}/nl/particulier/afval/ophaling"
URL_PICKUPS = f"{BASE_URL}/nl/particulier/garbage/pick-up/pickups"
URL_STREETS = f"{BASE_URL}/nl/particulier/autocomplete/garbage/streets"

USER_AGENT = "Mozilla/5.0 (compatible; HomeAssistant IVAGO integration)"

SCAN_INTERVAL = timedelta(hours=DEFAULT_SCAN_INTERVAL_HOURS)

# Known waste types as returned by the IVAGO API (``label``).
WASTE_TYPES: dict[str, dict[str, str]] = {
    "RESTAFVAL": {"name": "Restafval", "icon": "mdi:trash-can"},
    "PMD": {"name": "PMD", "icon": "mdi:recycle"},
    "GFT": {"name": "GFT", "icon": "mdi:leaf"},
    "PAPIER": {"name": "Papier en karton", "icon": "mdi:newspaper-variant-multiple"},
    "GLAS": {"name": "Glas", "icon": "mdi:bottle-wine"},
    "GROFVUIL": {"name": "Grofvuil", "icon": "mdi:sofa"},
    "KERSTBOMEN": {"name": "Kerstbomen", "icon": "mdi:pine-tree"},
}

DEFAULT_ICON = "mdi:delete"
