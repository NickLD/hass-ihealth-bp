"""Wait for a KN-550BT to advertise, connect, authenticate and dump its readings.

Usage: python tools/sync.py [--address AA:BB:..] [--wait 120] [--set-clock] [--ack] [-v]
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bleak import BleakClient, BleakScanner  # noqa: E402

from kn550bt import protocol as p  # noqa: E402



async def dump_gatt(device) -> None:
    async with BleakClient(device, timeout=20.0) as client:
        for service in client.services:
            print(f"service {service.uuid}")
            for char in service.characteristics:
                print(f"    char {char.uuid} {','.join(char.properties)}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--address")
    ap.add_argument("--wait", type=float, default=120)
    ap.add_argument("--set-clock", action="store_true")
    ap.add_argument("--ack", action="store_true", help="send 0x47 transfer-finished")
    ap.add_argument("--gatt", action="store_true", help="only dump the GATT table")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
    )
    for noisy in ("bleak",):
        logging.getLogger(noisy).setLevel(logging.INFO)

    print(f"waiting up to {args.wait:.0f}s for the cuff to advertise...", flush=True)
    if args.address:
        device = await BleakScanner.find_device_by_address(args.address, timeout=args.wait)
    else:
        device = await BleakScanner.find_device_by_filter(
            lambda d, adv: p.SERVICE_UUID in adv.service_uuids, timeout=args.wait
        )
    if device is None:
        sys.exit("cuff not found")
    print(f"found {device.address}, connecting", flush=True)

    if args.gatt:
        await dump_gatt(device)
        return

    result = await sync(device, set_clock=args.set_clock, acknowledge=args.ack)
    print(json.dumps(
        {
            "device_info": result.device_info,
            "battery": result.battery,
            "offline_count": result.offline_count,
            "readings": [r.as_dict() for r in result.readings],
        },
        indent=2,
    ))


asyncio.run(main())
