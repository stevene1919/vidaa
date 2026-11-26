"""Unit tests verifying options flow and entity behavior across multiple configured TVs."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant

from custom_components.vidaa import update_listener
from custom_components.vidaa.artwork import ArtworkReachabilityTracker
from custom_components.vidaa.const import (
    CONF_ENABLE_APP_ICONS,
    CONF_ENABLE_CEC_NAMES,
    CONF_ENABLE_MEDIA_CONTROLS,
    CONF_ENABLE_WOL,
    CONF_INCLUDE_APPS_IN_SOURCES,
    CONF_IP_ADDRESS,
    CONF_KEY_DELAY,
    CONF_KEY_REPEAT,
    CONF_MAC_ADDRESS,
    CONF_PLAYBACK_DEBOUNCE,
    CONF_SECONDARY_MAC_ADDRESS,
    CONF_SOURCES,
    DEFAULT_ENABLE_APP_ICONS,
)
from custom_components.vidaa.flow import VidaaOptionsFlowHandler
from custom_components.vidaa.media_player import VidaaMediaPlayer
from custom_components.vidaa.sensor import VidaaActiveAppSensor


def _create_mock_tv_entry(
    entry_id: str,
    title: str,
    ip: str,
    mac: str,
    sec_mac: str,
    apps: dict[str, dict[str, str]],
    sources: dict[str, dict[str, str]],
    options: dict | None = None,
) -> tuple[ConfigEntry, MagicMock]:
    """Helper creating a ConfigEntry and client for a mocked TV."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = entry_id
    entry.title = title
    entry.data = {
        CONF_IP_ADDRESS: ip,
        CONF_MAC_ADDRESS: mac,
        CONF_SECONDARY_MAC_ADDRESS: sec_mac,
    }
    entry.options = dict(options or {})

    client = MagicMock()
    client.ip = ip
    client.mac = mac
    client.mac_wifi = mac
    client.mac_ethernet = sec_mac
    client.app_dict = apps
    client.source_dict = sources
    client.connected = True
    client.is_on = True

    tracker = ArtworkReachabilityTracker(enabled=entry.options.get(CONF_ENABLE_APP_ICONS, DEFAULT_ENABLE_APP_ICONS))

    entry.runtime_data = SimpleNamespace(
        client=client,
        options=entry.options,
        artwork_tracker=tracker,
    )
    return entry, client


@pytest.mark.anyio
async def test_multi_tv_options_flow_source_and_mac_isolation():
    """Verify options flow presents isolated MAC addresses and discovered sources for each TV."""
    # TV 1: Living Room TV with Netflix & YouTube
    tv1_apps = {
        "Netflix": {"appId": "1", "httpIcon": "https://img.vidaahub.com/nf.png"},
        "YouTube": {"appId": "2", "httpIcon": "https://img.vidaahub.com/yt.png"},
    }
    tv1_sources = {
        "HDMI1": {"sourcename": "HDMI1"},
        "HDMI2": {"sourcename": "HDMI2"},
    }
    entry_tv1, _ = _create_mock_tv_entry(
        entry_id="tv1_entry",
        title="Living Room TV",
        ip="192.168.1.101",
        mac="aa:bb:cc:11:22:33",
        sec_mac="aa:bb:cc:11:22:34",
        apps=tv1_apps,
        sources=tv1_sources,
    )

    # TV 2: Bedroom TV with Disney+ & Stan
    tv2_apps = {
        "Disney+": {"appId": "3", "httpIcon": "https://img.vidaahub.com/disney.png"},
        "Stan": {"appId": "4", "httpIcon": "https://img.vidaahub.com/stan.png"},
    }
    tv2_sources = {
        "HDMI1": {"sourcename": "HDMI1"},
        "AV": {"sourcename": "AV"},
    }
    entry_tv2, _ = _create_mock_tv_entry(
        entry_id="tv2_entry",
        title="Bedroom TV",
        ip="192.168.1.102",
        mac="dd:ee:ff:44:55:66",
        sec_mac="dd:ee:ff:44:55:67",
        apps=tv2_apps,
        sources=tv2_sources,
    )

    flow_tv1 = VidaaOptionsFlowHandler(entry_tv1)
    flow_tv2 = VidaaOptionsFlowHandler(entry_tv2)

    # 1. Power & Network step displays TV-specific MAC placeholders and defaults
    pwr_tv1 = await flow_tv1.async_step_power_network()
    pwr_tv2 = await flow_tv2.async_step_power_network()

    assert pwr_tv1["description_placeholders"]["primary_mac"] == "aa:bb:cc:11:22:33"
    assert pwr_tv2["description_placeholders"]["primary_mac"] == "dd:ee:ff:44:55:66"

    sec_mac_field_tv1 = next(k for k in pwr_tv1["data_schema"].schema if str(k) == CONF_SECONDARY_MAC_ADDRESS)
    sec_mac_field_tv2 = next(k for k in pwr_tv2["data_schema"].schema if str(k) == CONF_SECONDARY_MAC_ADDRESS)
    assert sec_mac_field_tv1.default() == "aa:bb:cc:11:22:34"
    assert sec_mac_field_tv2.default() == "dd:ee:ff:44:55:67"

    # 2. Playback & Sources step presents TV-specific discovered sources
    src_tv1 = await flow_tv1.async_step_playback_sources()
    src_tv2 = await flow_tv2.async_step_playback_sources()

    schema_tv1 = src_tv1["data_schema"].schema
    schema_tv2 = src_tv2["data_schema"].schema

    sources_selector_tv1 = next(schema_tv1[k] for k in schema_tv1 if str(k) == CONF_SOURCES)
    sources_selector_tv2 = next(schema_tv2[k] for k in schema_tv2 if str(k) == CONF_SOURCES)

    def _get_options(sel):
        cfg = getattr(sel, "config", sel)
        if hasattr(cfg, "config") and isinstance(cfg.config, dict):
            return cfg.config.get("options", [])
        if isinstance(cfg, dict):
            return cfg.get("options", [])
        return getattr(cfg, "options", [])

    options_tv1 = _get_options(sources_selector_tv1)
    options_tv2 = _get_options(sources_selector_tv2)

    # TV 1 has Netflix & YouTube, but not Disney+ or Stan
    assert "Netflix" in options_tv1
    assert "YouTube" in options_tv1
    assert "HDMI2" in options_tv1
    assert "Disney+" not in options_tv1
    assert "Stan" not in options_tv1

    # TV 2 has Disney+ & Stan, but not Netflix or YouTube
    assert "Disney+" in options_tv2
    assert "Stan" in options_tv2
    assert "AV" in options_tv2
    assert "Netflix" not in options_tv2
    assert "YouTube" not in options_tv2


@pytest.mark.anyio
async def test_multi_tv_options_submission_isolation():
    """Submitting option updates on one TV does not mutate or leak options into other TVs."""
    entry_tv1, _ = _create_mock_tv_entry(
        entry_id="tv1_entry",
        title="Living Room TV",
        ip="192.168.1.101",
        mac="aa:bb:cc:11:22:33",
        sec_mac="aa:bb:cc:11:22:34",
        apps={"Netflix": {}},
        sources={"HDMI1": {}},
        options={
            CONF_ENABLE_WOL: True,
            CONF_ENABLE_APP_ICONS: True,
            CONF_KEY_DELAY: 0.2,
            CONF_KEY_REPEAT: 1,
        },
    )
    entry_tv2, _ = _create_mock_tv_entry(
        entry_id="tv2_entry",
        title="Bedroom TV",
        ip="192.168.1.102",
        mac="dd:ee:ff:44:55:66",
        sec_mac="dd:ee:ff:44:55:67",
        apps={"Disney+": {}},
        sources={"HDMI1": {}},
        options={
            CONF_ENABLE_WOL: True,
            CONF_ENABLE_APP_ICONS: True,
            CONF_KEY_DELAY: 0.2,
            CONF_KEY_REPEAT: 1,
        },
    )

    flow_tv1 = VidaaOptionsFlowHandler(entry_tv1)

    # Update TV 1's options to disable WoL, disable artwork CDN, and customize key repeat
    res_pwr = await flow_tv1.async_step_power_network(
        user_input={
            CONF_ENABLE_WOL: False,
            CONF_SECONDARY_MAC_ADDRESS: "aa:bb:cc:11:22:99",
        }
    )
    entry_tv1.options.update(res_pwr["data"])

    res_src = await flow_tv1.async_step_playback_sources(
        user_input={
            CONF_INCLUDE_APPS_IN_SOURCES: False,
            CONF_ENABLE_MEDIA_CONTROLS: True,
            CONF_ENABLE_CEC_NAMES: True,
            CONF_ENABLE_APP_ICONS: False,
            CONF_PLAYBACK_DEBOUNCE: 1.0,
        }
    )
    entry_tv1.options.update(res_src["data"])

    res_feat = await flow_tv1.async_step_features_remote(
        user_input={
            CONF_KEY_DELAY: 0.5,
            CONF_KEY_REPEAT: 3,
        }
    )
    entry_tv1.options.update(res_feat["data"])

    # Verify TV 1 received the updated options
    assert entry_tv1.options[CONF_ENABLE_WOL] is False
    assert entry_tv1.options[CONF_SECONDARY_MAC_ADDRESS] == "aa:bb:cc:11:22:99"
    assert entry_tv1.options[CONF_ENABLE_APP_ICONS] is False
    assert entry_tv1.options[CONF_INCLUDE_APPS_IN_SOURCES] is False
    assert entry_tv1.options[CONF_ENABLE_CEC_NAMES] is True
    assert entry_tv1.options[CONF_KEY_DELAY] == 0.5
    assert entry_tv1.options[CONF_KEY_REPEAT] == 3

    # Verify TV 2 options remained strictly untouched
    assert entry_tv2.options[CONF_ENABLE_WOL] is True
    assert entry_tv2.options[CONF_ENABLE_APP_ICONS] is True
    assert entry_tv2.options[CONF_KEY_DELAY] == 0.2
    assert entry_tv2.options[CONF_KEY_REPEAT] == 1
    assert CONF_SECONDARY_MAC_ADDRESS not in entry_tv2.options


@pytest.mark.anyio
async def test_multi_tv_entities_respect_individual_options_simultaneously():
    """Multiple TV entities simultaneously reflect their respective individual config options."""
    app_info = {
        "name": "Netflix",
        "appId": "1",
        "httpIcon": "iconDownloadhttps://img.vidaahub.com/nf.png",
    }

    # TV 1: Offline/privacy mode (enable_app_icons=False, include_apps_in_sources=False)
    entry_tv1, client_tv1 = _create_mock_tv_entry(
        entry_id="tv1_entry",
        title="Living Room TV",
        ip="192.168.1.101",
        mac="aa:bb:cc:11:22:33",
        sec_mac="",
        apps={"Netflix": app_info},
        sources={"HDMI1": {"sourcename": "HDMI1"}},
        options={
            CONF_ENABLE_APP_ICONS: False,
            CONF_INCLUDE_APPS_IN_SOURCES: False,
        },
    )

    # TV 2: Full online mode (enable_app_icons=True, include_apps_in_sources=True)
    entry_tv2, client_tv2 = _create_mock_tv_entry(
        entry_id="tv2_entry",
        title="Bedroom TV",
        ip="192.168.1.102",
        mac="dd:ee:ff:44:55:66",
        sec_mac="",
        apps={"Netflix": app_info},
        sources={"HDMI1": {"sourcename": "HDMI1"}},
        options={
            CONF_ENABLE_APP_ICONS: True,
            CONF_INCLUDE_APPS_IN_SOURCES: True,
        },
    )

    # Both TVs are running Netflix
    client_tv1.current_app = "Netflix"
    client_tv1.current_app_id = "1"
    client_tv1.apps = [app_info]

    client_tv2.current_app = "Netflix"
    client_tv2.current_app_id = "1"
    client_tv2.apps = [app_info]

    sensor_tv1 = VidaaActiveAppSensor(client_tv1, entry_tv1)
    sensor_tv2 = VidaaActiveAppSensor(client_tv2, entry_tv2)

    mp_tv1 = VidaaMediaPlayer(client=client_tv1, entry=entry_tv1)
    mp_tv1._source = "Netflix"
    mp_tv1._app_dict = {"Netflix": app_info}
    mp_tv1._source_dict = {"HDMI1": {"sourcename": "HDMI1"}}
    mp_tv1._state = STATE_ON

    mp_tv2 = VidaaMediaPlayer(client=client_tv2, entry=entry_tv2)
    mp_tv2._source = "Netflix"
    mp_tv2._app_dict = {"Netflix": app_info}
    mp_tv2._source_dict = {"HDMI1": {"sourcename": "HDMI1"}}
    mp_tv2._state = STATE_ON

    # TV 1 suppresses artwork and app sources per its options
    assert sensor_tv1.entity_picture is None
    assert sensor_tv1.icon == "mdi:netflix"
    assert mp_tv1.media_image_url is None
    assert mp_tv1.icon == "mdi:netflix"
    assert mp_tv1.source_list == ["HDMI1"]  # include_apps_in_sources is False

    # TV 2 displays CDN artwork and includes apps in source list per its options
    assert sensor_tv2.entity_picture == "https://img.vidaahub.com/nf.png"
    assert mp_tv2.media_image_url == "https://img.vidaahub.com/nf.png"
    assert "Netflix" in mp_tv2.source_list  # include_apps_in_sources is True
    assert "HDMI1" in mp_tv2.source_list


@pytest.mark.anyio
async def test_multi_tv_update_listener_reloads_only_target_entry():
    """Updating options on TV 1 triggers async_reload strictly for TV 1, not TV 2."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries = MagicMock()
    hass.config_entries.async_reload = AsyncMock()

    entry_tv1 = MagicMock(spec=ConfigEntry)
    entry_tv1.entry_id = "tv1_entry_id"
    entry_tv1.options = {CONF_ENABLE_WOL: True}
    entry_tv1.runtime_data = SimpleNamespace(options={CONF_ENABLE_WOL: True})

    entry_tv2 = MagicMock(spec=ConfigEntry)
    entry_tv2.entry_id = "tv2_entry_id"
    entry_tv2.options = {CONF_ENABLE_WOL: True}
    entry_tv2.runtime_data = SimpleNamespace(options={CONF_ENABLE_WOL: True})

    # 1. TV 1 options unchanged -> no reload
    await update_listener(hass, entry_tv1)
    hass.config_entries.async_reload.assert_not_called()

    # 2. TV 1 options updated -> reloads TV 1 only
    entry_tv1.options = {CONF_ENABLE_WOL: False}
    await update_listener(hass, entry_tv1)
    hass.config_entries.async_reload.assert_awaited_once_with("tv1_entry_id")

    hass.config_entries.async_reload.reset_mock()

    # 3. TV 2 options updated -> reloads TV 2 only
    entry_tv2.options = {CONF_ENABLE_APP_ICONS: False}
    await update_listener(hass, entry_tv2)
    hass.config_entries.async_reload.assert_awaited_once_with("tv2_entry_id")
