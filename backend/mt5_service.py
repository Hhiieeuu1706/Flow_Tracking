from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any
from threading import Lock
import time
import re
import logging
import os

try:
    import MetaTrader5 as mt5  # type: ignore

    MT5_AVAILABLE = True
except Exception:
    MT5_AVAILABLE = False


# Symbol mapping: UI names -> MT5 names
SUPPORTED_SYMBOLS = ("US30", "USTEC", "US500", "XAUUSD", "BTCUSD", "DXY", "UST10Y", "VIX", "DJ30.f", "USTEC.f", "US500.f")

# ICMarkets terminal executable path
IC_MARKETS_TERMINAL_PATH = r"C:\Program Files\MetaTrader 5 IC Markets Global\terminal64.exe"
IC_MARKETS_DATA_PATH = r"C:\Users\PC\AppData\Roaming\MetaQuotes\Terminal\010E047102812FC0C18890992854220E"

# Wildcard symbol patterns (resolved dynamically from available symbols)
WILDCARD_SYMBOLS = {
    "UST10Y": "UST10Y_*",
    "DXY": "DXY_*",
    "VIX": "VIX_*",
}


class Mt5Error(RuntimeError):
    pass


_log = logging.getLogger("flow_tracking.mt5")

MT5_LOG_FMT_H1 = "MT5 H1 %s %s -> %s bars=%s (+tail=%s) first=%s last=%s last_utc=%s ms=%.1f"


@dataclass(frozen=True)
class Bar:
    time: int  # unix seconds
    open: float
    high: float
    low: float
    close: float


def _parse_time_param(value: str) -> datetime:
    """
    Accept either:
    - unix seconds (int-like string)
    - ISO datetime: 2026-04-09T00:00:00
    - ISO datetime with Z: 2026-04-09T00:00:00.000Z
    - ISO date: 2026-04-09 (treated as 00:00:00)
    Returned datetime is local-naive to match MT5 expectations.
    """
    v = value.strip()
    if v.isdigit():
        # Treat numeric input as unix seconds (UTC), then convert to local-naive for MT5.
        sec = int(v)
        return datetime.fromtimestamp(sec, tz=timezone.utc).astimezone().replace(tzinfo=None)
    if v.endswith("Z"):
        # Python's fromisoformat doesn't accept trailing 'Z'
        v = v[:-1] + "+00:00"
    # Python only supports up to 6 digits for fractional seconds. Some clients send 7+.
    # Example: 2026-04-06T16:13:43.4196564+00:00
    v = re.sub(r"(\.\d{6})\d+([+-]\d{2}:\d{2})$", r"\1\2", v)
    v = re.sub(r"(\.\d{6})\d+$", r"\1", v)
    if "T" in v:
        # fromisoformat supports both with/without seconds
        dt = datetime.fromisoformat(v)
        # MT5 expects local-naive datetimes aligned with terminal/system local clock.
        # If input includes timezone, convert to local timezone then drop tzinfo.
        if dt.tzinfo:
            return dt.astimezone().replace(tzinfo=None)
        # If no tzinfo, assume caller already provided local-naive.
        return dt.replace(tzinfo=None)
    dt = datetime.fromisoformat(v)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)


def _initialize_mt5() -> None:
    if not MT5_AVAILABLE:
        raise Mt5Error("MetaTrader5 Python package is not installed")

    # Try ICMarkets terminal first (executable path)
    ic_markets_exe = IC_MARKETS_TERMINAL_PATH
    if os.path.exists(ic_markets_exe):
        try:
            if mt5.initialize(path=ic_markets_exe):
                _log.info(f"MT5 initialized with ICMarkets executable: {ic_markets_exe}")
                return
        except Exception as e:
            _log.warning(f"Failed to initialize with ICMarkets executable: {e}")

    # Fallback to default (if already running or in PATH)
    if mt5.initialize():
        _log.info("MT5 initialized with default process")
        return
    
    # Try default
    if mt5.initialize():
        _log.info("MT5 initialized with default path")
        return
    
    raise Mt5Error("MT5 initialize failed (ensure terminal is installed and logged in)")


def _shutdown_mt5() -> None:
    if MT5_AVAILABLE:
        try:
            mt5.shutdown()
        except Exception:
            pass


def resolve_wildcard_symbol(pattern: str) -> str | None:
    """
    Resolve wildcard symbols like UST10Y_*, DXY_*, VIX_* to the closest available match.
    Returns the closest matching symbol or None if not found.
    """
    if not pattern.endswith("*"):
        return pattern
    
    prefix = pattern[:-1]  # e.g., "UST10Y_" or "DXY_" or "VIX_"
    ensure_mt5_ready()
    
    try:
        # Get all symbols from MT5
        all_symbols = mt5.symbols_get()
        if not all_symbols:
            _log.warning(f"No symbols available for wildcard resolution: {pattern}")
            return None
        
        # Filter symbols matching the prefix
        matching = [s.name for s in all_symbols if s.name.startswith(prefix)]
        if not matching:
            _log.warning(f"No symbols match pattern {pattern}")
            return None
        
        # Sort and pick the closest match (assuming alphabetical order gives us the current/frontmost contract)
        matching.sort()
        selected = matching[0]
        _log.info(f"Resolved wildcard {pattern} to {selected}")
        return selected
    except Exception as e:
        _log.error(f"Error resolving wildcard {pattern}: {e}")
        return None


_MT5_LOCK = Lock()
_MT5_READY = False


def ensure_mt5_ready() -> None:
    global _MT5_READY
    if _MT5_READY:
        return
    _initialize_mt5()
    _MT5_READY = True


def with_mt5_lock(fn):
    def wrapper(*args, **kwargs):
        with _MT5_LOCK:
            ensure_mt5_ready()
            return fn(*args, **kwargs)

    return wrapper


@with_mt5_lock
def fetch_h1_bars(
    symbol: str,
    start: datetime,
    end: datetime,
    *,
    ensure_visible: bool = True,
    include_running_bar: bool = True,
) -> list[Bar]:
    # Allow symbols in SUPPORTED_SYMBOLS or anything that doesn't look like an error
    # (Resolved wildcards like DXY_M6 might not be in our static list)
    # if symbol not in SUPPORTED_SYMBOLS:
    #     raise Mt5Error(f"Unsupported symbol: {symbol}")

    if ensure_visible and not mt5.symbol_select(symbol, True):
        raise Mt5Error(f"Failed to select symbol: {symbol}")

    # MT5 python API expects naive datetimes aligned with the terminal clock.
    # If client 'end' is ahead of terminal "now" (timezone mismatches), cap it.
    now = datetime.now()
    if end > now:
        end = now
    if start >= end:
        # keep a minimal window to avoid MT5 errors
        start = end - timedelta(hours=1)

    t0 = time.perf_counter()

    def _copy_range_with_retry() -> Any:
        rr = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_H1, start, end)
        # MT5 can occasionally return stale/empty range right after session rollover.
        # Do one short retry before failing to reduce "missing latest bars" cases.
        if rr is None or len(rr) == 0:
            time.sleep(0.35)
            rr = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_H1, start, end)
        return rr

    rates = _copy_range_with_retry()
    if rates is None:
        try:
            err = mt5.last_error()
        except Exception:
            err = None
        raise Mt5Error(f"No rates returned for {symbol} (mt5_last_error={err})")

    by_time: dict[int, Bar] = {}
    for r in rates:
        b = Bar(
            time=int(r["time"]),
            open=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
        )
        by_time[b.time] = b

    # Add tail from most recent bars to avoid missing latest candles.
    # We intentionally merge BOTH strategies:
    # - copy_rates_from_pos(..., 0, N): robust latest history window
    # - copy_rates_from(..., now, N): mirrors fetch_from_mt5.py realtime behavior
    running_added = 0
    if include_running_bar:
        tails: list[Any] = []
        try:
            tail_pos = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 30)
            if tail_pos is not None:
                tails.append(tail_pos)
        except Exception:
            pass
        try:
            tail_now = mt5.copy_rates_from(symbol, mt5.TIMEFRAME_H1, now, 30)
            if tail_now is not None:
                tails.append(tail_now)
        except Exception:
            pass

        for tail in tails:
            for r in tail:
                b = Bar(
                    time=int(r["time"]),
                    open=float(r["open"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    close=float(r["close"]),
                )
                if b.time not in by_time:
                    running_added += 1
                by_time[b.time] = b

    bars = list(by_time.values())
    bars.sort(key=lambda x: x.time)
    first_t = bars[0].time if bars else None
    last_t = bars[-1].time if bars else None
    try:
        last_utc = datetime.fromtimestamp(last_t, tz=timezone.utc).isoformat() if last_t else None
    except Exception:
        last_utc = None
    _log.info(
        MT5_LOG_FMT_H1,
        symbol,
        start.isoformat(),
        end.isoformat(),
        len(bars),
        running_added,
        first_t,
        last_t,
        last_utc,
        (time.perf_counter() - t0) * 1000.0,
    )
    return bars


@with_mt5_lock
def fetch_h1_bars_multi(symbols: list[str], start: datetime, end: datetime) -> dict[str, list[Bar]]:
    out: dict[str, list[Bar]] = {}
    for sym in symbols:
        out[sym] = fetch_h1_bars(sym, start, end)
    return out


def timed(label: str):
    t0 = time.perf_counter()

    def done() -> float:
        return (time.perf_counter() - t0) * 1000.0

    return done


def bars_to_lwc(bars: list[Bar]) -> list[dict[str, Any]]:
    return [{"time": b.time, "open": b.open, "high": b.high, "low": b.low, "close": b.close} for b in bars]


def parse_query_params(args: dict[str, str]) -> tuple[str, datetime, datetime]:
    symbol = (args.get("symbol") or "").strip()
    if not symbol:
        raise Mt5Error("Missing required param: symbol")
    start_raw = args.get("from") or args.get("start")
    end_raw = args.get("to") or args.get("end")
    if not start_raw or not end_raw:
        raise Mt5Error("Missing required params: from/to (or start/end)")
    start = _parse_time_param(start_raw)
    end = _parse_time_param(end_raw)
    if end <= start:
        raise Mt5Error("Invalid range: end must be > start")
    return symbol, start, end


