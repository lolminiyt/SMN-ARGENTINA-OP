"""Constants for the SMN integration."""

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

DOMAIN: Final = "argentina_smn"

# API endpoints. ws1 is the public API used by the SMN website and app.
API_BASE_URL: Final = "https://ws1.smn.gob.ar/v1"
API_TOKEN_ENDPOINT: Final = f"{API_BASE_URL}/api-token/auth"
API_COORD_ENDPOINT: Final = f"{API_BASE_URL}/georef/location/coord"
API_WEATHER_ENDPOINT: Final = f"{API_BASE_URL}/weather/location"
API_FORECAST_ENDPOINT: Final = f"{API_BASE_URL}/forecast/location"
API_ALERT_ENDPOINT: Final = f"{API_BASE_URL}/warning/alert/location"
API_SHORTTERM_ALERT_ENDPOINT: Final = f"{API_BASE_URL}/warning/shortterm/location"
API_HEAT_WARNING_ENDPOINT: Final = f"{API_BASE_URL}/warning/heat/area"

# The anonymous "web" JWT is published in the HTML of the public site.
# ws2.smn.gob.ar no longer resolves, so the token must come from www.smn.gob.ar.
TOKEN_PAGE: Final = "https://www.smn.gob.ar/"

# SMN publishes all times in Argentina local time (UTC-3, no DST).
SMN_TIMEZONE: Final = "America/Argentina/Buenos_Aires"

# Update intervals
DEFAULT_SCAN_INTERVAL: Final = 3600  # 1 hour in seconds
DEFAULT_TIMEOUT: Final = 30  # seconds
TOKEN_TIMEOUT: Final = 15  # seconds; keep token scraping snappy

# Weather condition ID mappings - SMN ID to HA condition
# Based on SMN's official weather icon reference table
CONDITION_ID_MAP: Final = {
    3: ATTR_CONDITION_SUNNY,  # Despejado (día)
    5: ATTR_CONDITION_CLEAR_NIGHT,  # Despejado (noche)
    13: ATTR_CONDITION_PARTLYCLOUDY,  # Ligeramente nublado (día)
    14: ATTR_CONDITION_PARTLYCLOUDY,  # Ligeramente nublado (noche)
    19: ATTR_CONDITION_PARTLYCLOUDY,  # Algo nublado (día)
    20: ATTR_CONDITION_PARTLYCLOUDY,  # Algo nublado (noche)
    25: ATTR_CONDITION_PARTLYCLOUDY,  # Parcialmente nublado (día)
    26: ATTR_CONDITION_PARTLYCLOUDY,  # Parcialmente nublado (noche)
    37: ATTR_CONDITION_CLOUDY,  # Mayormente nublado (día)
    38: ATTR_CONDITION_CLOUDY,  # Mayormente nublado (noche)
    43: ATTR_CONDITION_CLOUDY,  # Nublado
    51: ATTR_CONDITION_WINDY,  # Ventoso
    61: ATTR_CONDITION_FOG,  # Neblina
    67: ATTR_CONDITION_FOG,  # Niebla
    69: ATTR_CONDITION_FOG,  # Niebla helada
    71: ATTR_CONDITION_RAINY,  # Llovizna
    72: ATTR_CONDITION_RAINY,  # Lluvias aisladas
    73: ATTR_CONDITION_RAINY,  # Lluvias
    74: ATTR_CONDITION_POURING,  # Chaparrones (día)
    75: ATTR_CONDITION_POURING,  # Chaparrones (noche)
    76: ATTR_CONDITION_LIGHTNING_RAINY,  # Tormentas aisladas
    77: ATTR_CONDITION_SNOWY_RAINY,  # Lluvias y Nevadas
    79: ATTR_CONDITION_SNOWY,  # Nevadas
    81: ATTR_CONDITION_LIGHTNING_RAINY,  # Tormentas
    83: ATTR_CONDITION_POURING,  # Lluvias fuertes
    85: ATTR_CONDITION_SNOWY,  # Nevadas fuertes
    89: ATTR_CONDITION_LIGHTNING_RAINY,  # Tormentas fuertes
    92: ATTR_CONDITION_SNOWY,  # Ventisca alta
    94: ATTR_CONDITION_SNOWY,  # Ventisca
    96: ATTR_CONDITION_SNOWY,  # Ventisca baja
}

# Weather condition text mappings - SMN text to HA condition (fallback).
# Order matters: more specific conditions must be checked before generic ones
# (e.g. "lluvias fuertes" before "lluvia", "parcialmente nublado" before
# "nublado", and "despejado noche" before "despejado").
CONDITIONS_MAP: Final = {
    ATTR_CONDITION_CLEAR_NIGHT: ["despejado noche", "clear night"],
    ATTR_CONDITION_POURING: ["chaparron", "chaparrón", "lluvias fuertes"],
    ATTR_CONDITION_LIGHTNING_RAINY: ["tormenta"],
    ATTR_CONDITION_SNOWY_RAINY: ["lluvias y nevadas"],
    ATTR_CONDITION_SNOWY: ["nieve", "snow", "nevada", "ventisca"],
    ATTR_CONDITION_RAINY: [
        "lluvia",
        "llovizna",
        "rain",
        "drizzle",
        "lluvias aisladas",
    ],
    ATTR_CONDITION_FOG: ["niebla", "fog", "neblina"],
    ATTR_CONDITION_PARTLYCLOUDY: [
        "parcialmente nublado",
        "partly cloudy",
        "algo nublado",
        "ligeramente nublado",
    ],
    ATTR_CONDITION_CLOUDY: ["nublado", "cubierto", "cloudy", "overcast"],
    ATTR_CONDITION_WINDY: ["ventoso"],
    ATTR_CONDITION_SUNNY: ["despejado", "soleado", "clear", "sunny"],
}

# Alert event ID mappings - SMN event ID to event name
ALERT_EVENT_MAP: Final = {
    37: "lluvia",  # Rain
    39: "viento",  # Wind
    40: "niebla",  # Fog
    41: "tormenta",  # Thunderstorm
    42: "nevada",  # Snow
    43: "altas_temperaturas",  # High temperatures
    44: "bajas_temperaturas",  # Low temperatures
    45: "ceniza_volcanica",  # Volcanic ash
    46: "polvo",  # Dust
    47: "viento_zonda",  # Zonda wind
    54: "humo",  # Smoke
}

# Alert event icon mappings - event name to MDI icon
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

# Alert level mappings - SMN alert level to severity
ALERT_LEVEL_MAP: Final = {
    1: {"name": "none", "color": "white", "severity": "info"},
    2: {"name": "advertencia", "color": "violeta", "severity": "warning"},  # Advisory
    3: {"name": "amarillo", "color": "amarillo", "severity": "warning"},  # Yellow alert
    4: {"name": "naranja", "color": "naranja", "severity": "error"},  # Orange alert
    5: {"name": "rojo", "color": "rojo", "severity": "error"},  # Red alert
}
