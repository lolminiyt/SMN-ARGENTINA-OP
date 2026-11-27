# SMN (Servicio Meteorológico Nacional) - Home Assistant Integration

[![Validate](https://github.com/lolminiyt/SMN-ARGENTINA-OP/actions/workflows/validate.yml/badge.svg)](https://github.com/lolminiyt/SMN-ARGENTINA-OP/actions/workflows/validate.yml)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Home Assistant custom integration for Argentina's National Weather Service (SMN),
with current conditions, daily and 6-hourly forecasts, rain probability,
precipitation amounts, and weather alerts.

Requires Home Assistant 2024.6 or newer.

## How the SMN API Knows Which Forecast You Want

The SMN API exposes a georeference endpoint that resolves your coordinates to
the nearest SMN location:

```
GET /georef/location/coord?lat={latitude}&lon={longitude}
```

The integration calls `georef` once to obtain the SMN location ID (for example
`4743` for San Isidro, Buenos Aires) and then uses the ID for weather, forecast
and alert requests:

```
GET /weather/location/{locationId}
GET /forecast/location/{locationId}
GET /warning/alert/location/{locationId}
```

## Authentication

The public SMN API (`https://ws1.smn.gob.ar/v1`) requires a JWT:

- Header: `Authorization: JWT {token}`
- Tokens expire after about one hour and are refreshed automatically.

There are two ways to obtain a token:

1. **Anonymous web token (default).** The integration scrapes the token that
   `https://www.smn.gob.ar/` publishes for its own frontend. That site is behind
   a Cloudflare managed challenge, so the request is made with `curl_cffi`
   impersonating a real Chrome browser. `curl_cffi` is declared in
   `manifest.json` and installed by Home Assistant automatically.
2. **SMN account (optional).** If you have SMN API credentials, enter the
   username and password during setup. The integration then logs in through
   `POST /api-token/auth` instead of scraping the website.

No credentials are required for normal use. If SMN changes its website or
Cloudflare policy, the anonymous path can break until the integration is
updated; supplying SMN credentials is the fallback.

## API Endpoints Used

### Current Weather
- **Endpoint**: `/weather/location/{locationId}`
- **Data**: temperature, feels-like, humidity, pressure, visibility, wind speed
  and direction, condition, observation time, station name and ID.

### Forecast
- **Endpoint**: `/forecast/location/{locationId}`
- **Data**: up to 8 days, 4 periods per day (`early_morning`, `morning`,
  `afternoon`, `night`).
- **Fields**: min/max temperature, humidity, condition, wind, visibility,
  rain probability range (`rain_prob_range`) and expected precipitation in mm
  (`rain06h`).

### Alerts
- **Endpoint**: `/warning/alert/location/{locationId}`
- **Data**: warnings per day with event IDs and severity levels, plus reports
  and instructions when SMN publishes them.

## Features

- **Weather entity**: current conditions, daily forecast and 6-hourly forecast,
  including precipitation probability and precipitation amount.
- **Binary sensors**: a general weather alert sensor, one optional sensor per
  alert event (rain, wind, fog, thunderstorm, snow, extreme temperatures,
  volcanic ash, dust, Zonda wind, smoke) and a short-term alert sensor. The
  per-event sensors are disabled by default; enable the ones you need in the
  entity registry.
- **Alert events**: `argentina_smn_alert_created`, `argentina_smn_alert_updated`
  and `argentina_smn_alert_cleared` are fired on the Home Assistant bus.
- **Services**:
  - `argentina_smn.get_alerts` returns alerts for a configured entry.
  - `argentina_smn.get_alerts_for_location` returns alerts for any SMN location ID.
- **Configurable polling**: set the update interval (5–1440 minutes, default 60)
  from the integration's **Configure** dialog, with automatic token refresh.
- **Diagnostics**: download a redacted diagnostics file from the integration page.
- **HACS compatible**.

## Installation

### HACS (Recommended)
1. Add this repository as a custom repository in HACS.
2. Search for "SMN" in HACS.
3. Click Install.
4. Restart Home Assistant.

### Manual
1. Copy `custom_components/argentina_smn` to your `custom_components` directory.
2. Restart Home Assistant.

Home Assistant installs `curl_cffi` from `manifest.json` on first start; no
manual `pip install` is needed.

## Configuration

1. Go to **Settings** → **Devices & Services**.
2. Click **Add Integration**.
3. Search for **SMN**.
4. Choose how to set the location:
   - **Use the Home Assistant home location** (recommended): copies the home
     coordinates configured under **Settings** → **System** → **General**.
     Changing the HA home location later does not move an existing entry.
   - **Enter coordinates manually**: for a different city or location. The
     fields are pre-filled with the HA home coordinates.
5. Optionally set a friendly **Name** and SMN API **Username / Password**.
   Credentials are only needed if you have an SMN API account; otherwise the
   public web token is used. Leave both empty if you do not have an account.

If the HA home location is outside Argentina, the integration opens the manual
coordinates form pre-filled with that location so you can correct it without
restarting the flow.

The integration resolves the nearest SMN location, fetches current weather,
forecast and alerts, and creates the weather and binary sensor entities.

### Options

Open **Settings** → **Devices & Services** → **SMN** → **Configure** to change
the polling interval (5–1440 minutes). The default is 60 minutes.

### Reauthentication

If you configured SMN API credentials and SMN later rejects them, Home
Assistant shows a **Reauthenticate** action on the integration. Enter a valid
username and password to recover without removing the entry.

## Diagnostics

On the integration page, open the entry menu and choose **Download
diagnostics**. The file contains the resolved location, current weather,
forecasts and raw alert payloads. Username, password and token values are
redacted.

## Example Automations

```yaml
automation:
  - alias: "SMN Weather Alert Notification"
    trigger:
      - platform: state
        entity_id: binary_sensor.smn_weather_alert
        to: "on"
    action:
      - service: notify.mobile_app
        data:
          title: "Alerta Meteorológica"
          message: "{{ state_attr('binary_sensor.smn_weather_alert', 'alert_summary') }}"
```

```yaml
automation:
  - alias: "Rain expected tomorrow"
    trigger:
      - platform: time
        at: "20:00:00"
    action:
      - service: weather.get_forecasts
        target:
          entity_id: weather.smn_san_isidro
        data:
          type: daily
        response_variable: forecast
      - condition: template
        # Index 0 is today, index 1 is tomorrow.
        value_template: >
          {{ forecast['weather.smn_san_isidro'].forecast[1]
             .precipitation_probability | default(0) > 40 }}
      - service: notify.mobile_app
        data:
          message: "Rain is likely tomorrow."
```

## Data Provided

### Current Weather
- Temperature (°C)
- Feels-like temperature (°C), when SMN publishes it
- Humidity (%)
- Atmospheric pressure (hPa)
- Wind speed (km/h) and direction (°)
- Visibility (km)
- Condition with icon
- Observation time and station

Current conditions come from the SMN reference station that SMN associates with
the resolved location. In sparsely covered areas that station can be far away
(for example, San Justo, Santa Fe, uses CERES AERO about 164 km away); the
forecast is still generated for the requested location. The station name and
distance are exposed as weather entity attributes.

### Forecast
- Daily high/low temperatures
- 6-hourly conditions and temperatures
- Precipitation probability (%)
- Precipitation amount (mm)
- Wind speed and direction

### Alerts
- Active alert count
- Maximum severity level and colour (amarillo, naranja, rojo)
- Alert summary
- Per-event details with dates and levels
- Instructions and descriptions when available
- Last updated timestamp

## Troubleshooting

### Integration fails to load
- Verify your internet connection.
- Check Home Assistant logs: **Settings → System → Logs**.
- Restart Home Assistant.
- Confirm `curl_cffi` installed correctly; if not, reinstall the integration.

### Token errors / HTTP 403 from smn.gob.ar
- The public token is scraped from a Cloudflare-protected page. A temporary
  block or a change to the page can break anonymous access.
- Remove and re-add the integration with SMN API credentials, or wait and retry.
- `ws2.smn.gob.ar` is retired; the integration uses `ws1.smn.gob.ar` only.

### Weather data not updating
- The integration updates every hour by default.
- Check the coordinator's last update time in Developer Tools.
- Verify the SMN API is reachable from your network.

### Location not found
- Ensure coordinates are within Argentina (lat -55.5 to -21, lon -74 to -53).
- Try coordinates of a nearby major city.

### Diagnose a problem
- Download **Diagnostics** from the integration page (credentials and token are
  redacted) before opening an issue.
- The integration page reports the resolved SMN location, the reference
  weather station and its distance under the weather entity attributes.

### Enable debug logging
```yaml
logger:
  default: info
  logs:
    custom_components.argentina_smn: debug
```

## Development and Validation

The repository includes a GitHub Actions workflow that runs the official
validators on every push and pull request:

- [HACS Action](https://github.com/hacs/action) with `category: integration`
- [Hassfest](https://github.com/home-assistant/actions#hassfest)

Run the local checks before opening a pull request:

```bash
python -m compileall custom_components/argentina_smn
ruff check custom_components/argentina_smn
python -m json.tool custom_components/argentina_smn/manifest.json > /dev/null
python -m json.tool hacs.json > /dev/null
python -m json.tool custom_components/argentina_smn/strings.json > /dev/null
```

The integration is structured to be distributed as a HACS custom repository.
Inclusion in the HACS default store additionally requires a full GitHub release
(not just a tag), a repository description, topics, issues enabled, an OSI
license, and passing both validators without ignores.

## Credits

Data provided by [Servicio Meteorológico Nacional Argentina](https://www.smn.gob.ar/)

## License

MIT License

