"""Regression tests from a live session with a KN-550BT (fw 303, com.jiuan.BPAV21) on 2026-10-21."""

from datetime import datetime

from kn550bt import protocol as p
from kn550bt import transport_v2 as t

H = bytes.fromhex

# Frames captured on the wire. The device answered the identify response with 0xFD (success).
IDENTIFY_TX = H("b0140001a1fa521c404e220e63526b59592f457226751b")
CHALLENGE_RX = H(
    "a0380001a1fb33127bb4abdd515b0c31002074320020d97e105b3a56ee0eca48e2e21a4c91ae"
    "bd9bc5ed004d32650e8900000000000000000000b6"
)
ANSWER_TX = H("b0180003a1fc8ab2cd0157412a6c83143694495a0a3d5823077318")
OFFLINE_RX = H("a0110009a14a01001a0a150e341f3d4045000051")


def test_build_frame_matches_capture():
    r1 = IDENTIFY_TX[6:22]
    assert t.build_frame(1, t.identify_payload(r1)) == IDENTIFY_TX
    assert t.build_frame(5, p.cmd(p.CMD_BATTERY, 0, 0, 0)) == H("b0070005a120000000c6")


def test_chunking_splits_at_20_bytes():
    assert [len(c) for c in t.chunk(IDENTIFY_TX)] == [20, 3]


def test_stream_parser_reassembles_split_notifications():
    parser = t.StreamParser()
    assert parser.feed(CHALLENGE_RX[:20]) == []
    assert parser.feed(CHALLENGE_RX[20:40]) == []
    (pkt,) = parser.feed(CHALLENGE_RX[40:] + H("a0040003a1fda1"))[:1]
    assert pkt.command == p.CMD_IDENTIFY_CHALLENGE
    assert len(pkt.data) == 52


def test_stream_parser_drops_bad_checksum():
    assert t.StreamParser().feed(H("a0040003a1fda2")) == []


def test_identify_answer_matches_accepted_capture():
    r1 = IDENTIFY_TX[6:22]
    (challenge,) = t.StreamParser().feed(CHALLENGE_RX)
    assert t.build_frame(3, t.identify_answer(challenge.data, r1)) == ANSWER_TX


def test_identify_rejects_wrong_r1():
    (challenge,) = t.StreamParser().feed(CHALLENGE_RX)
    try:
        t.identify_answer(challenge.data, bytes(16))
    except ValueError:
        return
    raise AssertionError("expected R1 mismatch")


def test_parse_av21_record():
    (pkt,) = t.StreamParser().feed(OFFLINE_RX)
    assert pkt.data[1] == 0  # no more pages
    (reading,) = p.parse_records_av21(pkt.data[2:])
    assert reading.time == datetime(2026, 10, 21, 14, 52, 31)
    assert (reading.systolic, reading.diastolic, reading.pulse) == (125, 64, 69)
    assert not reading.arrhythmia and not reading.body_movement
