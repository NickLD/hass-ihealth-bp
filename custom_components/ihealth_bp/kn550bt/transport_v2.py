"""Current KN-550BT firmware (service com.jiuan.dev): framing and authentication.

Frames: ``B0 len 00 seq A1 cmd ... sum`` written in 20-byte chunks; the cuff
answers with a byte stream of ``A0 len flag seq A1 cmd data... sum`` frames.
"""

from __future__ import annotations

import os

from .protocol import CMD_IDENTIFY, CMD_IDENTIFY_RESPONSE, DEVICE_TYPE, Packet
from .xxtea import xxtea2_decrypt, xxtea2_encrypt

# IdentifyIns2.n: XXTEA2 key used for "KN-550BT" and "KN-550BT_BPAV21".
KN550BT_KEY = bytes(
    b & 0xFF
    for b in (25, 1, 7, -106, -14, 35, 26, 104, -117, 84, 52, 98, -116, 87, -21, 25)
)

MTU_CHUNK = 20


# --- framing -----------------------------------------------------------------


def build_frame(seq: int, payload: bytes) -> bytes:
    """B0 len 00 seq <payload> sum(bytes[2:])  (BleCommProtocol2.a/d)."""
    body = bytes([0x00, seq & 0xFF]) + payload
    frame = bytes([0xB0, len(payload) + 2]) + body
    return frame + bytes([sum(body) & 0xFF])


def chunk(frame: bytes) -> list[bytes]:
    return [frame[i : i + MTU_CHUNK] for i in range(0, len(frame), MTU_CHUNK)]


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


class V2Transport:
    """Session adapter for the com.jiuan.dev firmware."""

    def __init__(self) -> None:
        self._seq = 1
        self._parser = StreamParser()

    def encode(self, payload: bytes) -> list[bytes]:
        frame = build_frame(self._seq, payload)
        self._seq = (self._seq + 2) & 0xFF
        return chunk(frame)

    def receive(self, data: bytes) -> tuple[list[Packet], list[bytes]]:
        return self._parser.feed(data), []

    def answer(self, challenge: bytes, r1: bytes, name: str) -> bytes:
        return identify_answer(challenge, r1)
