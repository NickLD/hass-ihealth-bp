"""Legacy KN-550BT firmware (services com.jiuan.BPAV21 / com.jiuan.BPAV10).

UNTESTED ON HARDWARE: built from the iHealth app's behaviour and checked against
vectors produced by the app's own code, but no legacy cuff has been available.

Frames: ``B0 len flag seq A1 cmd ... sum`` out, ``A0 ...`` in. Every non-ACK
frame from the cuff must be acknowledged. Payloads over 15 bytes are split into
14-byte fragments whose flag byte counts down.
"""

from __future__ import annotations

from .protocol import DEVICE_TYPE, Packet
from .xxtea import xxtea_be_encrypt

# 16-byte keys the app's native library returns for these model names.
LEGACY_KEYS = {
    "KN-550BT": bytes.fromhex("5835d27714e6e2da4de3795f6565ceb4"),
    "KN-550BT_BPAV21": bytes.fromhex("b51dfe0438ba4f897837979124e23fcc"),
}
KEY_WRAP = b"Ch/HQ4LzItYT42s="

_SINGLE_MAX = 15
_FRAGMENT = 14
_FLAG_NO_ACK = 0xF0


def nibble_swap(data: bytes) -> bytes:
    return bytes(((b & 0xF0) >> 4) | ((b & 0x0F) << 4) for b in data)


def word_swap(data: bytes) -> bytes:
    return b"".join(data[i : i + 4][::-1] for i in range(0, len(data), 4))


def legacy_ka(name: str) -> bytes:
    return xxtea_be_encrypt(nibble_swap(LEGACY_KEYS[name]), nibble_swap(KEY_WRAP))


def legacy_identify_answer(challenge48: bytes, name: str) -> bytes:
    """Answer the 0xFB challenge the way the app does (the middle block is unused)."""
    if len(challenge48) != 48:
        raise ValueError(f"expected 48-byte challenge, got {len(challenge48)}")
    key = xxtea_be_encrypt(word_swap(challenge48[:16]), legacy_ka(name))
    answer = word_swap(xxtea_be_encrypt(word_swap(challenge48[32:48]), key))
    return bytes([DEVICE_TYPE, 0xFC]) + answer


def _checksum(frame: bytes) -> int:
    return sum(frame[2:]) & 0xFF


class V1Framer:
    """Sequence numbers, fragmentation, ACKs and reassembly for the legacy protocol."""

    def __init__(self) -> None:
        self._seq = 1
        self._last_rx_seq: int | None = None
        self._parts: dict[int, bytes] = {}
        self._parts_total = 0

    def build(self, payload: bytes) -> list[bytes]:
        device_type, rest = payload[:1], payload[1:]
        if len(payload) <= _SINGLE_MAX:
            frames = [self._frame(0x00, device_type + rest)]
        else:
            full = len(rest) // _FRAGMENT
            frames = []
            for i in range(full + 1):
                part = rest[i * _FRAGMENT : (i + 1) * _FRAGMENT]
                flag = ((full << 4) + full - i) & 0xFF
                frames.append(self._frame(flag, device_type + part))
        return frames

    def _frame(self, flag: int, body: bytes) -> bytes:
        head = bytes([0xB0, len(body) + 2, flag, self._seq & 0xFF]) + body
        self._seq = (self._seq + 2) & 0xFF
        return head + bytes([_checksum(head)])

    def ack_for(self, frame: bytes) -> bytes | None:
        """ACK to send for a received frame; also advances our sequence number."""
        if len(frame) <= 6 or not self._valid(frame):
            return None
        flag = frame[2]
        rx_seq = (frame[3] - 1) & 0xFF if frame[3] else 0xFF
        if flag == _FLAG_NO_ACK:
            self._seq = (rx_seq + 2) & 0xFF
            return None
        low = flag & 0x0F
        b, b2 = 0xA0 + low, (rx_seq + 2) & 0xFF
        self._seq = (low * 2 + b2 + 2) & 0xFF
        return bytes([0xB0, 0x03, b, b2, DEVICE_TYPE, (b + b2 + DEVICE_TYPE) & 0xFF])

    @staticmethod
    def _valid(frame: bytes) -> bool:
        return (
            len(frame) >= 6
            and frame[0] == 0xA0
            and frame[1] == len(frame) - 3
            and _checksum(frame[:-1]) == frame[-1]
        )

    def feed(self, frame: bytes) -> list[Packet]:
        """Accept one notification (one frame); return completed packets."""
        if not self._valid(frame) or len(frame) == 6:
            return []
        flag, seq = frame[2], frame[3]
        if flag in (0x00, _FLAG_NO_ACK):
            if seq == self._last_rx_seq:
                return []
            self._last_rx_seq = seq
            return [Packet(command=frame[5], data=frame[6:-1], raw=frame)]
        if flag >= 0xA0:
            return []
        total, index = (flag >> 4) + 1, flag & 0x0F
        if total != self._parts_total:
            self._parts, self._parts_total = {}, total
        self._parts[index] = frame
        if len(self._parts) < total:
            return []
        ordered = [self._parts[i] for i in range(total - 1, -1, -1)]
        self._parts, self._parts_total = {}, 0
        first = ordered[0]
        data = first[6:-1] + b"".join(f[5:-1] for f in ordered[1:])
        return [Packet(command=first[5], data=data, raw=b"".join(ordered))]


class V1Transport:
    """Session adapter for the legacy firmware (UNTESTED ON HARDWARE)."""

    def __init__(self) -> None:
        self._framer = V1Framer()

    def encode(self, payload: bytes) -> list[bytes]:
        return self._framer.build(payload)

    def receive(self, data: bytes) -> tuple[list[Packet], list[bytes]]:
        ack = self._framer.ack_for(data)
        return self._framer.feed(data), [ack] if ack else []

    def answer(self, challenge: bytes, r1: bytes, name: str) -> bytes:
        return legacy_identify_answer(challenge, name)
