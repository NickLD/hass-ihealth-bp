"""Build Bluetooth advertisements for tests."""

from __future__ import annotations

import time

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

from .conftest import ADDRESS

DEV_UUID = "636f6d2e-6a69-7561-6e2e-646576000000"
AV21_UUID = "636f6d2e-6a69-7561-6e2e-425041563231"


def make_service_info(
    address: str = ADDRESS,
    uuids: list[str] | None = None,
    name: str | None = None,
    rssi: int = -60,
) -> BluetoothServiceInfoBleak:
    uuids = [DEV_UUID] if uuids is None else uuids
    adv = AdvertisementData(
        local_name=name, manufacturer_data={}, service_data={}, service_uuids=uuids,
        tx_power=-127, rssi=rssi, platform_data=(),
    )
    return BluetoothServiceInfoBleak(
        name=name or address, address=address, rssi=rssi, manufacturer_data={},
        service_data={}, service_uuids=uuids, source="local",
        device=BLEDevice(address, name, {}), advertisement=adv, connectable=True,
        time=time.monotonic(), tx_power=-127,
    )


async def async_setup_cuff(
    hass, *, delete=True, review=False, variant="com.jiuan.dev", routine=True
):
    """Set up a config entry for the test cuff; returns (entry, coordinator)."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.ihealth_bp.const import (
        CONF_DELETE_AFTER_IMPORT,
        CONF_MEASUREMENT_ROUTINE,
        CONF_REVIEW_MODE,
        DOMAIN,
    )

    await hass.config.async_set_time_zone("America/Chicago")
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=ADDRESS, title="KN-550BT",
        data={"address": ADDRESS, "variant": variant},
        options={
            CONF_DELETE_AFTER_IMPORT: delete,
            CONF_REVIEW_MODE: review,
            CONF_MEASUREMENT_ROUTINE: routine,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, entry.runtime_data


_wake = 0


async def async_sync(hass, coordinator, cuff) -> None:
    """Run one sync against a FakeCuff, as a separate wake a minute after the last one."""
    from unittest.mock import patch

    global _wake
    _wake += 1
    info = make_service_info()
    info.time += 60 * _wake
    with patch("custom_components.ihealth_bp.coordinator.async_connect", return_value=cuff):
        await coordinator.async_sync(info)
    await hass.async_block_till_done()
