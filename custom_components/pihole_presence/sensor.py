from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PiholeUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class PiholeHostSensorEntityDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], int | float | None]
    extra_attributes_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _get(data: dict[str, Any], *path: str) -> Any:
    value: Any = data
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _number(value: Any, precision: int = 2) -> int | float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    rounded = round(float(value), precision)
    if rounded.is_integer():
        return int(rounded)
    return rounded


def _compact(attributes: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in attributes.items() if value is not None}


def _list_item(value: Any, index: int) -> Any:
    if isinstance(value, list) and len(value) > index:
        return value[index]
    return None


def _cpu_value(metrics: dict[str, Any]) -> int | float | None:
    return _number(_get(metrics, "system", "cpu", "%cpu"))


def _cpu_attributes(metrics: dict[str, Any]) -> dict[str, Any]:
    cpu = _get(metrics, "system", "cpu")
    ftl = _get(metrics, "system", "ftl")
    load = cpu.get("load") if isinstance(cpu, dict) else {}
    raw_load = load.get("raw") if isinstance(load, dict) else None
    percent_load = load.get("percent") if isinstance(load, dict) else None
    return _compact(
        {
            "processor_count": cpu.get("nprocs") if isinstance(cpu, dict) else None,
            "load_1m": _number(_list_item(raw_load, 0), 3),
            "load_5m": _number(_list_item(raw_load, 1), 3),
            "load_15m": _number(_list_item(raw_load, 2), 3),
            "load_1m_percent": _number(_list_item(percent_load, 0), 2),
            "load_5m_percent": _number(_list_item(percent_load, 1), 2),
            "load_15m_percent": _number(_list_item(percent_load, 2), 2),
            "ftl_cpu_percent": _number(
                ftl.get("%cpu") if isinstance(ftl, dict) else None
            ),
        }
    )


def _memory_value(metrics: dict[str, Any]) -> int | float | None:
    return _number(_get(metrics, "system", "memory", "ram", "%used"))


def _memory_attributes(metrics: dict[str, Any]) -> dict[str, Any]:
    ram = _get(metrics, "system", "memory", "ram")
    swap = _get(metrics, "system", "memory", "swap")
    ftl = _get(metrics, "system", "ftl")
    return _compact(
        {
            "ram_total_kib": ram.get("total") if isinstance(ram, dict) else None,
            "ram_used_kib": ram.get("used") if isinstance(ram, dict) else None,
            "ram_free_kib": ram.get("free") if isinstance(ram, dict) else None,
            "ram_available_kib": (
                ram.get("available") if isinstance(ram, dict) else None
            ),
            "swap_total_kib": swap.get("total") if isinstance(swap, dict) else None,
            "swap_used_kib": swap.get("used") if isinstance(swap, dict) else None,
            "swap_used_percent": _number(
                swap.get("%used") if isinstance(swap, dict) else None
            ),
            "ftl_memory_percent": _number(
                ftl.get("%mem") if isinstance(ftl, dict) else None
            ),
        }
    )


def _temperature_value(metrics: dict[str, Any]) -> int | float | None:
    return _number(_get(metrics, "sensors", "cpu_temp"), 1)


def _temperature_attributes(metrics: dict[str, Any]) -> dict[str, Any]:
    sensors = _get(metrics, "sensors")
    return _compact(
        {
            "hot_limit": sensors.get("hot_limit") if isinstance(sensors, dict) else None,
            "unit": sensors.get("unit") if isinstance(sensors, dict) else None,
        }
    )


SENSOR_DESCRIPTIONS: tuple[PiholeHostSensorEntityDescription, ...] = (
    PiholeHostSensorEntityDescription(
        key="host_temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
        value_fn=_temperature_value,
        extra_attributes_fn=_temperature_attributes,
    ),
    PiholeHostSensorEntityDescription(
        key="host_cpu_usage",
        name="CPU Usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=_cpu_value,
        extra_attributes_fn=_cpu_attributes,
    ),
    PiholeHostSensorEntityDescription(
        key="host_memory_usage",
        name="Memory Usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=_memory_value,
        extra_attributes_fn=_memory_attributes,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: PiholeUpdateCoordinator = data["coordinator"]
    host: str = data["host"]

    async_add_entities(
        PiholeHostSensor(coordinator, entry.entry_id, host, description)
        for description in SENSOR_DESCRIPTIONS
    )


class PiholeHostSensor(CoordinatorEntity[PiholeUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True

    entity_description: PiholeHostSensorEntityDescription

    def __init__(
        self,
        coordinator: PiholeUpdateCoordinator,
        entry_id: str,
        host: str,
        description: PiholeHostSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry_id = entry_id
        self._host = host
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_entity_registry_enabled_default = (
            description.entity_registry_enabled_default
        )

    @property
    def native_value(self) -> int | float | None:
        return self.entity_description.value_fn(self.coordinator.host_metrics)

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.entity_description.key != "host_temperature":
            return self.entity_description.native_unit_of_measurement

        unit = _get(self.coordinator.host_metrics, "sensors", "unit")
        if unit == "F":
            return UnitOfTemperature.FAHRENHEIT
        if unit == "C":
            return UnitOfTemperature.CELSIUS
        return self.entity_description.native_unit_of_measurement

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.entity_description.extra_attributes_fn is None:
            return {}
        return self.entity_description.extra_attributes_fn(self.coordinator.host_metrics)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name="Pi-hole",
            manufacturer="Pi-hole",
            configuration_url=self._host,
        )
