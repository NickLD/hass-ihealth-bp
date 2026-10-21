"""A scripted com.jiuan.dev KN-550BT that speaks the real wire protocol to a bleak-like caller."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace

try:  # inside Home Assistant tests
    from custom_components.ihealth_bp.kn550bt.transport_v2 import KN550BT_KEY
    from custom_components.ihealth_bp.kn550bt.xxtea import xxtea2_decrypt, xxtea2_encrypt
except ImportError:  # protocol-only tests (no Home Assistant installed)
    from kn550bt.transport_v2 import KN550BT_KEY
    from kn550bt.xxtea import xxtea2_decrypt, xxtea2_encrypt

ADDRESS = "00:4D:32:65:0E:89"
WRITE = "7265632e-6a69-7561-6e2e-646576000000"
NOTIFY = "7365642e-6a69-7561-6e2e-646576000000"
INFO = {
    "00002a24-0000-1000-8000-00805f9b34fb": b"KN-550BT\x00",
    "00002a25-0000-1000-8000-00805f9b34fb": b"004D32650E89",
    "00002a26-0000-1000-8000-00805f9b34fb": b"303",
    "00002a27-0000-1000-8000-00805f9b34fb": b"300",
    "00002a29-0000-1000-8000-00805f9b34fb": b"iHealth",
    "0000ff01-0000-1000-8000-00805f9b34fb": b"com.jiuan.BPAV21\x00\x00",
    "0000ff02-0000-1000-8000-00805f9b34fb": b"BP Monitor",
}


class CuffDisconnected(Exception):
    """Raised from a write to simulate the cuff dropping the link."""


@dataclass
class StoredReading:
    time: datetime
    systolic: int
    diastolic: int
    pulse: int
    arrhythmia: bool = False
    body_movement: bool = False

    def encode(self) -> bytes:
        t = self.time
        flags = (0x80 if self.arrhythmia else 0) | (0x10 if self.body_movement else 0)
        return bytes([t.year - 2000, t.month, t.day, t.hour, t.minute, t.second,
                      self.systolic - self.diastolic, self.diastolic, self.pulse, 0, flags])


@dataclass
class FakeCuff:
    readings: list[StoredReading] = field(default_factory=list)
    battery: int = 100
    display_mask: int = 0x03
    model: bytes = b"KN-550BT\x00"
    page_size: int = 20
    report_count: int | None = None  # lie about the count (empty-reply case)
    errors: dict[int, int] = field(default_factory=dict)  # cmd -> error code (0x38 reply)
    disconnect_on: set[int] = field(default_factory=set)  # cmd -> raise CuffDisconnected
    accept_auth: bool = True
    truncate_after_pages: int | None = None  # later 0x4A replies come back empty
    raw_records: list[bytes] = field(default_factory=list)  # served before `readings`
    protocol_string: bytes | None = b"com.jiuan.BPAV21\x00\x00"  # None: no FF01 char
    clock: datetime | None = None
    received: list[bytes] = field(default_factory=list)  # payloads (A1 cmd ...) seen
    gate_cmd: int | None = None  # pause before handling this command until `gate` is set
    gate: asyncio.Event | None = None
    gate_reached: asyncio.Event | None = None

    def __post_init__(self) -> None:
        self._rx = bytearray()
        self._notify = None
        self._ka = b""
        self._r2 = b""
        self._page = 0
        info = dict(INFO)
        info["00002a24-0000-1000-8000-00805f9b34fb"] = self.model
        if self.protocol_string is None:
            del info["0000ff01-0000-1000-8000-00805f9b34fb"]
        else:
            info["0000ff01-0000-1000-8000-00805f9b34fb"] = self.protocol_string
        self.info = info
        chars = {uuid: SimpleNamespace(uuid=uuid, properties=["read"]) for uuid in info}
        chars[WRITE] = SimpleNamespace(uuid=WRITE, properties=["write-without-response"])
        chars[NOTIFY] = SimpleNamespace(uuid=NOTIFY, properties=["notify"])
        self.services = SimpleNamespace(get_characteristic=chars.get)
        self.is_connected = True

    # --- bleak surface ---------------------------------------------------------

    async def read_gatt_char(self, char) -> bytearray:
        uuid = getattr(char, "uuid", char)
        return bytearray(self.info[uuid])

    async def start_notify(self, char, callback) -> None:
        self._notify = callback

    async def disconnect(self) -> bool:
        self.is_connected = False
        return True

    async def write_gatt_char(self, char, data, response: bool = False) -> None:
        self._rx += bytes(data)
        while len(self._rx) >= 2 and len(self._rx) >= self._rx[1] + 3:
            total = self._rx[1] + 3
            frame = bytes(self._rx[:total])
            del self._rx[:total]
            if self.gate is not None and len(frame) > 5 and frame[5] == self.gate_cmd:
                if self.gate_reached is not None:
                    self.gate_reached.set()
                await self.gate.wait()
            self._handle(frame)

    # --- device behaviour ------------------------------------------------------

    def _reply(self, seq: int, cmd: int, data: bytes = b"") -> None:
        body = bytes([0x00, seq, 0xA1, cmd]) + data
        frame = bytes([0xA0, len(body)]) + body
        frame += bytes([sum(body) & 0xFF])
        for i in range(0, len(frame), 20):
            self._notify(None, bytearray(frame[i : i + 20]))

    def _handle(self, frame: bytes) -> None:
        assert frame[0] == 0xB0 and (sum(frame[2:-1]) & 0xFF) == frame[-1], frame.hex()
        seq, payload = frame[3], frame[4:-1]
        self.received.append(payload)
        cmd, args = payload[1], payload[2:]
        if cmd in self.disconnect_on:
            self.is_connected = False
            raise CuffDisconnected(f"link lost on 0x{cmd:02X}")
        if cmd in self.errors:
            self._reply(seq, 0x38, bytes([self.errors[cmd]]))
            return
        if cmd == 0xFA:
            k_seed = bytes.fromhex(ADDRESS.replace(":", "")) + bytes(10)
            self._ka = xxtea2_encrypt(k_seed, KN550BT_KEY)
            self._r2 = os.urandom(16)
            self._reply(seq, 0xFB, self._r2 + xxtea2_encrypt(args, self._ka) + k_seed)
        elif cmd == 0xFC:
            ok = self.accept_auth and xxtea2_decrypt(args, self._ka) == self._r2
            self._reply(seq, 0xFD if ok else 0xFE)
        elif cmd == 0x20:
            self._reply(seq, 0x20, bytes([self.battery, 0, 0]))
        elif cmd == 0x21:
            y, mo, d, h, mi, s = args[:6]
            self.clock = datetime(2000 + y, mo, d, h, mi, s)
            self._reply(seq, 0x21, bytes.fromhex("5512016300000000030000"))
        elif cmd == 0x60:
            self._reply(seq, 0x60, bytes([self.display_mask, 0, 0]))
        elif cmd == 0x61:
            self.display_mask = args[0]
            self._reply(seq, 0x61)
        elif cmd == 0x40:
            self._page = 0
            stored = len(self.raw_records) + len(self.readings)
            count = stored if self.report_count is None else self.report_count
            self._reply(seq, 0x40, bytes([0x01, count, 0, 0]))
        elif cmd == 0x4A:
            records = self.raw_records + [r.encode() for r in self.readings]
            done = self.truncate_after_pages is not None and self._page >= self.truncate_after_pages
            if not records or done:
                self._reply(seq, 0x4A)
                return
            page = records[self._page * self.page_size : (self._page + 1) * self.page_size]
            self._page += 1
            more = 1 if self._page * self.page_size < len(records) else 0
            self._reply(seq, 0x4A, bytes([0x01, more]) + b"".join(page))
        elif cmd == 0x47:
            self.readings.clear()
            self.raw_records.clear()
            self._reply(seq, 0x47, bytes(3))
        else:
            self._reply(seq, 0x38, bytes([0x20]))
