from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any
from threading import RLock
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
SUPPORTED_SYMBOLS = ("XAUUSD", "UST10Y", "DXY", "VIX", "XTIUSD", "US30", "USTEC", "US500", "BTCUSD", "DJ30.f", "USTEC.f", "US500.f")

# ICMarkets terminal executable path
IC_MARKETS_TERMINAL_PATH = r"C:\Program Files\MetaTrader 5 IC Markets Global\terminal64.exe"
IC_MARKETS_DATA_PATH = r"C:\Users\PC\AppData\Roaming\MetaQuotes\Terminal\010E047102812FC0C18890992854220E"

# Wildcard symbol patterns (resolved dynamically from available symbols)
WILDCARD_SYMBOLS = {
    "UST10Y": "UST10Y_*M6",
    "DXY": "DXY_*",
    "VIX": "VIX_*",
    "XTIUSD": "XTIUSD*",
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
    The * can be anywhere in the pattern.
    """
    if "*" not in pattern:
        return pattern
    
    # Convert glob pattern to regex: e.g., "UST10Y_*" -> "^UST10Y_.*$"
    regex_pattern = "^" + pattern.replace("*", ".*") + "$"
    regex = re.compile(regex_pattern)
    
    ensure_mt5_ready()
    
    try:
        # Get all symbols from MT5
        all_symbols = mt5.symbols_get()
        if not all_symbols:
            _log.warning(f"No symbols available for wildcard resolution: {pattern}")
            return None
        
        # Filter symbols matching the regex
        matching = [s.name for s in all_symbols if regex.match(s.name)]
        if not matching:
            _log.warning(f"No symbols match pattern {pattern}")
            return None
        
        if len(matching) == 1:
            return matching[0]

        # Month codes to numeric value for sorting
        MONTH_CODES = {'H': 3, 'M': 6, 'U': 9, 'Z': 12}
        
        def sort_key(sym: str):
            # Try to extract month and year from common patterns
            # Pattern 1: DXY_M6 (MonthCode + 1-digit Year)
            m = re.search(r'_([HMUZ])(\d)$', sym)
            if m:
                month, year = m.groups()
                return (int(year), MONTH_CODES.get(month, 0))
            
            # Pattern 2: DXY_M26 (MonthCode + 2-digit Year)
            m = re.search(r'_([HMUZ])(\d{2})$', sym)
            if m:
                month, year = m.groups()
                return (int(year), MONTH_CODES.get(month, 0))
            
            # Pattern 3: DXY_MAR26 (3-char Month + 2-digit Year)
            MONTH_MAP = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6, 
                         'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
            m = re.search(r'_([A-Z]{3})(\d{2})$', sym)
            if m:
                mon_str, year = m.groups()
                return (int(year), MONTH_MAP.get(mon_str.upper(), 0))
            
            # Fallback to alphabetical
            return (0, sym)

        # Sort by (year, month) descending to get the latest contract
        matching.sort(key=sort_key, reverse=True)
        selected = matching[0]
        _log.info(f"Resolved wildcard {pattern} to {selected} (latest contract)")
        return selected
    except Exception as e:
        _log.error(f"Error resolving wildcard {pattern}: {e}")
        return None


_MT5_LOCK = RLock()
_MT5_READY = False


def ensure_mt5_ready():
    if not MT5_AVAILABLE:
        raise Mt5Error("MetaTrader5 package not installed")
    
    print(f"  [DEBUG] Checking MT5 connection (default)...", flush=True)
    if mt5.initialize():
        # Quick check if it's the right one or just any MT5
        acc = mt5.account_info()
        if acc:
            print(f"  [DEBUG] MT5 connected to running process. Account: {acc.login}", flush=True)
            return

    print(f"  [DEBUG] Default connection failed, trying explicit path: {IC_MARKETS_TERMINAL_PATH}", flush=True)
    if not mt5.initialize(path=IC_MARKETS_TERMINAL_PATH):
        err = mt5.last_error()
        print(f"  [ERROR] MT5 fully failed to initialize: {err}", flush=True)
        raise Mt5Error(f"MT5 initialize failed: {err}")
    
    # Check if logged in
    acc = mt5.account_info()
    if acc is None:
        print(f"  [WARN] MT5 initialized but no account info. Is terminal open and logged in?", flush=True)
    else:
        print(f"  [DEBUG] MT5 ready. Account: {acc.login}, Broker: {acc.company}", flush=True)


def with_mt5_lock(fn):
    def wrapper(*args, **kwargs):
        # print(f"  [DEBUG] Waiting for MT5 lock for {fn.__name__}...", flush=True)
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

    t0 = time.perf_counter()
    if ensure_visible and not mt5.symbol_select(symbol, True):
        _log.warning(f"Symbol {symbol} not available or failed to select. Skipping.")
        return []

    # MT5 python API expects naive datetimes aligned with the terminal clock.
    # If client 'end' is ahead of terminal "now" (timezone mismatches), cap it.
    now = datetime.now()
    if end > now:
        end = now
    if start >= end:
        # keep a minimal window to avoid MT5 errors
        start = end - timedelta(hours=1)

    # Chunking: MT5 can hang on very large range requests. Fetch in 30-day chunks.
    all_bars: list[Bar] = []
    current_start = start
    chunk_size = timedelta(days=30)

    while current_start < end:
        current_end = min(current_start + chunk_size, end)
        print(f"  [{symbol}] Fetching chunk: {current_start.date()} to {current_end.date()}...", flush=True)
        
        if not mt5.initialize(path=IC_MARKETS_TERMINAL_PATH):
            print(f"  [ERROR] MT5 initialization failed: {mt5.last_error()}", flush=True)
            return all_bars
        
        def _copy_range_with_retry() -> Any:
            rr = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_H1, current_start, current_end)
            if rr is None or len(rr) == 0:
                err = mt5.last_error()
                if err and err[0] == mt5.RES_S_OK:
                    return []
                _log.info(f"  [{symbol}] Retry chunk (last_error={err})...")
                time.sleep(0.5)
                rr = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_H1, current_start, current_end)
            return rr

        rates = _copy_range_with_retry()
        if rates is not None:
            for r in rates:
                all_bars.append(Bar(
                    time=int(r["time"]),
                    open=float(r["open"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    close=float(r["close"]),
                ))
        
        current_start = current_end

    if not all_bars:
        _log.warning(f"No rates returned for {symbol} after chunked fetch.")
        return []

    # Deduplicate and sort
    by_time: dict[int, Bar] = {b.time: b for b in all_bars}

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


def get_mt5_connection():
    """Get MT5 connection object, ensuring it's initialized"""
    try:
        ensure_mt5_ready()
        return mt5
    except Exception as e:
        _log.error(f"Failed to get MT5 connection: {e}")
        return None


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
