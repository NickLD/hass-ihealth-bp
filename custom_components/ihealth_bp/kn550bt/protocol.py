"""KN-550BT commands and record formats shared by both firmware variants (no I/O).

Reverse engineered from the iHealth MyVitals Pro 4.17.0 Android app.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

_LOGGER = logging.getLogger(__name__)

RECORD_SIZE_AV21 = 11
RECORD_SIZE_LEGACY = 10

# --- GATT -------------------------------------------------------------------

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

# --- commands ---------------------------------------------------------------

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
CMD_SET_DISPLAY = 0x61
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


@dataclass
class Packet:
    command: int
    data: bytes
    raw: bytes


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
    """11-byte records, protocol string com.jiuan.BPAV21. Unparseable records are skipped."""
    out = []
    for i in range(0, len(buf) - len(buf) % RECORD_SIZE_AV21, RECORD_SIZE_AV21):
        r = buf[i : i + RECORD_SIZE_AV21]
        y, mo, d, h, mi, s, sys_minus_dia, dia, pulse, _scheme, flags = r
        try:
            time = datetime(2000 + y, mo, d, h, mi, s)
        except ValueError:
            _LOGGER.warning("Skipping unparseable record %s", r.hex())
            continue
        out.append(
            Reading(
                time=time,
                systolic=sys_minus_dia + dia,
                diastolic=dia,
                pulse=pulse,
                arrhythmia=bool(flags & 0x80),
                body_movement=bool(flags & 0x10),
            )
        )
    return out


def parse_records_legacy(buf: bytes) -> list[Reading]:
    """10-byte records, any other protocol string. Unparseable records are skipped."""
    out = []
    for i in range(0, len(buf) - len(buf) % RECORD_SIZE_LEGACY, RECORD_SIZE_LEGACY):
        r = buf[i : i + RECORD_SIZE_LEGACY]
        try:
            time = datetime(2000 + (r[0] & 0x7F), r[1] & 0x7F, r[2], r[3], r[4])
        except ValueError:
            _LOGGER.warning("Skipping unparseable record %s", r.hex())
            continue
        out.append(
            Reading(
                time=time,
                systolic=r[5] + r[6],
                diastolic=r[6],
                pulse=r[7],
                arrhythmia=bool(r[0] & 0x80),
                hsd=bool(r[1] & 0x80),
            )
        )
    return out
