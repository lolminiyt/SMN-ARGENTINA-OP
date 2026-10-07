# SMN Argentina (OpenSMN) para Home Assistant

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)

Integración de Home Assistant para el **Servicio Meteorológico Nacional (SMN)** de Argentina, con **doble conexión**:

- **Proxy OpenSMN (recomendado):** apuntá la integración a tu instancia auto-hospedada de [OpenSMN](https://github.com/nixietab/OpenSMN). El proxy se encarga del token JWT del SMN, cachea las respuestas y evita meter el scraping de tokens y Cloudflare dentro de Home Assistant.
- **SMN directo:** habla con `https://ws1.smn.gob.ar` directamente, como la integración de referencia. El token se obtiene y se renueva dentro de HA.

Integración de referencia/ejemplo: https://github.com/catastrophicode/ha-ar-smn

## Funciones

### Entidad de clima (`weather.*`)

- Actual: temperatura, sensación térmica, humedad, presión, viento (velocidad y dirección), visibilidad
- Iconos según los IDs oficiales del SMN (distingue día/noche)
- **Pronóstico diario** (`weather.get_forecasts` con `type: daily`)
- **Pronóstico por hora** (`weather.get_forecasts` con `type: hourly`, 4 períodos por día)
- Datos de la estación en atributos (`location_id`, `location_name`, `observed_at`)

### Sensores binarios de alertas (`binary_sensor.*`)

- Sensor general `weather_alert` + 11 sensores por evento (tormenta, lluvia, nevada, viento, viento_zonda, altas/bajas temperaturas, niebla, polvo, humo, ceniza_volcanica) + `short_term_alert`
- Atributos útiles: nivel, severidad, descripción, instrucciones, resumen
- Eventos de HA cuando cambian las alertas: `arg_smn_ha_alert_created`, `arg_smn_ha_alert_updated`, `arg_smn_ha_alert_cleared`

### Servicios

- `arg_smn_ha.get_alerts` — alertas de la ubicación configurada (parámetro opcional `config_entry_id`)
- `arg_smn_ha.get_alerts_for_location` — alertas de cualquier `location_id` del SMN

## Instalación

### HACS (recomendado)

1. HACS → Integraciones → ⋮ → Repositorios personalizados → agregá la URL de este repo, categoría Integración
2. Buscá `SMN Argentina`, Instalá, Reiniciá HA

### Manual

Copiá `custom_components/arg_smn_ha` en `<config>/custom_components/` y reiniciá HA.

## Configuración

Ajustes → Dispositivos y servicios → Agregar integración → **SMN Argentina (OpenSMN)**.

**Paso 1:** elegí el tipo de conexión y completá latitud, longitud y nombre.
- **SMN directo** (por defecto): anda de una, sin servidor. Recomendado para empezar.
- **Proxy OpenSMN** (avanzado): te pide un **paso 2** con la URL y contraseña de tu proxy.

**Paso 2 (solo proxy):** URL base (ej. `http://192.168.1.10:6942/smn`) y contraseña (**exactamente igual** al `PASSWORD` de tu `.env` de OpenSMN; vacía si no tiene).

### Si el modo directo falla: pegá tu token manual

El SMN a veces bloquea la obtención automática del token. Si ves "No se pudo conectar directo al SMN", conseguí tu token en 1 minuto:

1. Abrí https://www.smn.gob.ar/ en tu navegador (Chrome/Edge/Firefox).
2. Apretá **F12** → pestaña **Aplicación** (o *Application*) → **Almacenamiento local** → `https://www.smn.gob.ar`.
3. Copiá el valor de **`token`** (empieza con `eyJ`, es un texto largo).
4. Volvé al instalador, elegí **SMN directo** y pegalo en **Token del SMN**.

Ojo: el token manual también vence en 1 hora; sirve para salir del paso, pero lo ideal es dejar el campo vacío y que la integración lo renueve sola (ver abajo). Si vence, la integración te avisa para reautenticar.

### El token dura 1 hora: ¿cómo se refresca solo?

El JWT del SMN expira cada hora (verificado). La integración lo renueva sola: 10 minutos antes de vencer obtiene uno nuevo, y si un pedido da 401 reintenta con token fresco. Como el SMN a veces bloquea el scrapeo (Cloudflare intermitente), cada renovación reintenta hasta 5 veces con pausas entre intentos.

- **Meter el proxy DENTRO del plugin no se puede**: el proxy usa Selenium + Chrome para esquivar Cloudflare, y en Home Assistant (HAOS/Docker) no hay navegador ni forma de instalar uno. Por eso el proxy es un servidor aparte.
- Si el modo directo tiene baches en tus horarios, el proxy auto-hospedado es el camino fiable: él se encarga del token y cachea.

| Campo | Modo proxy | Modo directo |
|---|---|---|
| Tipo de conexión | `Proxy OpenSMN` | `SMN directo` (por defecto) |
| URL base de OpenSMN | ej. `http://192.168.1.10:6942/smn` | no se pide |
| Contraseña de OpenSMN | valor de `PASSWORD` en el `.env` de OpenSMN, vacío si no tiene | no se pide |
| Latitud/Longitud | coordenadas de tu estación | igual |
| Nombre | nombre de la entidad/dispositivo | igual |

La configuración valida resolviendo el `location_id` con `GET {base}/v1/georef/location/coord?lat=..&lon=..`. No deja duplicados (misma estación o coordenadas a menos de ~11 m). En Opciones podés cambiar el intervalo de actualización (600–7200 s, por defecto 1800 s) y rotar las credenciales del proxy.

### ¿Qué pongo en cada campo?

- **Tipo de conexión:** si levantaste OpenSMN en tu red, `Proxy OpenSMN`. Si no tenés ningún servidor, `SMN directo` (no pide URL ni contraseña, anda de una).
- **URL base de OpenSMN:** la dirección de tu proxy, ej. `http://192.168.1.10:6942/smn`. Ojo: `localhost` solo sirve si OpenSMN corre en la misma máquina que Home Assistant (con HAOS o Docker, `localhost` es el propio HA, así que usá la IP de tu red).
- **Contraseña de OpenSMN:** tiene que ser **exactamente igual** al valor de `PASSWORD` en el archivo `.env` de OpenSMN. Si en tu `.env` no pusiste contraseña (vacío), dejá este campo **vacío** también.

> Primero auto-hospedá OpenSMN: `git clone https://github.com/nixietab/OpenSMN`, `pip install -r requirements.txt`, `cp .env.example .env`, `uvicorn server:app --port 6942` (desarrollo) o `./start.sh` (producción).

## Ejemplos de automatizaciones

```yaml
automation:
  - alias: "SMN alerta meteorológica"
    trigger:
      - platform: state
        entity_id: binary_sensor.caba_weather_alert
        to: "on"
    action:
      - service: notify.mobile_app
        data:
          title: "Alerta del SMN"
          message: "{{ state_attr('binary_sensor.caba_weather_alert', 'alert_summary') }}"

  - alias: "SMN pronóstico diario a las 7am"
    trigger:
      - platform: time
        at: "07:00:00"
    action:
      - service: weather.get_forecasts
        target:
          entity_id: weather.caba
        data:
          type: daily
        response_variable: daily
```

## Servicios

```yaml
service: arg_smn_ha.get_alerts
response_variable: alerts
```

```yaml
service: arg_smn_ha.get_alerts_for_location
data:
  location_id: "4864"
response_variable: alerts
```

## Solución de problemas

- **No conecta (proxy):** ¿está levantado OpenSMN? `curl {base}/v1/weather/location/4864`. Fijate que `PASSWORD` coincida con el header `Authorization`.
- **401 invalid_auth:** actualizá desde la entrada → Reconfigurar, u Opciones → actualizá la contraseña.
- **Ubicación no encontrada:** coordenadas fuera de Argentina o lejos de cualquier estación — probá con una ciudad cercana.
- **Datos desactualizados:** por defecto actualiza cada 30 min; revisá la última actualización en Herramientas de desarrollo → Estados.
- **Registros de depuración** (`configuration.yaml`):

```yaml
logger:
  logs:
    custom_components.arg_smn_ha: debug
```

## Privacidad / créditos

- En modo proxy la autenticación queda en tu servidor; HA solo ve tu host OpenSMN.
- Datos: [Servicio Meteorológico Nacional Argentina](https://www.smn.gob.ar/).
- Proxy: [OpenSMN](https://github.com/nixietab/OpenSMN) (GPL-2.0). Esta integración es MIT y no tiene afiliación con el SMN.
