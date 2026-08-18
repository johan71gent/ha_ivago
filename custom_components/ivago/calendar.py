"""Calendar entity for the IVAGO integration."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import Pickup
from .const import BASE_URL
from .coordinator import IvagoConfigEntry, IvagoCoordinator
from .entity import IvagoEntity
from .sensor import waste_type_name


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IvagoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the IVAGO calendar."""
    async_add_entities([IvagoCalendar(entry.runtime_data)])


def _to_event(pickup: Pickup) -> CalendarEvent:
    """Convert a pickup to an all-day calendar event."""
    return CalendarEvent(
        start=pickup.date,
        end=pickup.date + timedelta(days=1),
        summary=waste_type_name(pickup.waste_type),
        description=f"IVAGO ophaling {waste_type_name(pickup.waste_type)}"
        + (f"\n{BASE_URL}{pickup.url}" if pickup.url else ""),
        uid=f"ivago-{pickup.date.isoformat()}-{pickup.waste_type.lower()}",
    )


class IvagoCalendar(IvagoEntity, CalendarEntity):
    """All IVAGO pickups as an all-day calendar."""

    _attr_translation_key = "calendar"
    _attr_icon = "mdi:calendar"

    def __init__(self, coordinator: IvagoCoordinator) -> None:
        """Initialise."""
        super().__init__(coordinator, "calendar")

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming event (today or later)."""
        data = self.coordinator.data
        today = dt_util.now().date()
        for pickup in data.pickups:
            if pickup.date >= today:
                return _to_event(pickup)
        return None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""
        start = dt_util.as_local(start_date).date()
        end = dt_util.as_local(end_date).date()
        return [
            _to_event(p)
            for p in self.coordinator.data.pickups
            if start <= p.date <= end
        ]
