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
