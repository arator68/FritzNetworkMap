from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([NetworkDeviceCountSensor(coordinator, entry)])


class NetworkDeviceCountSensor(CoordinatorEntity, SensorEntity):
    _attr_name = "FRITZ!Box Netzwerkgeräte"
    _attr_icon = "mdi:lan"
    _attr_native_unit_of_measurement = "Geräte"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_device_count"

    @property
    def native_value(self):
        return len(self.coordinator.data or [])

    @property
    def extra_state_attributes(self):
        return {"devices": self.coordinator.data or []}
