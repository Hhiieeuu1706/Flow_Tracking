from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from typing import Any
import time

from bars_cache import load_cache, merge_bars, save_cache, slice_bars
from mt5_service import SUPPORTED_SYMBOLS, bars_to_lwc, fetch_h1_bars


def _dt_local_from_unix(sec: int) -> datetime:
    return datetime.fromtimestamp(sec)


def _unix_from_dt(dt: datetime) -> int:
    return int(dt.timestamp())


def _fetch_partial_for_symbol(symbol: str, start: datetime, end: datetime, cache: dict[str, Any]) -> None:
    t0 = time.perf_counter()
    symbols = cache.setdefault("symbols", {})
    sym_entry = symbols.setdefault(symbol, {"bars": []})
    existing_bars: list[dict[str, Any]] = sym_entry.get("bars", []) or []

    start_sec = _unix_from_dt(start)
    end_sec = _unix_from_dt(end)

    # Determine coverage inside desired window
    window_existing = slice_bars(existing_bars, start_sec, end_sec)
    if not window_existing:
        # No coverage: fetch full range
        print(f"[flow_tracking]   {symbol} cache=MISS fetch {start.isoformat()} -> {end.isoformat()}", flush=True)
        bars = fetch_h1_bars(symbol, start, end)
        print(f"[flow_tracking]   {symbol} fetched_full={len(bars)}", flush=True)
        sym_entry["bars"] = merge_bars(existing_bars, bars_to_lwc(bars))
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
        merged = merge_bars(merged, bars_to_lwc(bars))

    sym_entry["bars"] = merged
    print(
        f"[flow_tracking]   {symbol} done missing_ranges={len(missing_ranges)} total_cached={len(sym_entry['bars'])} in {((time.perf_counter()-t0)*1000):.1f} ms",
        flush=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="Lookback days to ensure cached")
    args = ap.parse_args()

    end = datetime.now()
    start = end - timedelta(days=max(1, int(args.days)))

    cache = load_cache()
    cache["timeframe"] = "H1"

    print(f"[flow_tracking] Prefetch start days={args.days} window={start.isoformat()} -> {end.isoformat()}", flush=True)
    for idx, sym in enumerate(SUPPORTED_SYMBOLS, start=1):
        print(f"[flow_tracking] [{idx}/{len(SUPPORTED_SYMBOLS)}] Ensuring cache {sym} H1 for last {args.days} day(s)...", flush=True)
        _fetch_partial_for_symbol(sym, start, end, cache)

    save_cache(cache)
    print("[flow_tracking] Cache updated.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

