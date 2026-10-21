"""iHealth KN-550BT BLE protocol (pure Python, no I/O).

Reverse engineered from iHealth MyVitals Pro 4.17.0 (com.ihealthlabs.MyVitalsPro):
  framing      com.ihealth.communication.base.protocol2.BleCommProtocol2 / BleUnPackageData2
  auth         com.ihealth.communication.ins.IdentifyIns2 + XXTEA2
  commands     com.ihealth.communication.ins.A1InsSetCommon / A1InSet_KN550BT
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

from .xxtea import xxtea2_decrypt, xxtea2_encrypt

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
