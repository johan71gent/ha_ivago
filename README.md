<p align="center"><img src="assets/logo@2x.png" alt="IVAGO Afvalkalender" width="640"></p>

# IVAGO Afvalkalender – Home Assistant integration

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-%E2%98%95-FFDD00?style=for-the-badge&logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/johan71gent)

Custom integration that brings the **IVAGO waste collection calendar** (Ghent & Destelbergen, Belgium) into Home Assistant:
which type of household waste is collected today / tomorrow / next, plus a calendar entity with all pickups.

It uses the same (unofficial) endpoints as the calendar on
[ivago.be/nl/particulier/afval/ophaling](https://www.ivago.be/nl/particulier/afval/ophaling).
No account or API key needed — just your street and house number.

## Installation

### Via HACS (custom repository)
1. HACS → Integrations → ⋮ → *Custom repositories*
2. Add `https://github.com/johan71gent/ha_ivago`, category **Integration**
3. Install "IVAGO Afvalkalender" and restart Home Assistant

### Manual
Copy the folder `custom_components/ivago` to `<config>/custom_components/ivago` and restart Home Assistant.

## Configuration
*Settings → Devices & services → Add integration → "IVAGO Afvalkalender"*

- **Street**: the beginning of the street name is enough (e.g. `Kortrijkse`). If several streets match you get a dropdown
  (e.g. `Kortrijksesteenweg (GENT)` vs `Kortrijksesteenweg (SINT-DENIJS-WESTREM)`).
- **House number**: e.g. `12` or `12A`.

The address is validated against IVAGO. You can add multiple addresses (each gets its own device).

### Changing things later
- **Change address**: on the integration → ⋮ → *Reconfigure*. Entities are kept (entity IDs don't change, the device name does).
- **Options** (*Configure* button): update interval in hours (default 12) and how many days ahead to fetch (default 90). Changes apply immediately.

## Entities
One device is created per address, with:

| Entity | State | Attributes |
|---|---|---|
| `sensor.…_next_pickup` | `Vandaag: PMD, Restafval` / `Morgen: GFT` / `Over 6 dagen: GFT, PMD, Restafval` / `Geen ophaling gepland` | `date`, `weekday`, `days_until`, `waste_types` (e.g. `["PMD","RESTAFVAL"]`), `waste_types_names`, `waste_types_text` (e.g. `PMD, Restafval`) |
| `sensor.…_next_pickup_date` | date of the next collection day (device_class `date`) | same as above |
| `sensor.…_days_until_next_pickup` | number of days (0 = today) | |
| `sensor.…_pickup_today` | `PMD, Restafval` or `Geen` | `date`, `waste_types`, `has_pickup` |
| `sensor.…_pickup_tomorrow` | same, for tomorrow | same |
| `sensor.…_restafval`, `…_pmd`, `…_gft`, `…_papier_en_karton`, `…_glas`, `…_grofvuil`, `…_kerstbomen` | next date per waste type | `days_until`, `is_today`, `is_tomorrow`, `upcoming` (next 5 dates) |
| `calendar.…_pickup_calendar` | calendar with all pickups (all-day events) | |

Notes:
- Entity IDs follow your Home Assistant language: with Dutch UI you get e.g. `sensor.…_volgende_ophaling`, `…_ophaling_vandaag`, `…_ophaalkalender`.
- The text states (`Vandaag: …`, `Morgen: …`, `Over N dagen: …`, `Geen`) are in Dutch, matching the IVAGO service area. Use the attributes (`waste_types`, `days_until`, `has_pickup`) in templates and automations if you prefer language-independent values.
- Data is fetched every 12 hours (90 days ahead; both configurable) and the today/tomorrow sensors are recalculated right after midnight.

## Examples

**Notification the evening before**
```yaml
automation:
  - alias: IVAGO reminder
    trigger:
      - platform: time
        at: "19:00:00"
    condition:
      - condition: state
        entity_id: sensor.ivago_kortrijksesteenweg_gent_10_pickup_tomorrow
        attribute: has_pickup
        state: true
    action:
      - service: notify.mobile_app_phone
        data:
          title: "Put out the bins"
          message: "Tomorrow: {{ states('sensor.ivago_kortrijksesteenweg_gent_10_pickup_tomorrow') }}"
```

**Dashboard card**
```yaml
type: entities
title: IVAGO
entities:
  - sensor.ivago_kortrijksesteenweg_gent_10_next_pickup
  - sensor.ivago_kortrijksesteenweg_gent_10_days_until_next_pickup
  - sensor.ivago_kortrijksesteenweg_gent_10_restafval
  - sensor.ivago_kortrijksesteenweg_gent_10_pmd
  - sensor.ivago_kortrijksesteenweg_gent_10_gft
  - sensor.ivago_kortrijksesteenweg_gent_10_papier_en_karton
  - sensor.ivago_kortrijksesteenweg_gent_10_glas
```

## Support this project
Find this integration useful? A coffee is much appreciated and keeps maintenance going:

<a href="https://buymeacoffee.com/johan71gent"><img src="https://img.shields.io/badge/Buy%20me%20a%20coffee-%E2%98%95-FFDD00?style=for-the-badge&logo=buymeacoffee&logoColor=black" alt="Buy Me a Coffee"></a>

## Disclaimer
Unofficial integration, not affiliated with IVAGO. If IVAGO changes its website, the integration may stop working.
