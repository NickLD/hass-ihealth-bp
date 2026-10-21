"""KN-550BT firmware variants, told apart by their advertised service."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class Variant(StrEnum):
    DEV = "com.jiuan.dev"
    BPAV21 = "com.jiuan.BPAV21"
    BPAV10 = "com.jiuan.BPAV10"

    @property
    def untested(self) -> bool:
        """True for the legacy firmware, which has never been run against hardware."""
        return self is not Variant.DEV

    @property
    def service_uuid(self) -> str:
        return SERVICE_UUIDS[self]

    @property
    def write_uuid(self) -> str:
        return "7265632e" + SERVICE_UUIDS[self][8:]  # "rec." characteristic

    @property
    def notify_uuid(self) -> str:
        return "7365642e" + SERVICE_UUIDS[self][8:]  # "sed." characteristic


SERVICE_UUIDS = {
    Variant.DEV: "636f6d2e-6a69-7561-6e2e-646576000000",
    Variant.BPAV21: "636f6d2e-6a69-7561-6e2e-425041563231",
    Variant.BPAV10: "636f6d2e-6a69-7561-6e2e-425041563130",
}


def variant_from_service_uuids(uuids: Iterable[str], local_name: str | None) -> Variant | None:
    """Pick the variant from an advertisement; BPAV10 is shared with other models."""
    found = {u.lower() for u in uuids}
    for variant, uuid in SERVICE_UUIDS.items():
        if uuid in found:
            if variant is Variant.BPAV10 and "550" not in (local_name or ""):
                return None
            return variant
    return None
