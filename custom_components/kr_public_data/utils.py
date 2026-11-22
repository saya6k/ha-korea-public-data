"""Utility functions - NO pytz, NO blocking imports."""
from __future__ import annotations

import asyncio
import importlib
import secrets
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

# Korea has had no DST since 1988, so a fixed offset is exact and — unlike
# ZoneInfo — never reads tzdata from disk (safe to build on the event loop).
KST = timezone(timedelta(hours=9), "KST")

# 전체 시도명 → 축약명 (airkorea의 STATIONS_BY_SIDO/SIDO_AREA_CODE 키).
# 나머지 시도는 앞 두 글자가 곧 축약명이다.
_SIDO_SHORT = {"충청북도": "충북", "충청남도": "충남", "전라남도": "전남",
               "경상북도": "경북", "경상남도": "경남"}


async def async_import_curl_cffi() -> Any:
    """Return ``curl_cffi.requests``, importing it in the executor.

    curl_cffi loads a large C extension on first import, which must not
    happen on the event loop. Later calls are a ``sys.modules`` hit.

    A module lands in ``sys.modules`` *before* it finishes executing, so
    while another thread (e.g. KEPCO's executor job) is mid-import we'd see
    a partial module without ``AsyncSession``. Only trust the cached entry
    once it's complete; otherwise ``import_module`` blocks (in the executor)
    on the import lock until the other thread finishes.
    """
    mod = sys.modules.get("curl_cffi.requests")
    if getattr(mod, "AsyncSession", None) is None:
        mod = await asyncio.get_running_loop().run_in_executor(
            None, importlib.import_module, "curl_cffi.requests")
    return mod


def sido_short_name(name: str) -> str:
    """'서울특별시' → '서울', '충청북도' → '충북'."""
    return _SIDO_SHORT.get(name, name[:2])


class RSAKey:
    """RSA encryption for KEPCO login (matching rsa.js)."""
    def __init__(self) -> None:
        self.n = None
        self.e = 0

    def set_public(self, modulus_hex: str, exponent_hex: str) -> None:
        if modulus_hex and exponent_hex:
            self.n = int(modulus_hex, 16)
            self.e = int(exponent_hex, 16)
        else:
            raise ValueError("Invalid RSA public key")

    def do_public(self, x: int) -> int:
        return pow(x, self.e, self.n)

    def encrypt(self, text: str) -> str | None:
        key_size = (self.n.bit_length() + 7) // 8
        m = _pkcs1pad2(text, key_size)
        if m is None:
            return None
        c = self.do_public(m)
        h = hex(c)[2:]
        if len(h) % 2 == 1:
            h = "0" + h
        return h


def _pkcs1pad2(s: str, n: int) -> int:
    s_bytes = s.encode("utf-8")
    s_len = len(s_bytes)
    if n < s_len + 11:
        raise ValueError("Message too long for RSA")
    ba = bytearray(n)
    ba[n - s_len:n] = s_bytes
    ba[n - s_len - 1] = 0
    for i in range(2, n - s_len - 1):
        while True:
            rand_byte = secrets.randbelow(255) + 1
            if rand_byte != 0:
                ba[i] = rand_byte
                break
    ba[0] = 0
    ba[1] = 2
    result = int.from_bytes(ba, byteorder='big')
    return result


def get_value_from_path(data: dict[str, Any], path: str) -> Any:
    keys = path.split(".")
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return None
        if current is None:
            return None
    return current


def parse_date_value(raw_value: str, current_year: int | None = None) -> datetime | None:
    if not raw_value:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y.%m.%d", "%m/%d"):
        try:
            dt = datetime.strptime(raw_value.strip(), fmt)
            if current_year and dt.year == 1900:
                dt = dt.replace(year=current_year)
            return dt
        except ValueError:
            continue
    return None

