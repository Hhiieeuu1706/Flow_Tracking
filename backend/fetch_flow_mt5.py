from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from typing import Any
import time
import logging
import sys

from bars_cache import load_symbol_bars, merge_bars, save_symbol_bars, slice_bars, bars_to_dicts
from mt5_service import SUPPORTED_SYMBOLS, fetch_h1_bars

# Configure logging to show progress in terminal
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)
_log = logging.getLogger("fetch_flow_mt5")

def _dt_local_from_unix(sec: int) -> datetime:
    return datetime.fromtimestamp(sec)

def _unix_from_dt(dt: datetime) -> int:
    return int(dt.timestamp())

def _fetch_partial_for_symbol(symbol: str, start: datetime, end: datetime) -> None:
    t0 = time.perf_counter()
    existing_bars = load_symbol_bars(symbol)

    start_sec = _unix_from_dt(start)
    end_sec = _unix_from_dt(end)

    # Determine coverage inside desired window
    window_existing = slice_bars(existing_bars, start_sec, end_sec)
    if not window_existing:
        # No coverage: fetch full range
        print(f"[flow_tracking]   {symbol} cache=MISS fetch {start.isoformat()} -> {end.isoformat()}", flush=True)
        bars = fetch_h1_bars(symbol, start, end)
        print(f"[flow_tracking]   {symbol} fetched_full={len(bars)}", flush=True)
        merged = merge_bars(existing_bars, bars_to_dicts(bars))
        save_symbol_bars(symbol, merged)
        print(f"[flow_tracking]   {symbol} done in {((time.perf_counter()-t0)*1000):.1f} ms", flush=True)
        return

    min_sec = int(window_existing[0]["time"])
    max_sec = int(window_existing[-1]["time"])

    # Buffer overlap to reduce edge gaps
    overlap = 2 * 60 * 60  # 2 hours

    missing_ranges: list[tuple[datetime, datetime]] = []
    if min_sec > start_sec:
        missing_ranges.append((_dt_local_from_unix(start_sec), _dt_local_from_unix(min_sec + overlap)))
    if max_sec < end_sec:
        missing_ranges.append((_dt_local_from_unix(max_sec - overlap), _dt_local_from_unix(end_sec)))

    merged = existing_bars
    for a, b in missing_ranges:
        print(f"[flow_tracking]   {symbol} fetch_missing {a.isoformat()} -> {b.isoformat()}", flush=True)
        bars = fetch_h1_bars(symbol, a, b)
        print(f"[flow_tracking]   {symbol} fetched_partial={len(bars)}", flush=True)
        merged = merge_bars(merged, bars_to_dicts(bars))

    save_symbol_bars(symbol, merged)
    print(
        f"[flow_tracking]   {symbol} done missing_ranges={len(missing_ranges)} total_cached={len(merged)} in {((time.perf_counter()-t0)*1000):.1f} ms",
        flush=True,
    )

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="Lookback days to ensure cached")
    ap.add_argument("--symbols", type=str, default="", help="Comma-separated symbols to fetch")
    args = ap.parse_args()

    end = datetime.now()
    start = end - timedelta(days=max(1, int(args.days)))

    target_symbols = SUPPORTED_SYMBOLS
    if args.symbols:
        requested = [s.strip() for s in args.symbols.split(",") if s.strip()]
        target_symbols = [s for s in SUPPORTED_SYMBOLS if s in requested]

    from mt5_service import resolve_wildcard_symbol, WILDCARD_SYMBOLS
    
    print(f"[flow_tracking] Prefetch start days={args.days} symbols={len(target_symbols)} window={start.isoformat()} -> {end.isoformat()}", flush=True)
    for idx, sym in enumerate(target_symbols, start=1):
        # Resolve wildcard if needed
        resolved = sym
        if sym in WILDCARD_SYMBOLS:
            resolved = resolve_wildcard_symbol(WILDCARD_SYMBOLS[sym]) or sym
        
        print(f"[flow_tracking] [{idx}/{len(SUPPORTED_SYMBOLS)}] Ensuring cache {sym} (resolved: {resolved}) H1 for last {args.days} day(s)...", flush=True)
        _fetch_partial_for_symbol(resolved, start, end)

    print("[flow_tracking] Cache updated.", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
