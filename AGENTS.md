# AGENTS.md

HACS custom integration `arg_smn_ha` (SMN Argentina via OpenSMN proxy or direct SMN). Platforms: `weather`, `binary_sensor`.

## Verify

```bash
python -m compileall custom_components/arg_smn_ha tests
python -m unittest discover -s tests -v
python -c "import json,glob; [json.load(open(f, encoding='utf-8')) for f in glob.glob('custom_components/arg_smn_ha/**/*.json', recursive=True)]"
```

CI (`.github/workflows/validate.yml`): compile + unittest + hassfest + HACS validation. Tests run with **no HA runtime** via `tests/stubs.py` (stubs `homeassistant.*`, `aiohttp`, `async_timeout`, `voluptuous`); `test_api.py`/`test_parsing.py` pre-register empty parent packages to skip the real `__init__.py`.

## Gotchas

- `strings.json` must equal `translations/en.json`; `es.json` must have the same key tree; every entity translation key needs an `icon.json` entry — all enforced by `tests/test_release.py`.
- `hacs.json` `filename` must equal manifest `domain` (`arg_smn_ha`); `content_in_root: false`; min HA `2024.1.0` (for `async_get_forecasts`).
- Unique ID is `{connection_type}_{location_id}` plus a ±0.0001° coord-dupe check in `config_flow.py`.
- Coordinator (`coordinator.py`) reads proxy URL/password from `entry.options` first, `entry.data` fallback; options flow stores credential rotation there. Services (`__init__.py`) reuse the first entry's backend the same way — keep all three in sync.
- Weather uses modern `async_get_forecasts(kind)` only (no legacy `async_forecast_*`); SMN visibility is meters, entity converts to km.
- Alert sensor tracks `dict[id -> level]` to fire `created`/`updated`/`cleared` events; keep `EVENT_*` names in `const.py` as the single source.
- Never commit `cache/`, `token`, `.env`, `debug_page_source.html` (already gitignored).
