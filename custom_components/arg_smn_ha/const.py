"""Constants for the SMN Argentina (OpenSMN) integration."""

from __future__ import annotations

from typing import Final

from homeassistant.components.weather import (
    ATTR_CONDITION_CLEAR_NIGHT,
    ATTR_CONDITION_CLOUDY,
    ATTR_CONDITION_FOG,
    ATTR_CONDITION_LIGHTNING_RAINY,
    ATTR_CONDITION_PARTLYCLOUDY,
    ATTR_CONDITION_POURING,
    ATTR_CONDITION_RAINY,
    ATTR_CONDITION_SNOWY,
    ATTR_CONDITION_SNOWY_RAINY,
    ATTR_CONDITION_SUNNY,
    ATTR_CONDITION_WINDY,
)
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME, CONF_SCAN_INTERVAL

DOMAIN: Final = "arg_smn_ha"

# Config keys (CONF_LATITUDE / CONF_LONGITUDE / CONF_NAME are reused from HA).
CONF_CONNECTION_TYPE: Final = "connection_type"
CONF_OPENSMN_URL: Final = "opensmn_url"
CONF_OPENSMN_PASSWORD: Final = "opensmn_password"
CONF_SMN_TOKEN: Final = "smn_token"

CONNECTION_TYPE_OPENSMN: Final = "opensmn"
CONNECTION_TYPE_DIRECT: Final = "direct"

DEFAULT_CONNECTION_TYPE: Final = CONNECTION_TYPE_DIRECT
DEFAULT_OPENSMN_URL: Final = "http://localhost:6942/smn"
DEFAULT_SCAN_INTERVAL_SECONDS: Final = 1800  # 30 minutes
MIN_SCAN_INTERVAL_SECONDS: Final = 600  # 10 minutes
MAX_SCAN_INTERVAL_SECONDS: Final = 7200  # 2 hours

# Direct SMN backend (same endpoints the reference integration uses).
SMN_DIRECT_BASE_URL: Final = "https://ws1.smn.gob.ar"
SMN_TOKEN_PAGES: Final = (
    "https://ws2.smn.gob.ar/",
    "https://www.smn.gob.ar/",
)

# Relative API paths, appended to either the OpenSMN base URL or the SMN base.
PATH_GEOREF_COORD: Final = "/v1/georef/location/coord"
PATH_WEATHER: Final = "/v1/weather/location"
PATH_FORECAST: Final = "/v1/forecast/location"
PATH_ALERT: Final = "/v1/warning/alert/location"
PATH_SHORTTERM_ALERT: Final = "/v1/warning/shortterm/location"
PATH_HEAT_WARNING: Final = "/v1/warning/heat/area"

REQUEST_TIMEOUT_SECONDS: Final = 15

# Services.
SERVICE_GET_ALERTS: Final = "get_alerts"
SERVICE_GET_ALERTS_FOR_LOCATION: Final = "get_alerts_for_location"

# HA event names fired when alerts change.
EVENT_ALERT_CREATED: Final = f"{DOMAIN}_alert_created"
EVENT_ALERT_UPDATED: Final = f"{DOMAIN}_alert_updated"
EVENT_ALERT_CLEARED: Final = f"{DOMAIN}_alert_cleared"

# Re-exported HA conf keys so platforms import from one place.
__all__ = [
    "CONF_LATITUDE",
    "CONF_LONGITUDE",
    "CONF_NAME",
    "CONF_SCAN_INTERVAL",
]

# SMN weather ID -> HA condition (from SMN official icon table).
CONDITION_ID_MAP: Final = {
    3: ATTR_CONDITION_SUNNY,  # Despejado (dia)
    5: ATTR_CONDITION_CLEAR_NIGHT,  # Despejado (noche)
    13: ATTR_CONDITION_SUNNY,  # Ligeramente nublado (dia)
    14: ATTR_CONDITION_CLEAR_NIGHT,  # Ligeramente nublado (noche)
    19: ATTR_CONDITION_SUNNY,  # Algo nublado (dia)
    20: ATTR_CONDITION_CLEAR_NIGHT,  # Algo nublado (noche)
    25: ATTR_CONDITION_PARTLYCLOUDY,  # Parcialmente nublado (dia)
    26: ATTR_CONDITION_PARTLYCLOUDY,  # Parcialmente nublado (noche)
    37: ATTR_CONDITION_CLOUDY,  # Mayormente nublado (dia)
    38: ATTR_CONDITION_CLOUDY,  # Mayormente nublado (noche)
    43: ATTR_CONDITION_CLOUDY,  # Nublado
    51: ATTR_CONDITION_WINDY,  # Ventoso
    61: ATTR_CONDITION_FOG,  # Neblina
    67: ATTR_CONDITION_FOG,  # Niebla
    69: ATTR_CONDITION_FOG,  # Niebla helada
    71: ATTR_CONDITION_RAINY,  # Llovizna
    72: ATTR_CONDITION_RAINY,  # Lluvias aisladas
    73: ATTR_CONDITION_RAINY,  # Lluvias
    74: ATTR_CONDITION_POURING,  # Chaparrones (dia)
    75: ATTR_CONDITION_POURING,  # Chaparrones (noche)
    76: ATTR_CONDITION_LIGHTNING_RAINY,  # Tormentas aisladas
    77: ATTR_CONDITION_SNOWY_RAINY,  # Lluvias y nevadas
    79: ATTR_CONDITION_SNOWY,  # Nevadas
    81: ATTR_CONDITION_LIGHTNING_RAINY,  # Tormentas
    83: ATTR_CONDITION_POURING,  # Lluvias fuertes
    85: ATTR_CONDITION_SNOWY,  # Nevadas fuertes
    89: ATTR_CONDITION_LIGHTNING_RAINY,  # Tormentas fuertes
    92: ATTR_CONDITION_SNOWY,  # Ventisca alta
    94: ATTR_CONDITION_SNOWY,  # Ventisca
    96: ATTR_CONDITION_SNOWY,  # Ventisca baja
}

# SMN alert event ID -> slug.
ALERT_EVENT_MAP: Final = {
    37: "lluvia",
    39: "viento",
    40: "niebla",
    41: "tormenta",
    42: "nevada",
    43: "altas_temperaturas",
    44: "bajas_temperaturas",
    45: "ceniza_volcanica",
    46: "polvo",
    47: "viento_zonda",
    54: "humo",
}

ALERT_EVENT_ICONS: Final = {
    "lluvia": "mdi:weather-rainy",
    "viento": "mdi:weather-windy",
    "niebla": "mdi:weather-fog",
    "tormenta": "mdi:weather-lightning",
    "nevada": "mdi:weather-snowy",
    "altas_temperaturas": "mdi:thermometer-high",
    "bajas_temperaturas": "mdi:thermometer-low",
    "ceniza_volcanica": "mdi:volcano",
    "polvo": "mdi:weather-dust",
    "viento_zonda": "mdi:weather-windy-variant",
    "humo": "mdi:smoke",
}

ALERT_LEVEL_MAP: Final = {
    1: {"name": "none", "color": "white", "severity": "info"},
    2: {"name": "advertencia", "color": "violeta", "severity": "warning"},
    3: {"name": "amarillo", "color": "amarillo", "severity": "warning"},
    4: {"name": "naranja", "color": "naranja", "severity": "error"},
    5: {"name": "rojo", "color": "rojo", "severity": "error"},
}
