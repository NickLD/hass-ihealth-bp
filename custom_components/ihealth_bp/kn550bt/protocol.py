"""iHealth KN-550BT BLE protocol (pure Python, no I/O).

Reverse engineered from iHealth MyVitals Pro 4.17.0 (com.ihealthlabs.MyVitalsPro):
  framing      com.ihealth.communication.base.protocol2.BleCommProtocol2 / BleUnPackageData2
  auth         com.ihealth.communication.ins.IdentifyIns2 + XXTEA2
  commands     com.ihealth.communication.ins.A1InsSetCommon / A1InSet_KN550BT
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from datetime import datetime

# --- GATT -------------------------------------------------------------------

# "com.jiuan.dev" firmware variant (BleCommProtocol2 path in the app).
SERVICE_UUID = "636f6d2e-6a69-7561-6e2e-646576000000"
# "rec." characteristic: the app writes commands here (BLE_TRANSMIT).
WRITE_UUID = "7265632e-6a69-7561-6e2e-646576000000"
# "sed." characteristic: the device notifies responses here (BLE_RECEIVE).
NOTIFY_UUID = "7365642e-6a69-7561-6e2e-646576000000"

DEVICE_INFO_UUIDS = {
    "model": "00002a24-0000-1000-8000-00805f9b34fb",
    "serial": "00002a25-0000-1000-8000-00805f9b34fb",
    "firmware": "00002a26-0000-1000-8000-00805f9b34fb",
    "hardware": "00002a27-0000-1000-8000-00805f9b34fb",
    "manufacturer": "00002a29-0000-1000-8000-00805f9b34fb",
    "protocol": "00002a30-0000-1000-8000-00805f9b34fb",
    "protocol_ff01": "0000ff01-0000-1000-8000-00805f9b34fb",
    "accessory_name": "0000ff02-0000-1000-8000-00805f9b34fb",
}

# --- commands (A1InsSetCommon) -----------------------------------------------

DEVICE_TYPE = 0xA1
CMD_BATTERY = 0x20
CMD_FUNCTION_INFO = 0x21  # also sets the device clock
CMD_START_MEASURE = 0x31
CMD_INTERRUPT_MEASURE = 0x37
CMD_ERROR = 0x38
CMD_OFFLINE_NUM = 0x40
CMD_OFFLINE_DATA = 0x46
CMD_OFFLINE_DATA_OVER = 0x47
CMD_OFFLINE_DATA_AV21 = 0x4A
CMD_GET_DISPLAY = 0x60
CMD_GET_TIME = 0x62
CMD_IDENTIFY = 0xFA
CMD_IDENTIFY_CHALLENGE = 0xFB
CMD_IDENTIFY_RESPONSE = 0xFC
CMD_IDENTIFY_OK = 0xFD
CMD_IDENTIFY_FAIL = 0xFE

ERRORS = {
    0: "No suitable zero in 20s",
    1: "Systolic pressure not found",
    2: "Diastolic pressure not found or systolic below diastolic",
    3: "Inflation too fast",
    4: "Inflation too slow",
    5: "Pressure exceeded 300 mmHg",
    6: "Pressure above 15 mmHg for more than 160s",
    7: "EEPROM read/write error",
    8: "EEPROM backup data error",
    10: "SPAN value error",
    11: "CRC error",
    12: "Connect error",
    13: "Low battery",
    14: "Reading above upper limit",
    16: "Reading below lower limit",
    17: "Arm movement during measurement",
    32: "Device is measuring",
}

# IdentifyIns2.n: XXTEA2 key used for "KN-550BT" and "KN-550BT_BPAV21".
KN550BT_KEY = bytes(
    b & 0xFF
    for b in (25, 1, 7, -106, -14, 35, 26, 104, -117, 84, 52, 98, -116, 87, -21, 25)
)

MTU_CHUNK = 20  # BleCommProtocol2.h


# --- XXTEA2 (little-endian words, length word appended on encrypt) ------------

_DELTA = 0x9E3779B9
_M32 = 0xFFFFFFFF


def _to_words(data: bytes, include_length: bool) -> list[int]:
    n = (len(data) + 3) // 4
    words = [0] * (n + 1 if include_length else n)
    for i, b in enumerate(data):
        words[i >> 2] |= b << ((i & 3) << 3)
    if include_length:
        words[n] = len(data)
    return words


def _to_bytes(words: list[int], include_length: bool) -> bytes | None:
    length = len(words) << 2
    if include_length:
        n = words[-1]
        if n < length - 7 or n > length - 4:
            return None
        length = n
    return bytes((words[i >> 2] >> ((i & 3) << 3)) & 0xFF for i in range(length))


def _fix_key(key: bytes) -> list[int]:
    return _to_words(key[:16].ljust(16, b"\0"), False)


def _mx(s: int, y: int, z: int, p: int, e: int, k: list[int]) -> int:
    return (((z >> 5) ^ (y << 2) & _M32) + ((y >> 3) ^ (z << 4) & _M32)) ^ (
        (s ^ y) + (k[(p & 3) ^ e] ^ z)
    )


def xxtea2_encrypt(data: bytes, key: bytes) -> bytes:
    if not data:
        return data
    v = _to_words(data, True)
    k = _fix_key(key)
    n = len(v) - 1
    z = v[n]
    s = 0
    for _ in range(52 // len(v) + 6):
        s = (s + _DELTA) & _M32
        e = (s >> 2) & 3
        for p in range(n):
            y = v[p + 1]
            z = v[p] = (v[p] + _mx(s, y, z, p, e, k)) & _M32
        y = v[0]
        z = v[n] = (v[n] + _mx(s, y, z, n, e, k)) & _M32
    return _to_bytes(v, False)  # type: ignore[return-value]


def xxtea2_decrypt(data: bytes, key: bytes) -> bytes | None:
    if not data:
        return data
    v = _to_words(data, False)
    k = _fix_key(key)
    n = len(v) - 1
    y = v[0]
    s = ((52 // len(v) + 6) * _DELTA) & _M32
    while s:
        e = (s >> 2) & 3
        for p in range(n, 0, -1):
            z = v[p - 1]
            y = v[p] = (v[p] - _mx(s, y, z, p, e, k)) & _M32
        z = v[n]
        y = v[0] = (v[0] - _mx(s, y, z, 0, e, k)) & _M32
        s = (s - _DELTA) & _M32
    return _to_bytes(v, True)


# --- framing -----------------------------------------------------------------


def build_frame(seq: int, payload: bytes) -> bytes:
    """B0 len 00 seq <payload> sum(bytes[2:])  (BleCommProtocol2.a/d)."""
    body = bytes([0x00, seq & 0xFF]) + payload
    frame = bytes([0xB0, len(payload) + 2]) + body
    return frame + bytes([sum(body) & 0xFF])


def chunk(frame: bytes) -> list[bytes]:
    return [frame[i : i + MTU_CHUNK] for i in range(0, len(frame), MTU_CHUNK)]


@dataclass
class Packet:
    command: int
    data: bytes
    raw: bytes


class StreamParser:
    """Reassemble A0-framed packets from notification chunks (BleUnPackageData2)."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk_: bytes) -> list[Packet]:
        self._buf += chunk_
        out: list[Packet] = []
        while True:
            start = self._buf.find(0xA0)
            if start < 0:
                self._buf.clear()
                return out
            del self._buf[:start]
            if len(self._buf) < 2:
                return out
            total = self._buf[1] + 3
            if len(self._buf) < total:
                return out
            frame = bytes(self._buf[:total])
            del self._buf[:total]
            if total <= 6 or (sum(frame[2:-1]) & 0xFF) != frame[-1]:
                continue
            out.append(Packet(command=frame[5], data=frame[6:-1], raw=frame))


# --- auth (IdentifyIns2) -----------------------------------------------------


def make_challenge() -> bytes:
    # Java fills with Random bytes and negates negatives, so every byte is 0..128.
    return bytes(b & 0x7F for b in os.urandom(16))


def identify_payload(r1: bytes) -> bytes:
    return bytes([DEVICE_TYPE, CMD_IDENTIFY]) + r1


def identify_answer(challenge: bytes, r1: bytes, key: bytes = KN550BT_KEY) -> bytes:
    """Answer the device's 0xFB challenge; raises if the device fails to prove itself."""
    if len(challenge) != 52:
        raise ValueError(f"expected 52-byte challenge, got {len(challenge)}")
    r2, r1_enc, k_seed = challenge[:16], challenge[16:36], challenge[36:52]
    ka = xxtea2_encrypt(k_seed, key)
    if xxtea2_decrypt(r1_enc, ka) != r1:
        raise ValueError("device failed mutual authentication (R1 mismatch)")
    return bytes([DEVICE_TYPE, CMD_IDENTIFY_RESPONSE]) + xxtea2_encrypt(r2, ka)


# --- commands ----------------------------------------------------------------


def cmd(command: int, *args: int) -> bytes:
    return bytes([DEVICE_TYPE, command, *args])


def function_info_payload(now: datetime) -> bytes:
    return cmd(
        CMD_FUNCTION_INFO,
        max(now.year - 2000, 0),
        now.month,
        now.day,
        now.hour,
        now.minute,
        now.second,
    )


@dataclass
class Reading:
    time: datetime
    systolic: int
    diastolic: int
    pulse: int
    arrhythmia: bool
    body_movement: bool | None = None
    hsd: bool | None = None

    def as_dict(self) -> dict:
        return {
            "time": self.time.isoformat(),
            "systolic": self.systolic,
            "diastolic": self.diastolic,
            "pulse": self.pulse,
            "arrhythmia": self.arrhythmia,
            "body_movement": self.body_movement,
            "hsd": self.hsd,
        }


def parse_records_av21(buf: bytes) -> list[Reading]:
    """11-byte records, protocol string com.jiuan.BPAV21 (A1InSet_KN550BT.e)."""
    out = []
    for i in range(0, len(buf) - len(buf) % 11, 11):
        r = buf[i : i + 11]
        y, mo, d, h, mi, s, sys_minus_dia, dia, pulse, _scheme, flags = r
        out.append(
            Reading(
                time=datetime(2000 + y, mo, d, h, mi, s),
                systolic=sys_minus_dia + dia,
                diastolic=dia,
                pulse=pulse,
                arrhythmia=bool(flags & 0x80),
                body_movement=bool(flags & 0x10),
            )
        )
    return out


def parse_records_legacy(buf: bytes) -> list[Reading]:
    """10-byte records, any other protocol string (A1InSet_KN550BT.e)."""
    out = []
    for i in range(0, len(buf) - len(buf) % 10, 10):
        r = buf[i : i + 10]
        out.append(
            Reading(
                time=datetime(2000 + (r[0] & 0x7F), r[1] & 0x7F, r[2], r[3], r[4]),
                systolic=r[5] + r[6],
                diastolic=r[6],
                pulse=r[7],
                arrhythmia=bool(r[0] & 0x80),
                hsd=bool(r[1] & 0x80),
            )
        )
    return out
