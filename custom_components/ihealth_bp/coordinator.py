"""Runs one session each time the cuff wakes up and advertises."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import datetime

from homeassistant.components.bluetooth import (
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_register_advertisement_callback,
)
from homeassistant.components.bluetooth.active_update_coordinator import (
    ActiveBluetoothDataUpdateCoordinator,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import CALLBACK_TYPE, CoreState, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from .connection import MODEL, async_connect
from .const import (
    CONF_DELETE_AFTER_IMPORT,
    CONF_REVIEW_MODE,
    CONF_VARIANT,
    DOMAIN,
    EVENT_MEASUREMENT,
    POLL_INTERVAL_S,
)
from .kn550bt.session import (
    Capabilities,
    DeviceInfo,
    DisplaySettings,
    KN550BTSession,
    SessionError,
)
from .kn550bt.variants import Variant
from .statistics import async_update_statistics
from .storage import CuffStore, LoggedReading, ReadingStatus

_LOGGER = logging.getLogger(__name__)


@dataclass
class CuffState:
    info: DeviceInfo | None = None
    battery: int | None = None
    display: DisplaySettings | None = None
    capabilities: Capabilities | None = None
    last_sync: datetime | None = None
    last_failure: datetime | None = None
    failure_stage: str | None = None
    failure_reason: str | None = None
    rssi: int | None = None


class IHealthBPCoordinator(ActiveBluetoothDataUpdateCoordinator[None]):
    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, store: CuffStore, device_id: str
    ) -> None:
        self.entry = entry
        self.store = store
        self.device_id = device_id
        self.address: str = entry.data[CONF_ADDRESS]
        self.variant = Variant(entry.data.get(CONF_VARIANT, Variant.DEV.value))
        self.state = CuffState()
        self._session_lock = asyncio.Lock()
        self._closed = False
        self._last_session_adv_time: float | None = None
        super().__init__(
            hass,
            _LOGGER,
            address=self.address,
            mode=BluetoothScanningMode.ACTIVE,
            needs_poll_method=self.needs_poll_for,
            poll_method=self.async_sync,
            connectable=True,
        )

    @property
    def delete_after_import(self) -> bool:
        return self.entry.options.get(CONF_DELETE_AFTER_IMPORT, True)

    @property
    def review_mode(self) -> bool:
        return self.entry.options.get(CONF_REVIEW_MODE, False)

    def needs_poll_for(
        self, service_info: BluetoothServiceInfoBleak, seconds_since_last_poll: float | None
    ) -> bool:
        """Connect once per wake: the cuff only advertises for ~10 s after waking."""
        return self.hass.state is CoreState.running and (
            seconds_since_last_poll is None or seconds_since_last_poll > POLL_INTERVAL_S
        )

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        """Also listen to every packet: HA suppresses repeats of an unchanged
        advertisement, and every wake of the cuff advertises exactly the same data."""
        cancel_changes = super().async_start()
        cancel_packets = async_register_advertisement_callback(
            self.hass, self._async_on_packet, self.address
        )

        @callback
        def _cancel() -> None:
            cancel_changes()
            cancel_packets()

        return _cancel

    @callback
    def _async_on_packet(self, service_info: BluetoothServiceInfoBleak) -> None:
        if service_info.connectable:
            self._async_handle_bluetooth_event(service_info, BluetoothChange.ADVERTISEMENT)

    async def async_close(self) -> None:
        """Stop new sessions and wait for a running one, so a reload never races it."""
        self._closed = True
        async with self._session_lock:
            pass

    async def async_sync(self, service_info: BluetoothServiceInfoBleak) -> None:
        """One complete session. Never raises: failures are recorded for diagnostics."""
        async with self._session_lock:
            if self._closed:
                return
            last = self._last_session_adv_time
            if last is not None and 0 <= service_info.time - last < POLL_INTERVAL_S:
                return  # another packet from a wake we already handled
            self._last_session_adv_time = service_info.time
            await self._async_sync_locked(service_info)

    async def _async_sync_locked(self, service_info: BluetoothServiceInfoBleak) -> None:
        self.state.rssi = service_info.rssi
        client = None
        try:
            try:
                device = (
                    async_ble_device_from_address(self.hass, self.address, connectable=True)
                    or service_info.device
                )
                client = await async_connect(device, self.entry.title)
            except Exception as err:
                raise SessionError("connect", f"{type(err).__name__}: {err}") from err
            await self._async_run(KN550BTSession(client, self.variant))
        except SessionError as err:
            self._record_failure(err.stage, str(err))
        except Exception as err:  # noqa: BLE001 - never let a sync crash the coordinator
            _LOGGER.exception("Unexpected error syncing %s", self.address)
            self._record_failure("unexpected", f"{type(err).__name__}: {err}")
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("Disconnect from %s failed", self.address, exc_info=True)
            self.async_update_listeners()

    async def _async_run(self, session: KN550BTSession) -> None:
        info = await session.read_device_info()
        if info.model and info.model != MODEL:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"unsupported_device_{self.entry.entry_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="unsupported_device",
                translation_placeholders={"model": info.model, "address": self.address},
            )
            raise SessionError("device_info", f"unsupported model {info.model!r}")
        self.state.info = info
        dr.async_get(self.hass).async_update_device(
            self.device_id, sw_version=info.firmware or None, hw_version=info.hardware or None
        )

        await session.open()
        self.state.capabilities = await session.set_clock(dt_util.now().replace(tzinfo=None))
        self.state.battery = await session.battery()
        display = await session.get_display()
        pending = dict(self.store.pending_display)
        if pending:
            wanted = replace(display, **pending)
            if wanted != display:
                await session.set_display(wanted)
                display = wanted
            await self.store.async_clear_pending_display(pending)
        self.state.display = display

        download = await session.read_readings()
        readings = download.readings
        added = await self.store.async_add(readings, review=self.review_mode)
        imported = [r for r in added if r.status is ReadingStatus.IMPORTED]
        for reading in imported:
            self.fire_measurement_event(reading)
        if imported:
            await self.async_refresh_statistics({r.measured_at for r in imported})
        if not download.complete:
            # Never send the delete command after a partial download: it wipes everything.
            raise SessionError(
                "readings",
                f"incomplete download ({len(readings)} of {download.expected} readings); "
                "nothing was deleted from the cuff",
            )
        if self.delete_after_import and readings:
            await session.delete_readings()

        self.state.last_sync = dt_util.utcnow()
        self.state.failure_stage = self.state.failure_reason = None

    def _record_failure(self, stage: str, reason: str) -> None:
        _LOGGER.warning("Sync with %s failed during %s: %s", self.address, stage, reason)
        self.state.last_failure = dt_util.utcnow()
        self.state.failure_stage = stage
        self.state.failure_reason = reason

    def fire_measurement_event(self, reading: LoggedReading) -> None:
        self.hass.bus.async_fire(
            EVENT_MEASUREMENT,
            {
                "device_id": self.device_id,
                "address": self.address,
                "measured_at": dt_util.as_local(reading.measured_at).isoformat(),
                "systolic": reading.systolic,
                "diastolic": reading.diastolic,
                "pulse": reading.pulse,
                "irregular_pulse": reading.irregular_pulse,
                "body_movement": reading.body_movement,
            },
        )

    async def async_refresh_statistics(self, hours: set[datetime]) -> None:
        await async_update_statistics(
            self.hass, self.address, self.entry.title, self.store.imported(), hours
        )

    async def async_delete_reading(self, uid: str) -> None:
        """Delete a reading from Home Assistant (it is never re-imported)."""
        reading = self.store.find(uid)
        if reading is None or reading.status is ReadingStatus.DELETED:
            raise KeyError(uid)
        await self.store.async_set_status(uid, ReadingStatus.DELETED)
        if reading.status is ReadingStatus.IMPORTED:
            await self.async_refresh_statistics({reading.measured_at})
        self.async_update_listeners()

    async def async_approve_reading(self, uid: str) -> None:
        """Import a reading held for review."""
        reading = self.store.find(uid)
        if reading is None or reading.status is not ReadingStatus.PENDING:
            raise KeyError(uid)
        imported = await self.store.async_set_status(uid, ReadingStatus.IMPORTED)
        self.fire_measurement_event(imported)
        await self.async_refresh_statistics({imported.measured_at})
        self.async_update_listeners()

    async def async_request_display(self, field: str, value: bool) -> None:
        """Remember a display change; it is applied the next time the cuff connects."""
        await self.store.async_set_pending_display(field, value)
        self.async_update_listeners()
