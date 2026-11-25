"""二元传感器：今天 / 明天是否工作日。"""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ENTITY_TODAY, ENTITY_TOMORROW
from .coordinator import MergedCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    coordinator: MergedCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([TodaySensor(coordinator, entry),
                        TomorrowSensor(coordinator, entry)])


class Base(CoordinatorEntity[MergedCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: MergedCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="workday_maintenance", manufacturer="自建", model="工作日 + 维护台账",
        )

    @property
    def wd(self) -> dict:
        return (self.coordinator.data or {}).get("workday", {})


class TodaySensor(Base):
    _attr_name = "今天是否工作日"
    _attr_icon = "mdi:briefcase-check"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = ENTITY_TODAY
        self._attr_unique_id = f"{entry.entry_id}_today"

    @property
    def is_on(self):
        return bool(self.wd.get("today_work"))

    @property
    def extra_state_attributes(self):
        return {"date": (self.coordinator.data or {}).get("today"),
                "label": self.wd.get("today_label")}


class TomorrowSensor(Base):
    _attr_name = "明天是否工作日"
    _attr_icon = "mdi:briefcase-clock"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self.entity_id = ENTITY_TOMORROW
        self._attr_unique_id = f"{entry.entry_id}_tomorrow"

    @property
    def is_on(self):
        return bool(self.wd.get("tomorrow_work"))


