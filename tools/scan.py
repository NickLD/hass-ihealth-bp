"""Scan for iHealth (com.jiuan.*) BLE devices and print their advertised services."""
import asyncio
import sys

from bleak import BleakScanner

JIUAN_SUFFIX = "-6a69-7561-6e2e-"  # "ji ua n." in every iHealth vendor UUID


def decode(uuid: str) -> str:
    try:
        return bytes.fromhex(uuid.replace("-", "")).rstrip(b"\0").decode("ascii")
    except ValueError:
        return ""


async def main(seconds: float) -> None:
    seen = {}

    def cb(dev, adv):
        jiuan = [u for u in adv.service_uuids if JIUAN_SUFFIX in u]
        name = adv.local_name or dev.name or ""
        if not jiuan and not any(k in name.upper() for k in ("550", "IHEALTH", "BP")):
            return
        key = dev.address
        if key not in seen:
            seen[key] = True
            print(f"{dev.address} rssi={adv.rssi} name={name!r}", flush=True)
            for u in adv.service_uuids:
                print(f"    service {u}  {decode(u) if JIUAN_SUFFIX in u else ''}", flush=True)
            if adv.manufacturer_data:
                print(f"    mfr {{{', '.join(f'{k:#06x}: {v.hex()}' for k, v in adv.manufacturer_data.items())}}}", flush=True)

    async with BleakScanner(cb):
        await asyncio.sleep(seconds)
    if not seen:
        print("no iHealth devices seen")


asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 30))
