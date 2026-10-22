# KN-550BT Bluetooth protocol

Notes for interoperability, written from observing the iHealth MyVitals Pro app (4.17.0) and a live
KN-550BT (firmware 303, hardware 300). Byte values are hex. "Tested" marks what was verified against
the real cuff; everything about the older firmware is untested.

## Discovery

The cuff advertises (connectable, no local name) for about 10 seconds after a measurement or wake.

| Firmware | Service UUID | ASCII |
| :--- | :--- | :--- |
| current (tested) | `636f6d2e-6a69-7561-6e2e-646576000000` | `com.jiuan.dev` |
| older (untested) | `636f6d2e-6a69-7561-6e2e-425041563231` | `com.jiuan.BPAV21` |
| older (untested) | `636f6d2e-6a69-7561-6e2e-425041563130` | `com.jiuan.BPAV10` (also used by other models; the name contains "550") |

`com.jiuan.dev` is shared with other iHealth products, so confirm the model from Device Information
(`0x2A24` = `KN-550BT`).

Characteristics follow the service UUID with a different first word: write commands to `7265632e-…`
("rec.") and subscribe to notifications on `7365642e-…` ("sed."). Device Information: model `2A24`,
serial `2A25` (the MAC without colons), firmware `2A26`, hardware `2A27`, manufacturer `2A29`, protocol
string `FF01` (or `2A30`), e.g. `com.jiuan.BPAV21`.

## Current firmware framing (tested)

Command frame, written in 20-byte pieces (write without response):

```
B0 len 00 seq A1 cmd args… sum      len = 2 + len(A1 cmd args…), sum = Σ bytes from 00 to last arg
```

`seq` starts at 1 and increases by 2 per frame. Replies arrive as a byte stream split across
notifications; each reply is `A0 len flag seq A1 cmd data… sum` (total length `len + 3`, same checksum
rule). No link-layer acknowledgement is needed.

### Authentication

1. Send `A1 FA R1` where R1 is 16 random bytes in 0x00–0x7F.
2. The cuff replies `FB` with 52 bytes: `R2[16] E[20] S[16]`, where S begins with the cuff's MAC.
3. `K = xxtea2_encrypt(S, KEY)`. Check `xxtea2_decrypt(E, K) == R1` (the cuff proves itself).
4. Send `A1 FC xxtea2_encrypt(R2, K)` (20 bytes). The cuff answers `FD` (accepted) or `FE`.

`xxtea2` is XXTEA over little-endian 32-bit words; encryption appends the plaintext length as an
extra word, and decryption checks and strips it. Keys longer than 16 bytes are truncated to 16.
`KEY` is the fixed 16-byte value `19 01 07 96 f2 23 1a 68 8b 54 34 62 8c 57 eb 19`, the same for every
KN-550BT.

## Commands (both firmware variants)

| Cmd | Args | Reply | Meaning |
| :--- | :--- | :--- | :--- |
| `20` | `00 00 00` | `20 bat 00 00` | Battery %, tested |
| `21` | `YY MM DD hh mm ss` (year − 2000, local time) | `21` + capabilities | Set clock and read capabilities, tested |
| `40` | `01 00 00` | `40 01 count 00 00` | Stored reading count (memory group 1), tested |
| `4A` | `01 00 00` | `4A 01 more records…` | Readings, BPAV21 protocol string; repeat while `more` ≠ 0 (single page tested, see below) |
| `46` | `01 00 00` | `46 01 more records…` | Readings, other protocol strings (untested) |
| `47` | `00 00 00` | `47 00 00 00` | Transfer finished: **permanently deletes** the downloaded readings, tested |
| `60` | `00 00 00` | `60 mask 00 00` | Display settings: bit 0 backlight, bit 1 clock, tested |
| `61` | `mask 00 00` | `61` | Set display settings, tested |
| `62` | — | `62 YY MM DD hh mm ss` | Read clock, tested |
| `38` | — | `38 code` | Error reply (13 = low battery, 32 = measuring, …) |

An empty reply (no data bytes) to `4A` means there are no readings.

Only a single `4A` page has been seen from the real cuff (2 readings, `more` = 0). Repeating the
request while `more` ≠ 0 follows the iHealth app's logic and has only been exercised against a
simulated cuff.

The capabilities in the `21` reply (BPAV21 layout) are: byte 2 = memory groups (1 on the KN-550BT),
`byte7 × 256 + byte3` = capacity (99), and byte 8 bits 0/1 = backlight/clock settable.

### Records

BPAV21, 11 bytes: `YY MM DD hh mm ss (sys−dia) dia pulse scheme flags`. Flags bit 7 = irregular pulse
and bit 4 = body movement. Timestamps are naive local time.

Other protocol strings, 10 bytes (untested): `YY|irregular MM|hsd DD hh mm (sys−dia) dia pulse ? ?`.
Bit 7 of the year byte is irregular pulse and bit 7 of the month byte is HSD.

## Older firmware framing (untested)

- Frames use the same `B0 len flag seq A1 …` layout. A payload (counting `A1`) of more than 15 bytes is
  split into 14-byte fragments of the bytes after `A1`. With `n = len(rest) // 14`, fragment `i` has
  flag `(n << 4) + n − i`, and each fragment repeats `A1` and has its own checksum and `seq`.
- Every reply frame longer than 6 bytes with flag ≠ `F0` must be acknowledged with
  `B0 03 (A0 | flag & 0F) rxseq+1 A1 sum`. The next command's `seq` continues from
  `(flag & 0F) × 2 + rxseq + 3`. 6-byte frames from the cuff are acknowledgements.
- A reply frame with flag `F0` is not acknowledged; the next command's `seq` is `rxseq + 1`.
  In both rules `rxseq` is the `seq` byte of the received frame.
- Multi-fragment replies are reassembled in send order. The first fragment (highest low nibble)
  carries `A1 cmd data`, and later ones carry `A1 data`.
- Authentication: send `A1 FA R1`. The cuff replies `FB` with 48 bytes `B0 B1 B2`.
  - With `ws` = reverse the bytes of each 4-byte word and `ns` = swap the nibbles of each byte, compute
    `Ka = xxtea_be(ns(T), ns("Ch/HQ4LzItYT42s="))`. Here `xxtea_be` is classic XXTEA over big-endian
    words with no length word, and `T` is a 16-byte per-model table: `5835d27714e6e2da4de3795f6565ceb4`
    for name `KN-550BT`, or `b51dfe0438ba4f897837979124e23fcc` for `KN-550BT_BPAV21` (used when the
    protocol string is BPAV21/BPAV22).
  - Then `K = xxtea_be(ws(B0), Ka)`. The answer is `A1 FC ws(xxtea_be(ws(B2), K))`; B1 is not used.
    `FD` means accepted.
