"""The reading log must be on disk before the cuff is told to wipe its memory."""

from custom_components.ihealth_bp.storage import CuffStore

from .conftest import ADDRESS


async def test_reading_log_uses_atomic_fsynced_writes(hass):
    store = CuffStore(hass, ADDRESS)
    assert store._store._atomic_writes is True
