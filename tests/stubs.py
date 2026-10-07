"""Shared stubs so unit tests run without a Home Assistant runtime."""
import sys
import types
from datetime import datetime, timezone


def _cls(name: str, **attrs: object) -> type:
    return type(name, (), attrs)


def install_stubs() -> None:
    if "homeassistant" in sys.modules:
        return
    ha = types.ModuleType("homeassistant")

    components = types.ModuleType("homeassistant.components")
    weather = types.ModuleType("homeassistant.components.weather")
    for name in [
        "clear-night", "cloudy", "fog", "lightning-rainy", "partlycloudy",
        "pouring", "rainy", "snowy", "snowy-rainy", "sunny", "windy", "exceptional",
    ]:
        setattr(weather, f"ATTR_CONDITION_{name.upper().replace('-', '_')}", name)
    weather.Forecast = dict
    weather.WeatherEntity = object
    weather.WeatherEntityFeature = _cls("WeatherEntityFeature", FORECAST_DAILY=1, FORECAST_HOURLY=2)
    components.weather = weather

    binary_sensor = types.ModuleType("homeassistant.components.binary_sensor")
    binary_sensor.BinarySensorDeviceClass = _cls("BinarySensorDeviceClass", SAFETY="safety")
    binary_sensor.BinarySensorEntity = object
    components.binary_sensor = binary_sensor

    const = types.ModuleType("homeassistant.const")
    const.CONF_LATITUDE = "latitude"
    const.CONF_LONGITUDE = "longitude"
    const.CONF_NAME = "name"
    const.CONF_SCAN_INTERVAL = "scan_interval"
    const.Platform = _cls("Platform", WEATHER="weather", BINARY_SENSOR="binary_sensor")
    const.UnitOfPressure = _cls("UnitOfPressure", HPA="hPa")
    const.UnitOfSpeed = _cls("UnitOfSpeed", KILOMETERS_PER_HOUR="km/h")
    const.UnitOfTemperature = _cls("UnitOfTemperature", CELSIUS="°C")
    const.UnitOfLength = _cls("UnitOfLength", KILOMETERS="km")
    const.CONF_NAME = "name"
    const.EntityCategory = _cls("EntityCategory", DIAGNOSTIC="diagnostic")

    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    core.ServiceCall = object
    core.Event = object
    core.callback = lambda f: f

    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    config_entries.ConfigFlow = object
    config_entries.ConfigFlowResult = dict
    config_entries.OptionsFlow = object

    exceptions = types.ModuleType("homeassistant.exceptions")
    exceptions.ConfigEntryAuthFailed = type("ConfigEntryAuthFailed", (Exception,), {})
    exceptions.ConfigEntryNotReady = type("ConfigEntryNotReady", (Exception,), {})

    helpers = types.ModuleType("homeassistant.helpers")
    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda hass: None
    config_validation = types.ModuleType("homeassistant.helpers.config_validation")
    config_validation.string = str
    config_validation.latitude = float
    config_validation.longitude = float
    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")

    class _Coordinator:
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, hass=None, logger=None, name=None, update_interval=None, **kwargs):
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval
            self.last_update_success = True
            self.data = None

        async def async_config_entry_first_refresh(self):
            await self._async_update_data()

        async def async_request_refresh(self):
            await self._async_update_data()

    update_coordinator.DataUpdateCoordinator = _Coordinator
    update_coordinator.UpdateFailed = type("UpdateFailed", (Exception,), {})

    class _CoordEntity:
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, coordinator=None, **kwargs):
            self.coordinator = coordinator
            self.hass = getattr(coordinator, "hass", None)

    update_coordinator.CoordinatorEntity = _CoordEntity
    device_registry = types.ModuleType("homeassistant.helpers.device_registry")
    device_registry.DeviceEntryType = _cls("DeviceEntryType", SERVICE="service")
    device_registry.DeviceInfo = dict
    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    entity_platform.AddEntitiesCallback = object
    sun = types.ModuleType("homeassistant.helpers.sun")
    sun.is_up = lambda hass: True
    event = types.ModuleType("homeassistant.helpers.event")
    event.async_track_state_change_event = lambda *a, **k: None
    event.async_call_later = lambda *a, **k: None

    util = types.ModuleType("homeassistant.util")
    dt_mod = types.ModuleType("homeassistant.util.dt")
    dt_mod.UTC = timezone.utc
    dt_mod.utcnow = lambda: datetime.now(timezone.utc)

    def _parse_datetime(s):
        try:
            return datetime.fromisoformat(str(s))
        except Exception:
            return None

    def _parse_date(s):
        try:
            from datetime import date as _date
            return _date.fromisoformat(str(s))
        except Exception:
            return None

    dt_mod.parse_datetime = _parse_datetime
    dt_mod.parse_date = _parse_date
    util.dt = dt_mod

    for name, mod in {
        "homeassistant": ha,
        "homeassistant.components": components,
        "homeassistant.components.weather": weather,
        "homeassistant.components.binary_sensor": binary_sensor,
        "homeassistant.const": const,
        "homeassistant.core": core,
        "homeassistant.config_entries": config_entries,
        "homeassistant.exceptions": exceptions,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.aiohttp_client": aiohttp_client,
        "homeassistant.helpers.config_validation": config_validation,
        "homeassistant.helpers.update_coordinator": update_coordinator,
        "homeassistant.helpers.device_registry": device_registry,
        "homeassistant.helpers.entity_platform": entity_platform,
        "homeassistant.helpers.sun": sun,
        "homeassistant.helpers.event": event,
        "homeassistant.util": util,
        "homeassistant.util.dt": dt_mod,
    }.items():
        sys.modules[name] = mod

    if "aiohttp" not in sys.modules:
        aiohttp = types.ModuleType("aiohttp")
        aiohttp.ClientSession = object
        aiohttp.ClientError = type("ClientError", (Exception,), {})
        sys.modules["aiohttp"] = aiohttp
    if "async_timeout" not in sys.modules:
        at = types.ModuleType("async_timeout")
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def timeout(*args, **kwargs):
            yield

        at.timeout = timeout
        sys.modules["async_timeout"] = at
    if "voluptuous" not in sys.modules:
        vol = types.ModuleType("voluptuous")

        class _Schema:
            def __init__(self, *args, **kwargs):
                pass

            def __call__(self, data):
                return data

        class _Marker:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

            def __hash__(self):
                return id(self)

            def __eq__(self, other):
                return self is other

        vol.Schema = _Schema
        vol.Required = lambda *a, **k: _Marker(*a, **k)
        vol.Optional = lambda *a, **k: _Marker(*a, **k)
        vol.In = lambda *a, **k: (lambda v: v)
        vol.All = lambda *a, **k: (lambda v: v)
        vol.Coerce = lambda *a, **k: (lambda v: v)
        vol.Range = lambda *a, **k: (lambda v: v)
        sys.modules["voluptuous"] = vol
