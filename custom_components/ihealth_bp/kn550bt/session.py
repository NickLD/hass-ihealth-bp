"""One connected conversation with a KN-550BT, independent of firmware variant."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from . import protocol as p
from .transport_v1 import V1Transport
from .transport_v2 import V2Transport, identify_payload, make_challenge
from .variants import Variant

_LOGGER = logging.getLogger(__name__)

PROTOCOL_AV21 = "com.jiuan.BPAV21"
_MAX_PAGES = 64  # 99 readings fit in far fewer pages; guards against a misbehaving cuff


class Transport(Protocol):
    def encode(self, payload: bytes) -> list[bytes]: ...
    def receive(self, data: bytes) -> tuple[list[p.Packet], list[bytes]]: ...
    def answer(self, challenge: bytes, r1: bytes, name: str) -> bytes: ...


class SessionError(Exception):
    """A session step failed; ``stage`` names the step."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"{stage}: {message}")
        self.stage = stage


@dataclass(frozen=True)
class DeviceInfo:
    model: str
    serial: str
    firmware: str
    hardware: str
    protocol_string: str
    variant: Variant

    @property
    def protocol_label(self) -> str:
        suffix = self.protocol_string.removeprefix("com.jiuan.")
        return f"{self.variant.value} ({suffix})" if suffix else self.variant.value


@dataclass(frozen=True)
class DisplaySettings:
    backlight: bool
    clock: bool

    @property
    def mask(self) -> int:
        return (1 if self.backlight else 0) | (2 if self.clock else 0)

    @classmethod
    def from_mask(cls, mask: int) -> DisplaySettings:
        return cls(backlight=bool(mask & 1), clock=bool(mask & 2))


@dataclass(frozen=True)
class Capabilities:
    memory_groups: int
    capacity: int
    display_settable: bool


class KN550BTSession:
    def __init__(self, client: Any, variant: Variant, *, timeout: float = 5.0) -> None:
        self._client = client
        self._variant = variant
        self._timeout = timeout
        self._transport: Transport = V2Transport() if variant is Variant.DEV else V1Transport()
        self._packets: asyncio.Queue[p.Packet] = asyncio.Queue()
        self._pending_writes: set[asyncio.Task] = set()
        self._write_response = False
        self.info: DeviceInfo | None = None

    # --- transport -------------------------------------------------------------

    def _on_notify(self, _char: Any, data: bytearray) -> None:
        _LOGGER.debug("<- %s", bytes(data).hex())
        packets, writes = self._transport.receive(bytes(data))
        for pkt in packets:
            self._packets.put_nowait(pkt)
        for frame in writes:
            task = asyncio.ensure_future(self._write(frame))
            self._pending_writes.add(task)
            task.add_done_callback(self._pending_writes.discard)

    async def _write(self, data: bytes) -> None:
        _LOGGER.debug("-> %s", data.hex())
        await self._client.write_gatt_char(
            self._variant.write_uuid, data, response=self._write_response
        )

    async def _request(self, stage: str, payload: bytes, *expect: int) -> p.Packet:
        try:
            for part in self._transport.encode(payload):
                await self._write(part)
            return await self._recv(stage, *expect)
        except SessionError:
            raise
        except Exception as err:
            raise SessionError(stage, f"{type(err).__name__}: {err}") from err

    async def _recv(self, stage: str, *commands: int) -> p.Packet:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise SessionError(stage, "timed out waiting for the cuff")
            try:
                pkt = await asyncio.wait_for(self._packets.get(), remaining)
            except TimeoutError as err:
                raise SessionError(stage, "timed out waiting for the cuff") from err
            if pkt.command == p.CMD_ERROR:
                code = pkt.data[0] if pkt.data else -1
                raise SessionError(stage, f"cuff error {code}: {p.ERRORS.get(code, 'unknown')}")
            if pkt.command in commands:
                return pkt
            _LOGGER.debug("ignoring unexpected reply 0x%02X during %s", pkt.command, stage)

    # --- operations ------------------------------------------------------------

    async def read_device_info(self) -> DeviceInfo:
        values: dict[str, str] = {}
        try:
            for name, uuid in p.DEVICE_INFO_UUIDS.items():
                char = self._client.services.get_characteristic(uuid)
                if char is None or "read" not in char.properties:
                    continue
                raw = await self._client.read_gatt_char(char)
                values[name] = bytes(raw).split(b"\0", 1)[0].decode("utf-8", "replace").strip()
        except Exception as err:
            raise SessionError("device_info", f"{type(err).__name__}: {err}") from err
        write_char = self._client.services.get_characteristic(self._variant.write_uuid)
        self._write_response = write_char is not None and (
            "write-without-response" not in write_char.properties
        )
        self.info = DeviceInfo(
            model=values.get("model", ""),
            serial=values.get("serial", ""),
            firmware=values.get("firmware", ""),
            hardware=values.get("hardware", ""),
            protocol_string=values.get("protocol") or values.get("protocol_ff01") or "",
            variant=self._variant,
        )
        return self.info

    @property
    def _protocol_string(self) -> str:
        return self.info.protocol_string if self.info else ""

    async def open(self) -> None:
        """Subscribe to notifications and run the mutual authentication."""
        try:
            await self._client.start_notify(self._variant.notify_uuid, self._on_notify)
        except Exception as err:
            raise SessionError("auth", f"{type(err).__name__}: {err}") from err
        r1 = make_challenge()
        challenge = await self._request("auth", identify_payload(r1), p.CMD_IDENTIFY_CHALLENGE)
        name = "KN-550BT_BPAV21" if self._protocol_string in (
            "com.jiuan.BPAV21", "com.jiuan.BPAV22") else "KN-550BT"
        try:
            answer = self._transport.answer(challenge.data, r1, name)
        except ValueError as err:
            raise SessionError("auth", str(err)) from err
        result = await self._request("auth", answer, p.CMD_IDENTIFY_OK, p.CMD_IDENTIFY_FAIL)
        if result.command != p.CMD_IDENTIFY_OK:
            raise SessionError("auth", "cuff rejected authentication")

    async def set_clock(self, now: datetime) -> Capabilities:
        data = (await self._request("clock", p.function_info_payload(now), p.CMD_FUNCTION_INFO)).data
        if len(data) >= 9:
            return Capabilities(
                memory_groups=data[2],
                capacity=data[7] * 256 + data[3],
                display_settable=bool(data[8] & 0x03),
            )
        return Capabilities(memory_groups=1, capacity=0, display_settable=False)

    async def battery(self) -> int:
        data = (await self._request("battery", p.cmd(p.CMD_BATTERY, 0, 0, 0), p.CMD_BATTERY)).data
        level = data[0] if data else 0
        return level if 0 < level <= 100 else 100

    async def get_display(self) -> DisplaySettings:
        pkt = await self._request("display", p.cmd(p.CMD_GET_DISPLAY, 0, 0, 0), p.CMD_GET_DISPLAY)
        return DisplaySettings.from_mask(pkt.data[0] if pkt.data else 0)

    async def set_display(self, settings: DisplaySettings) -> None:
        await self._request(
            "display", p.cmd(p.CMD_SET_DISPLAY, settings.mask, 0, 0), p.CMD_SET_DISPLAY
        )

    async def read_readings(self) -> list[p.Reading]:
        count = await self._request("readings", p.cmd(p.CMD_OFFLINE_NUM, 1, 0, 0), p.CMD_OFFLINE_NUM)
        if len(count.data) < 2 or count.data[1] == 0:
            return []
        av21 = self._protocol_string == PROTOCOL_AV21
        command = p.CMD_OFFLINE_DATA_AV21 if av21 else p.CMD_OFFLINE_DATA
        buf = b""
        for _ in range(_MAX_PAGES):
            data = (await self._request(
                "readings", p.cmd(command, 1, 0, 0), p.CMD_OFFLINE_DATA, p.CMD_OFFLINE_DATA_AV21
            )).data
            if len(data) < 2:
                break
            buf += data[2:]
            if data[1] == 0:
                break
        return p.parse_records_av21(buf) if av21 else p.parse_records_legacy(buf)

    async def delete_readings(self) -> None:
        await self._request(
            "delete", p.cmd(p.CMD_OFFLINE_DATA_OVER, 0, 0, 0), p.CMD_OFFLINE_DATA_OVER
        )
