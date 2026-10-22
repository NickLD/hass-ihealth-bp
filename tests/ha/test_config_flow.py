"""Discovery, manual setup and options."""

import json
from pathlib import Path
from unittest.mock import patch

from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ihealth_bp.const import (
    CONF_DELETE_AFTER_IMPORT,
    CONF_REVIEW_MODE,
    DOMAIN,
)
from custom_components.ihealth_bp.rejected import DATA_REJECTED, STORAGE_KEY

from .conftest import ADDRESS
from .helpers import AV21_UUID, make_service_info

READ_MODEL = "custom_components.ihealth_bp.config_flow.async_read_model"
DISCOVERED = "custom_components.ihealth_bp.config_flow.async_discovered_service_info"


STRINGS = Path(__file__).parents[2] / "custom_components" / "ihealth_bp" / "strings.json"


async def discover(hass, info, model):
    return (await discover_counting(hass, info, model))[0]


async def discover_counting(hass, info, model):
    """Discover, also returning the async_read_model mock to check whether it connected."""
    with patch(READ_MODEL, return_value=model) as read_model:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=info
        )
    return result, read_model


async def test_bluetooth_discovery_creates_entry(hass):
    result = await discover(hass, make_service_info(), "KN-550BT")
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "KN-550BT"
    assert result["data"] == {"address": ADDRESS, "variant": "com.jiuan.dev"}
    assert result["result"].unique_id == ADDRESS
    assert result["options"] == {CONF_DELETE_AFTER_IMPORT: True, CONF_REVIEW_MODE: False}


async def test_bluetooth_discovery_aborts_for_other_model(hass):
    result = await discover(hass, make_service_info(), "BG5S")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_supported"


async def test_other_model_is_not_connected_to_again(hass):
    await discover(hass, make_service_info(), "BG5S")
    result, read_model = await discover_counting(hass, make_service_info(), "KN-550BT")
    assert result["reason"] == "not_supported"
    read_model.assert_not_called()


async def test_rejection_survives_restart(hass, hass_storage):
    await discover(hass, make_service_info(), "BG5S")
    await hass.async_block_till_done()
    assert hass_storage[STORAGE_KEY]["data"] == {"addresses": [ADDRESS]}
    hass.data.pop(DATA_REJECTED)
    result, read_model = await discover_counting(hass, make_service_info(), "KN-550BT")
    assert result["reason"] == "not_supported"
    read_model.assert_not_called()


async def test_unreadable_model_still_offers_setup(hass):
    result = await discover(hass, make_service_info(), None)
    assert result["step_id"] == "bluetooth_confirm"
    hass.config_entries.flow.async_abort(result["flow_id"])
    result, read_model = await discover_counting(hass, make_service_info(), "KN-550BT")
    assert result["step_id"] == "bluetooth_confirm"
    read_model.assert_called_once()


async def test_legacy_variant_is_flagged_untested(hass):
    result = await discover(hass, make_service_info(uuids=[AV21_UUID]), None)
    assert result["step_id"] == "bluetooth_confirm_untested"
    assert result["description_placeholders"]["variant"] == "com.jiuan.BPAV21"
    step = json.loads(STRINGS.read_text(encoding="utf-8"))["config"]["step"][result["step_id"]]
    assert "{variant}" in step["description"] and "untested" in step["description"].lower()
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["data"]["variant"] == "com.jiuan.BPAV21"


async def test_unrelated_advertisement_aborts(hass):
    result = await discover(hass, make_service_info(uuids=["0000180a-0000-1000-8000-00805f9b34fb"]), None)
    assert result["reason"] == "not_supported"


async def test_already_configured(hass):
    MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS, data={"address": ADDRESS}).add_to_hass(hass)
    result = await discover(hass, make_service_info(), "KN-550BT")
    assert result["reason"] == "already_configured"


async def test_user_step_lists_discovered(hass):
    with patch(DISCOVERED, return_value=[make_service_info()]):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        assert result["step_id"] == "user"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"address": ADDRESS})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["address"] == ADDRESS


async def test_user_step_without_devices_aborts(hass):
    with patch(DISCOVERED, return_value=[]):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["reason"] == "no_devices_found"


async def test_options_defaults_and_update(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=ADDRESS,
        data={"address": ADDRESS, "variant": "com.jiuan.dev"},
        options={CONF_DELETE_AFTER_IMPORT: True, CONF_REVIEW_MODE: False},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_DELETE_AFTER_IMPORT: False, CONF_REVIEW_MODE: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_DELETE_AFTER_IMPORT: False, CONF_REVIEW_MODE: True}
