"""Connecting to the cuff through Home Assistant's Bluetooth stack."""

from __future__ import annotations

import asyncio
import logging

from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .kn550bt.session import KN550BTSession
from .kn550bt.variants import Variant

_LOGGER = logging.getLogger(__name__)

MODEL = "KN-550BT"

# The cuff advertises while it is measuring but only accepts a connection once the
# measurement is done; give up quickly and retry on its next packet instead.
CONNECT_TIMEOUT_S = 10


async def async_connect(ble_device: BLEDevice, name: str) -> BleakClientWithServiceCache:
    async with asyncio.timeout(CONNECT_TIMEOUT_S):
        return await establish_connection(
            BleakClientWithServiceCache, ble_device, name, max_attempts=2
        )


async def async_read_model(ble_device: BLEDevice, variant: Variant) -> str | None:
    """Read the model string while the cuff is awake; None if it cannot be read."""
    try:
        async with asyncio.timeout(10):
            client = await async_connect(ble_device, ble_device.name or ble_device.address)
            try:
                info = await KN550BTSession(client, variant).read_device_info()
            finally:
                await client.disconnect()
    except Exception as err:  # noqa: BLE001 - any failure just means "unknown"
        _LOGGER.debug("Could not read model from %s: %s", ble_device.address, err)
        return None
    return info.model or None
