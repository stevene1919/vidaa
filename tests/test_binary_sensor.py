"""Tests for VIDAA Smart TV binary sensor platform."""

import asyncio
from unittest.mock import MagicMock

from custom_components.vidaa.binary_sensor import (
    HisenseVidaaAuthProblemBinarySensor,
    HisenseVidaaHotelModeBinarySensor,
    HisenseVidaaInUseBinarySensor,
    HisenseVidaaMqttConnectedBinarySensor,
    VidaaAuthProblemBinarySensor,
    VidaaHotelModeBinarySensor,
    VidaaInUseBinarySensor,
    VidaaMqttConnectedBinarySensor,
    async_setup_entry as async_setup_binary_sensors,
)


def test_binary_sensor_backwards_compatibility_aliases():
    """Verify legacy HisenseVidaa* binary sensor classes are aliases for Vidaa* classes."""
    assert HisenseVidaaMqttConnectedBinarySensor is VidaaMqttConnectedBinarySensor
    assert HisenseVidaaInUseBinarySensor is VidaaInUseBinarySensor
    assert HisenseVidaaHotelModeBinarySensor is VidaaHotelModeBinarySensor
    assert HisenseVidaaAuthProblemBinarySensor is VidaaAuthProblemBinarySensor


def test_binary_sensor_entities(mock_client, mock_entry):
    """Test MQTT connected and auth problem binary sensor entities."""
    bs_mqtt = VidaaMqttConnectedBinarySensor(mock_client, mock_entry)
    assert bs_mqtt.is_on is True

    # Test Auth Problem binary sensor
    mock_client.auth_failed = False
    bs_auth = VidaaAuthProblemBinarySensor(mock_client, mock_entry)
    assert bs_auth.is_on is False
    assert bs_auth.unique_id == "test_entry_id_auth_problem"
    assert bs_auth.available is True

    mock_client.auth_failed = True
    assert bs_auth.is_on is True
    # Remains available so user and automations can see the problem status
    assert bs_auth.available is True

    # Test platform setup adds 4 binary sensors
    hass = MagicMock()
    added_sensors = []
    asyncio.run(async_setup_binary_sensors(hass, mock_entry, lambda entities: added_sensors.extend(entities)))
    assert len(added_sensors) == 4


def test_hotel_mode_binary_sensor(mock_client, mock_entry):
    """Test hotel mode binary sensor."""
    mock_client.hotel_mode = False
    sensor_hotel = VidaaHotelModeBinarySensor(mock_client, mock_entry)
    assert sensor_hotel.is_on is False
    assert sensor_hotel.unique_id == f"{mock_entry.entry_id}_hotel_mode"

    mock_client.hotel_mode = True
    assert sensor_hotel.is_on is True


def test_in_use_binary_sensor_dormant_and_hdmi_states(mock_client, mock_entry):
    """Test in_use binary sensor accounts for HDMI display, dormant modes, and power."""
    sensor = VidaaInUseBinarySensor(mock_client, mock_entry)

    # 1. Connected and awake on HDMI (current_app is None): in_use must be True
    mock_client.connected = True
    mock_client.is_on = True
    mock_client.state = "on"
    mock_client.current_app = None
    assert sensor.is_on is True

    # 2. In standby: in_use must be False
    mock_client.is_on = False
    mock_client.state = "off"
    assert sensor.is_on is False

    # 3. TV awake but reporting dormant sleep/standby mode
    mock_client.is_on = True
    mock_client.state = "on"
    mock_client.current_app = "Standby"
    assert sensor.is_on is False

    mock_client.current_app = "sleep"
    assert sensor.is_on is False

    # 4. TV awake running an app
    mock_client.current_app = "Netflix"
    assert sensor.is_on is True
