"""Sensors for the IVAGO integration."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import Pickup
from .const import DEFAULT_ICON, DOMAIN, WASTE_TYPES, WEEKDAYS_NL
from .coordinator import IvagoConfigEntry, IvagoCoordinator, IvagoData
from .entity import IvagoEntity

MAX_UPCOMING = 5


def waste_type_name(waste_type: str) -> str:
    """Human readable name for a waste type label."""
    info = WASTE_TYPES.get(waste_type)
    return info["name"] if info else waste_type.capitalize()


def waste_type_icon(waste_type: str) -> str:
    """Icon for a waste type label."""
    info = WASTE_TYPES.get(waste_type)
    return info["icon"] if info else DEFAULT_ICON


def _names(pickups: list[Pickup]) -> list[str]:
    return [waste_type_name(p.waste_type) for p in pickups]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IvagoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up IVAGO sensors."""
    coordinator = entry.runtime_data

    # Clean up entities from older versions.
    ent_reg = er.async_get(hass)
    for old_key in ("upcoming",):
        if entity_id := ent_reg.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{old_key}"
        ):
            ent_reg.async_remove(entity_id)

    entities: list[SensorEntity] = [
        IvagoNextPickupSensor(coordinator),
        IvagoNextPickupDateSensor(coordinator),
        IvagoDaysUntilSensor(coordinator),
        IvagoDaySensor(coordinator, "today", 0),
        IvagoDaySensor(coordinator, "tomorrow", 1),
    ]

    known: set[str] = set()

    @callback
    def _add_waste_type_sensors() -> None:
        """Create a sensor per waste type (known list + whatever the API returns)."""
        types = set(WASTE_TYPES) | coordinator.data.waste_types
        new = sorted(types - known)
        if not new:
            return
        known.update(new)
        async_add_entities(IvagoWasteTypeSensor(coordinator, t) for t in new)

    async_add_entities(entities)
    _add_waste_type_sensors()
    entry.async_on_unload(coordinator.async_add_listener(_add_waste_type_sensors))


class IvagoWasteTypeSensor(IvagoEntity, SensorEntity):
    """Next pickup date for one waste type."""

    _attr_device_class = SensorDeviceClass.DATE

    def __init__(self, coordinator: IvagoCoordinator, waste_type: str) -> None:
        """Initialise."""
        super().__init__(coordinator, f"type_{waste_type.lower()}")
        self._waste_type = waste_type
        self._attr_name = waste_type_name(waste_type)
        self._attr_icon = waste_type_icon(waste_type)

    @property
    def _data(self) -> IvagoData:
        return self.coordinator.data

    @property
    def native_value(self) -> date | None:
        """Next pickup date."""
        pickup = self._data.next_pickup_for(self._waste_type)
        return pickup.date if pickup else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Extra attributes."""
        today = self._data.today()
        upcoming = [
            p.date
            for p in self._data.pickups
            if p.waste_type == self._waste_type and p.date >= today
        ]
        nxt = upcoming[0] if upcoming else None
        return {
            "waste_type": self._waste_type,
            "days_until": (nxt - today).days if nxt else None,
            "is_today": nxt == today if nxt else False,
            "is_tomorrow": nxt == today + timedelta(days=1) if nxt else False,
            "upcoming": [d.isoformat() for d in upcoming[:MAX_UPCOMING]],
        }


def _next_pickup_attributes(data: IvagoData) -> dict[str, Any]:
    """Shared attributes describing the next collection day."""
    today = data.today()
    pickups = data.next_pickups()
    names = _names(pickups)
    nxt = pickups[0].date if pickups else None
    return {
        "date": nxt.isoformat() if nxt else None,
        "weekday": WEEKDAYS_NL[nxt.weekday()] if nxt else None,
        "days_until": (nxt - today).days if nxt else None,
        "waste_types": [p.waste_type for p in pickups],
        "waste_types_names": names,
        "waste_types_text": ", ".join(names) if names else None,
    }


class IvagoNextPickupSensor(IvagoEntity, SensorEntity):
    """Text: when is the next collection and what is collected.

    State: ``Vandaag: PMD, Restafval`` / ``Morgen: GFT`` /
    ``Over 6 dagen: GFT, PMD, Restafval`` / ``Geen ophaling gepland``.
    """

    _attr_translation_key = "next_pickup"
    _attr_icon = "mdi:truck-fast"

    def __init__(self, coordinator: IvagoCoordinator) -> None:
        """Initialise."""
        super().__init__(coordinator, "next_pickup")

    @property
    def native_value(self) -> str:
        """Human readable summary."""
        data = self.coordinator.data
        pickups = data.next_pickups()
        if not pickups:
            return "Geen ophaling gepland"
        days = (pickups[0].date - data.today()).days
        types = ", ".join(_names(pickups))
        if days == 0:
            return f"Vandaag: {types}"
        if days == 1:
            return f"Morgen: {types}"
        return f"Over {days} dagen: {types}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Extra attributes."""
        return _next_pickup_attributes(self.coordinator.data)


class IvagoNextPickupDateSensor(IvagoEntity, SensorEntity):
    """Date of the next collection day, with the waste types as attributes."""

    _attr_device_class = SensorDeviceClass.DATE
    _attr_translation_key = "next_pickup_date"
    _attr_icon = "mdi:calendar-arrow-right"

    def __init__(self, coordinator: IvagoCoordinator) -> None:
        """Initialise."""
        super().__init__(coordinator, "next_pickup_date")

    @property
    def native_value(self) -> date | None:
        """Next collection date."""
        pickups = self.coordinator.data.next_pickups()
        return pickups[0].date if pickups else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Extra attributes."""
        return _next_pickup_attributes(self.coordinator.data)


class IvagoDaysUntilSensor(IvagoEntity, SensorEntity):
    """Number of days until the next collection day."""

    _attr_translation_key = "days_until_next_pickup"
    _attr_icon = "mdi:calendar-clock"
    _attr_native_unit_of_measurement = "d"

    def __init__(self, coordinator: IvagoCoordinator) -> None:
        """Initialise."""
        super().__init__(coordinator, "days_until_next_pickup")

    @property
    def native_value(self) -> int | None:
        """Days until the next pickup (0 = today)."""
        data = self.coordinator.data
        pickups = data.next_pickups()
        return (pickups[0].date - data.today()).days if pickups else None


class IvagoDaySensor(IvagoEntity, SensorEntity):
    """What is collected today / tomorrow (text)."""

    _attr_icon = "mdi:calendar-today"

    def __init__(self, coordinator: IvagoCoordinator, key: str, offset: int) -> None:
        """Initialise."""
        super().__init__(coordinator, key)
        self._attr_translation_key = key
        self._offset = offset

    def _pickups(self) -> list[Pickup]:
        data = self.coordinator.data
        return data.pickups_on(data.today() + timedelta(days=self._offset))

    @property
    def native_value(self) -> str:
        """Comma separated waste types, or 'Geen'."""
        names = _names(self._pickups())
        return ", ".join(names) if names else "Geen"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Extra attributes."""
        pickups = self._pickups()
        return {
            "date": (
                self.coordinator.data.today() + timedelta(days=self._offset)
            ).isoformat(),
            "waste_types": [p.waste_type for p in pickups],
            "waste_types_names": _names(pickups),
            "has_pickup": bool(pickups),
        }

