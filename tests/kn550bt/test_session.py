"""Session API against a scripted cuff."""

from datetime import datetime, timedelta

import pytest

from kn550bt.session import Capabilities, DisplaySettings, KN550BTSession, SessionError
from kn550bt.variants import Variant, variant_from_service_uuids

from .fake_cuff import FakeCuff, StoredReading

T0 = datetime(2026, 10, 21, 14, 52, 31)
DEV = "636f6d2e-6a69-7561-6e2e-646576000000"
AV10 = "636f6d2e-6a69-7561-6e2e-425041563130"
AV21 = "636f6d2e-6a69-7561-6e2e-425041563231"


def two_readings() -> list[StoredReading]:
    return [StoredReading(T0, 125, 64, 69), StoredReading(T0 + timedelta(minutes=16, seconds=31), 121, 71, 68)]


async def opened(cuff: FakeCuff) -> KN550BTSession:
    session = KN550BTSession(cuff, Variant.DEV, timeout=1.0)
    await session.read_device_info()
    await session.open()
    return session


async def test_full_sync_against_fake():
    cuff = FakeCuff(readings=two_readings())
    session = KN550BTSession(cuff, Variant.DEV, timeout=1.0)
    info = await session.read_device_info()
    assert (info.model, info.serial, info.firmware, info.protocol_string) == (
        "KN-550BT", "004D32650E89", "303", "com.jiuan.BPAV21")
    assert info.protocol_label == "com.jiuan.dev (BPAV21)"
    await session.open()
    assert await session.set_clock(datetime(2026, 10, 21, 15, 9, 5)) == Capabilities(1, 99, True)
    assert cuff.clock == datetime(2026, 10, 21, 15, 9, 5)
    assert await session.battery() == 100
    assert await session.get_display() == DisplaySettings(backlight=True, clock=True)
    download = await session.read_readings()
    assert download.complete and download.expected == 2
    assert [(r.time, r.systolic, r.diastolic, r.pulse) for r in download.readings] == [
        (T0, 125, 64, 69), (T0 + timedelta(minutes=16, seconds=31), 121, 71, 68)]


async def test_empty_cuff_returns_no_readings():
    session = await opened(FakeCuff())
    download = await session.read_readings()
    assert download.readings == [] and download.complete


async def test_empty_offline_reply_returns_no_readings_and_is_incomplete():
    session = await opened(FakeCuff(report_count=2))  # count says 2, data reply is empty
    download = await session.read_readings()
    assert download.readings == []
    assert not download.complete


async def test_fewer_records_than_count_is_incomplete():
    session = await opened(FakeCuff(readings=two_readings(), report_count=5))
    download = await session.read_readings()
    assert len(download.readings) == 2 and not download.complete


async def test_short_page_mid_stream_is_incomplete():
    stored = [StoredReading(T0 + timedelta(minutes=i), 120, 80, 60) for i in range(10)]
    cuff = FakeCuff(readings=stored, page_size=3, truncate_after_pages=2)
    download = await (await opened(cuff)).read_readings()
    assert len(download.readings) == 6 and not download.complete


async def test_ninety_nine_single_record_pages_are_all_read():
    stored = [StoredReading(T0 + timedelta(minutes=i), 120, 80, 60) for i in range(99)]
    download = await (await opened(FakeCuff(readings=stored, page_size=1))).read_readings()
    assert len(download.readings) == 99 and download.complete


async def test_unparseable_record_is_skipped_but_download_complete():
    bad = bytes([26, 0, 21, 14, 52, 31, 61, 64, 69, 0, 0])  # month 0
    cuff = FakeCuff(readings=two_readings(), raw_records=[bad])
    download = await (await opened(cuff)).read_readings()
    assert [r.systolic for r in download.readings] == [125, 121]
    assert download.complete


async def test_missing_protocol_string_uses_current_record_format():
    cuff = FakeCuff(readings=two_readings(), protocol_string=None)
    session = KN550BTSession(cuff, Variant.DEV, timeout=1.0)
    assert (await session.read_device_info()).protocol_string == ""
    await session.open()
    download = await session.read_readings()
    assert [r.systolic for r in download.readings] == [125, 121] and download.complete


async def test_ninety_nine_readings_over_multiple_pages():
    stored = [StoredReading(T0 + timedelta(minutes=i), 110 + i % 30, 70, 60 + i % 20) for i in range(99)]
    cuff = FakeCuff(readings=list(stored), page_size=20)
    session = await opened(cuff)
    download = await session.read_readings()
    assert len(download.readings) == 99 and download.complete
    assert [r.time for r in download.readings] == [s.time for s in stored]
    assert sum(1 for p in cuff.received if p[1] == 0x4A) == 5


async def test_set_display_sends_mask():
    cuff = FakeCuff()
    session = await opened(cuff)
    await session.set_display(DisplaySettings(backlight=False, clock=False))
    assert bytes.fromhex("a161000000") in cuff.received
    assert await session.get_display() == DisplaySettings(backlight=False, clock=False)


async def test_delete_readings_clears_cuff():
    cuff = FakeCuff(readings=two_readings())
    session = await opened(cuff)
    await session.delete_readings()
    assert cuff.readings == []


async def test_error_reply_raises_session_error_with_stage():
    session = await opened(FakeCuff(errors={0x20: 13}))
    with pytest.raises(SessionError) as err:
        await session.battery()
    assert err.value.stage == "battery"
    assert "Low battery" in str(err.value)


async def test_rejected_auth_raises():
    cuff = FakeCuff(accept_auth=False)
    session = KN550BTSession(cuff, Variant.DEV, timeout=1.0)
    await session.read_device_info()
    with pytest.raises(SessionError) as err:
        await session.open()
    assert err.value.stage == "auth"


async def test_timeout_raises_session_error():
    cuff = FakeCuff()
    session = await opened(cuff)
    cuff._notify = lambda *_: None  # cuff stops answering
    with pytest.raises(SessionError) as err:
        await session.battery()
    assert err.value.stage == "battery"


def test_variant_detection():
    assert variant_from_service_uuids([DEV], None) is Variant.DEV
    assert variant_from_service_uuids([AV21], None) is Variant.BPAV21
    assert variant_from_service_uuids([AV10], None) is None
    assert variant_from_service_uuids([AV10], "KN-550BT") is Variant.BPAV10
    assert variant_from_service_uuids(["0000180a-0000-1000-8000-00805f9b34fb"], "x") is None
    assert not Variant.DEV.untested and Variant.BPAV21.untested and Variant.BPAV10.untested
