"""The two XXTEA variants used by iHealth cuffs."""

from __future__ import annotations

_DELTA = 0x9E3779B9
_M32 = 0xFFFFFFFF


def _mx(s: int, y: int, z: int, p: int, e: int, k: list[int]) -> int:
    return (((z >> 5) ^ (y << 2) & _M32) + ((y >> 3) ^ (z << 4) & _M32)) ^ (
        (s ^ y) + (k[(p & 3) ^ e] ^ z)
    )


def _encrypt_words(v: list[int], k: list[int]) -> list[int]:
    n = len(v) - 1
    z = v[n]
    s = 0
    for _ in range(52 // len(v) + 6):
        s = (s + _DELTA) & _M32
        e = (s >> 2) & 3
        for p in range(n):
            y = v[p + 1]
            z = v[p] = (v[p] + _mx(s, y, z, p, e, k)) & _M32
        y = v[0]
        z = v[n] = (v[n] + _mx(s, y, z, n, e, k)) & _M32
    return v


def _decrypt_words(v: list[int], k: list[int]) -> list[int]:
    n = len(v) - 1
    y = v[0]
    s = ((52 // len(v) + 6) * _DELTA) & _M32
    while s:
        e = (s >> 2) & 3
        for p in range(n, 0, -1):
            z = v[p - 1]
            y = v[p] = (v[p] - _mx(s, y, z, p, e, k)) & _M32
        z = v[n]
        y = v[0] = (v[0] - _mx(s, y, z, 0, e, k)) & _M32
        s = (s - _DELTA) & _M32
    return v


# --- XXTEA2: little-endian words, length word appended on encrypt (current firmware) ---


def _le_words(data: bytes, include_length: bool) -> list[int]:
    n = (len(data) + 3) // 4
    words = [0] * (n + 1 if include_length else n)
    for i, b in enumerate(data):
        words[i >> 2] |= b << ((i & 3) << 3)
    if include_length:
        words[n] = len(data)
    return words


def _le_bytes(words: list[int], include_length: bool) -> bytes | None:
    length = len(words) << 2
    if include_length:
        n = words[-1]
        if n < length - 7 or n > length - 4:
            return None
        length = n
    return bytes((words[i >> 2] >> ((i & 3) << 3)) & 0xFF for i in range(length))


def _fix_key(key: bytes) -> list[int]:
    return _le_words(key[:16].ljust(16, b"\0"), False)


def xxtea2_encrypt(data: bytes, key: bytes) -> bytes:
    if not data:
        return data
    words = _encrypt_words(_le_words(data, True), _fix_key(key))
    return _le_bytes(words, False)  # type: ignore[return-value]


def xxtea2_decrypt(data: bytes, key: bytes) -> bytes | None:
    if not data:
        return data
    return _le_bytes(_decrypt_words(_le_words(data, False), _fix_key(key)), True)


# --- Classic XXTEA: big-endian words, no length word (legacy firmware) -------


def xxtea_be_encrypt(data: bytes, key: bytes) -> bytes:
    if len(data) < 8:
        return data
    v = [int.from_bytes(data[i : i + 4], "big") for i in range(0, len(data), 4)]
    k = [int.from_bytes(key[i : i + 4], "big") for i in range(0, 16, 4)]
    return b"".join(w.to_bytes(4, "big") for w in _encrypt_words(v, k))
