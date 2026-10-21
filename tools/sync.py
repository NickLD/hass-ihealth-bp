"""Wait for a KN-550BT to advertise, then run one session and print what it holds.

Usage: python tools/sync.py [--address AA:BB:..] [--wait 120] [--set-clock] [--delete]
                            [--display MASK] [-v]

Read-only unless --set-clock, --delete or --display is given.
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components" / "ihealth_bp"))

from bleak import BleakClient, BleakScanner  # noqa: E402

from kn550bt.session import DisplaySettings, KN550BTSession  # noqa: E402
from kn550bt.variants import variant_from_service_uuids  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--address")
    ap.add_argument("--wait", type=float, default=120)
    ap.add_argument("--set-clock", action="store_true")
    ap.add_argument("--delete", action="store_true", help="delete readings from the cuff (0x47)")
    ap.add_argument("--display", type=int, help="set display mask: bit0 backlight, bit1 clock")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
    )
    logging.getLogger("bleak").setLevel(logging.INFO)

    found = {}

    def match(device, adv) -> bool:
        if args.address and device.address.upper() != args.address.upper():
            return False
        variant = variant_from_service_uuids(adv.service_uuids, adv.local_name)
        if variant:
            found["variant"] = variant
        return variant is not None

    print(f"waiting up to {args.wait:.0f}s for the cuff to advertise...", flush=True)
    device = await BleakScanner.find_device_by_filter(match, timeout=args.wait)
    if device is None:
        sys.exit("cuff not found")
    variant = found["variant"]
    print(f"found {device.address} ({variant.value}{', UNTESTED' if variant.untested else ''})")

    async with BleakClient(device, timeout=20.0) as client:
        session = KN550BTSession(client, variant)
        info = await session.read_device_info()
        await session.open()
        out: dict = {"device_info": info.__dict__ | {"variant": variant.value}}
        if args.set_clock:
            out["capabilities"] = (await session.set_clock(datetime.now())).__dict__
        out["battery"] = await session.battery()
        if args.display is not None:
            await session.set_display(DisplaySettings.from_mask(args.display))
        out["display"] = (await session.get_display()).__dict__
        readings = await session.read_readings()
        out["readings"] = [r.as_dict() for r in readings]
        if args.delete and readings:
            await session.delete_readings()
            out["deleted"] = len(readings)
    print(json.dumps(out, indent=2, default=str))


asyncio.run(main())
