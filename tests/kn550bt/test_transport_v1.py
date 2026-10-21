"""Legacy (BPAV21/BPAV10) transport. Vectors come from the app's own Java code; no hardware test."""

import json
from pathlib import Path

import pytest

from kn550bt.transport_v1 import V1Framer, legacy_identify_answer
from kn550bt.xxtea import xxtea_be_encrypt

H = bytes.fromhex
VECTORS = json.loads((Path(__file__).parent / "vectors_v1.json").read_text())


def _ck(frame: bytes) -> bytes:
    return frame + bytes([sum(frame[2:]) & 0xFF])


@pytest.mark.parametrize("case", VECTORS["xxtea_be"])
def test_xxtea_be_matches_java_vectors(case):
    assert xxtea_be_encrypt(H(case["data"]), H(case["key"])) == H(case["out"])


@pytest.mark.parametrize("case", VECTORS["identify"])
def test_legacy_identify_matches_java_vectors(case):
    assert legacy_identify_answer(H(case["challenge"]), case["name"]) == H(case["answer"])


def test_v1_single_frame():
    assert V1Framer().build(H("a120000000")) == [H("b0070001a120000000c2")]


def test_v1_fragmented_identify_has_two_fragments_flags_11_10():
    frames = V1Framer().build(bytes([0xA1, 0xFA]) + bytes(range(16)))
    assert [f[2] for f in frames] == [0x11, 0x10]
    assert [f[3] for f in frames] == [1, 3]
    assert frames[0] == _ck(H("b0111101a1fa") + bytes(range(13)))
    assert frames[1] == _ck(H("b0061003a1") + bytes(range(13, 16)))


def test_v1_ack_for_data_frame():
    assert V1Framer().ack_for(H("a0070005a1206400002a")) == H("b003a006a147")


def test_v1_no_ack_for_ack_frame():
    assert V1Framer().ack_for(H("a003a002a143")) is None


def test_v1_sequence_continues_after_ack():
    framer = V1Framer()
    framer.ack_for(H("a0070005a1206400002a"))
    # ACK used seq 6; the next command uses 8.
    assert framer.build(H("a140010000"))[0][3] == 8


def test_v1_reassembles_two_fragment_reply():
    data = bytes(range(0x10, 0x24))  # 20 bytes
    framer = V1Framer()
    first = _ck(H("a0111121a140") + data[:13])
    second = _ck(H("a00a1023a1") + data[13:])
    assert framer.feed(first) == []
    (pkt,) = framer.feed(second)
    assert pkt.command == 0x40
    assert pkt.data == data


def test_v1_single_frame_reply_and_repeat_is_ignored():
    framer = V1Framer()
    frame = H("a0070005a1206400002a")
    (pkt,) = framer.feed(frame)
    assert (pkt.command, pkt.data) == (0x20, H("640000"))
    assert framer.feed(frame) == []
