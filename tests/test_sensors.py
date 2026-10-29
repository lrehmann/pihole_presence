"""Optional host metrics must not publish invalid values or temperature units."""

import pytest
from homeassistant.const import UnitOfTemperature

from custom_components.pihole_presence.sensor import (
    SENSOR_DESCRIPTIONS,
    PiholeHostSensor,
    _number,
)


@pytest.mark.parametrize(
    "value", [None, True, "15", float("nan"), float("inf"), 10**1000]
)
def test_non_numeric_metrics_are_unknown(value):
    assert _number(value) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unit,ha_unit",
    [
        ("C", UnitOfTemperature.CELSIUS),
        ("F", UnitOfTemperature.FAHRENHEIT),
        ("K", UnitOfTemperature.KELVIN),
    ],
)
async def test_temperature_units(coordinator, unit, ha_unit):
    coordinator.host_metrics = {"sensors": {"unit": unit, "cpu_temp": 45.24}}
    sensor = PiholeHostSensor(
        coordinator, "entry", "http://pi.hole", SENSOR_DESCRIPTIONS[0]
    )
    assert sensor.native_value == 45.2
    assert sensor.native_unit_of_measurement == ha_unit


@pytest.mark.asyncio
async def test_unknown_temperature_unit_does_not_publish_a_guess(coordinator):
    coordinator.host_metrics = {"sensors": {"unit": "unknown", "cpu_temp": 45}}
    sensor = PiholeHostSensor(
        coordinator, "entry", "http://pi.hole", SENSOR_DESCRIPTIONS[0]
    )
    assert sensor.native_value is None
    assert not sensor.available
