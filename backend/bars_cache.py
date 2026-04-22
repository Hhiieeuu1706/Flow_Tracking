from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from mt5_service import Bar


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CACHE_PATH = DATA_DIR / "bars_h1_cache.json"


import threading

_CACHE_LOCK = threading.Lock()

def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_cache() -> dict[str, Any]:
    with _CACHE_LOCK:
        _ensure_data_dir()
        if not CACHE_PATH.exists():
            return {"version": 1, "updated_at": None, "timeframe": "H1", "symbols": {}}
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)


def save_cache(cache: dict[str, Any]) -> None:
    with _CACHE_LOCK:
        _ensure_data_dir()
        cache["updated_at"] = datetime.now().isoformat()
        tmp = CACHE_PATH.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        try:
            if CACHE_PATH.exists():
                CACHE_PATH.unlink()
            tmp.rename(CACHE_PATH)
        except Exception:
            # Fallback if rename fails on Windows
            import os
            import time
            for _ in range(5):
                try:
                    if tmp.exists():
                        os.replace(str(tmp), str(CACHE_PATH))
                        break
                except Exception:
                    time.sleep(0.1)


def bars_to_dicts(bars: Iterable[Bar]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for b in bars:
        out.append({"time": b.time, "open": b.open, "high": b.high, "low": b.low, "close": b.close})
    return out


def merge_bars(existing: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_time: dict[int, dict[str, Any]] = {}
    for b in existing:
        by_time[int(b["time"])] = b
    for b in new:
        by_time[int(b["time"])] = b
    merged = list(by_time.values())
    merged.sort(key=lambda x: int(x["time"]))
    return merged


def slice_bars(bars: list[dict[str, Any]], start_sec: int, end_sec: int) -> list[dict[str, Any]]:
    # inclusive range
    return [b for b in bars if int(b["time"]) >= start_sec and int(b["time"]) <= end_sec]

