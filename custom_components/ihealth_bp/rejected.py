"""Remember iHealth devices that turned out not to be a KN-550BT.

Other iHealth products (e.g. the BG5S glucose meter) advertise the same service, and Home
Assistant re-runs discovery whenever a device comes back. Connecting to read the model each
time could block the iHealth app's own connection, so a definitive "not a KN-550BT" is kept
across restarts and later discoveries of that address are dropped without connecting.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.singleton import singleton
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_KEY = f"{DOMAIN}.rejected"
STORAGE_VERSION = 1
DATA_REJECTED = f"{DOMAIN}_rejected"


class RejectedDevices:
    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, list[str]]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._addresses: set[str] = set()

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self._addresses = set(data.get("addresses", []))

    def __contains__(self, address: str) -> bool:
        return address in self._addresses

    async def async_add(self, address: str) -> None:
        if address not in self._addresses:
            self._addresses.add(address)
            await self._store.async_save({"addresses": sorted(self._addresses)})


@singleton(DATA_REJECTED)
async def async_get_rejected(hass: HomeAssistant) -> RejectedDevices:
    """The rejected addresses, loaded on first use and cached in hass.data."""
    rejected = RejectedDevices(hass)
    await rejected.async_load()
    return rejected
