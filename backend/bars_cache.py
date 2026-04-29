from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from mt5_service import Bar

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BARS_DIR = DATA_DIR / "bars"

import threading

_LOCKS: dict[str, threading.Lock] = {}
_GLOBAL_LOCK = threading.Lock()

def _get_lock(symbol: str) -> threading.Lock:
    with _GLOBAL_LOCK:
        if symbol not in _LOCKS:
            _LOCKS[symbol] = threading.Lock()
        return _LOCKS[symbol]

def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BARS_DIR.mkdir(parents=True, exist_ok=True)

# Ensure dirs on load
_ensure_dirs()

def get_symbol_path(symbol: str) -> Path:
    return BARS_DIR / f"{symbol}_H1.json"

def load_symbol_bars(symbol: str) -> list[dict[str, Any]]:
    """Load bars for a specific symbol from its own file"""
    path = get_symbol_path(symbol)
    lock = _get_lock(symbol)
    with lock:
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("bars", [])
        except Exception:
            return []

def save_symbol_bars(symbol: str, bars: list[dict[str, Any]]) -> None:
    """Save bars for a specific symbol to its own file"""
    path = get_symbol_path(symbol)
    lock = _get_lock(symbol)
    _ensure_dirs()
    
    with lock:
        data = {
            "symbol": symbol,
            "timeframe": "H1",
            "updated_at": datetime.now().isoformat(),
            "bars": bars
        }
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        try:
            if path.exists():
                path.unlink()
            tmp.rename(path)
        except Exception:
            import os
            os.replace(str(tmp), str(path))

def bars_to_dicts(bars: Iterable[Bar]) -> list[dict[str, Any]]:
    return [{"time": b.time, "open": b.open, "high": b.high, "low": b.low, "close": b.close} for b in bars]

def merge_bars(existing: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_time: dict[int, dict[str, Any]] = {int(b["time"]): b for b in existing}
    for b in new:
        by_time[int(b["time"])] = b
    merged = list(by_time.values())
    merged.sort(key=lambda x: int(x["time"]))
    return merged

def slice_bars(bars: list[dict[str, Any]], start_sec: int, end_sec: int) -> list[dict[str, Any]]:
    return [b for b in bars if start_sec <= int(b["time"]) <= end_sec]
