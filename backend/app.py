from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import logging
import time as _time
import sys

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from mt5_service import (
    Mt5Error,
    SUPPORTED_SYMBOLS,
    bars_to_lwc,
    fetch_h1_bars,
    fetch_h1_bars_multi,
    parse_query_params,
    resolve_wildcard_symbol,
    timed,
)
import mt5_service as _mt5_mod
from bars_cache import load_cache, merge_bars, save_cache, slice_bars
from flow_check import analyze_flow_check


BASE_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"

app = Flask(__name__, static_folder=str(FRONTEND_DIST), static_url_path="")
CORS(app)

APP_BUILD_ID = "2026-04-09-log-cmd-v3"

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = DATA_DIR / "backend_flow_tracking.log"

_log = logging.getLogger("flow_tracking")
if not _log.handlers:
    _log.setLevel(logging.INFO)
    fmt = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(fmt)
    # Stream to stdout so it shows in the backend CMD window.
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    _log.addHandler(fh)
    _log.addHandler(sh)
    # Keep logs from being duplicated by root handlers.
    _log.propagate = False

# Ensure MT5 logger also prints to console (propagate to our handlers if attached elsewhere).
_mt5_log = logging.getLogger("flow_tracking.mt5")
_mt5_log.setLevel(logging.INFO)
_mt5_log.propagate = True

_REQ_PROGRESS: dict[str, dict] = {}


def _flush_logs() -> None:
    for h in _log.handlers:
        try:
            h.flush()
        except Exception:
            pass


def _set_progress(req_id: str | None, stage: str, *, symbol: str | None = None, detail: str | None = None) -> None:
    if not req_id:
        return
    _REQ_PROGRESS[req_id] = {
        "req_id": req_id,
        "stage": stage,
        "symbol": symbol,
        "detail": detail,
        "ts": datetime.now().isoformat(),
        "pid": os.getpid(),
        "build": APP_BUILD_ID,
    }


_log.info("flow_tracking backend starting (log=%s)", str(LOG_PATH))
_flush_logs()


@app.before_request
def _log_api_requests():
    # Always print API requests to the backend console for easy debugging.
    try:
        if request.path.startswith("/api/"):
            print(f"[flow_tracking] {request.method} {request.path} qs={request.query_string.decode('utf-8', 'ignore')}", flush=True)
    except Exception:
        pass


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "build": APP_BUILD_ID}), 200


@app.get("/api/pid")
def pid():
    return jsonify({"pid": os.getpid(), "build": APP_BUILD_ID}), 200


@app.get("/api/symbols")
def symbols():
    return jsonify({"symbols": list(SUPPORTED_SYMBOLS)}), 200


@app.get("/api/log-test")
def log_test():
    print("[flow_tracking] /api/log-test HIT", flush=True)
    _log.info("GET /api/log-test HIT")
    _flush_logs()
    return jsonify({"ok": True, "ts": datetime.now().isoformat()}), 200


@app.get("/api/routes")
def routes():
    return (
        jsonify(
            {
                "rules": sorted([str(r) for r in app.url_map.iter_rules()]),
            }
        ),
        200,
    )


@app.get("/api/bars-progress/<req_id>")
def bars_progress(req_id: str):
    p = _REQ_PROGRESS.get(req_id)
    if not p:
        return jsonify({"error": "unknown req_id"}), 404
    return jsonify(p), 200


@app.get("/api/pyinfo")
def pyinfo():
    # Debug endpoint: confirm which mt5_service module is loaded.
    try:
        mt5_file = getattr(_mt5_mod, "__file__", None)
        # Grab the log format string line if present (best-effort)
        src = Path(mt5_file).read_text(encoding="utf-8") if mt5_file else ""
        hint = "first=%s last=%s" in src
        fmt = getattr(_mt5_mod, "MT5_LOG_FMT_H1", None)
        return jsonify({"mt5_service_file": mt5_file, "mt5_service_has_first_last": hint, "mt5_log_fmt_h1": fmt}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/bars")
def bars():
    try:
        t_done = timed("bars")
        symbol, start, end = parse_query_params(request.args)  # type: ignore[arg-type]
        bars = fetch_h1_bars(symbol, start, end)
        ms = t_done()
        return (
            jsonify(
                {
                    "symbol": symbol,
                    "timeframe": "H1",
                    "from": start.isoformat(),
                    "to": end.isoformat(),
                    "bars": bars_to_lwc(bars),
                    "perf_ms": round(ms, 2),
                }
            ),
            200,
        )
    except Mt5Error as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {e}"}), 500


@app.get("/api/bars-multi")
def bars_multi():
    try:
        t_req0 = _time.perf_counter()
        force = (request.args.get("force") or "").strip() in ("1", "true", "yes", "on")
        req_id = (request.args.get("req_id") or "").strip() or None
        symbols_raw = (request.args.get("symbols") or "").strip()
        if not symbols_raw:
            raise Mt5Error("Missing required param: symbols (comma-separated)")
        symbols = [s.strip() for s in symbols_raw.split(",") if s.strip()]
        symbols = [s.strip() for s in symbols_raw.split(",") if s.strip()]
        # Allow any symbol to pass through to MT5, as wildcards might resolve to names outside SUPPORTED_SYMBOLS

        start_raw = request.args.get("from") or request.args.get("start")
        end_raw = request.args.get("to") or request.args.get("end")
        if not start_raw or not end_raw:
            raise Mt5Error("Missing required params: from/to (or start/end)")

        # Reuse existing parser by faking args
        _, start, end = parse_query_params({"symbol": symbols[0], "from": start_raw, "to": end_raw})

        start_sec = int(start.timestamp())
        end_sec = int(end.timestamp())

        # Prefer cache for fast startup; fetch only missing ranges if needed.
        cache = load_cache()
        bars_by_symbol: dict[str, list[dict]] = {}
        last_time_by_symbol: dict[str, int | None] = {}

        print(
            f"[flow_tracking] bars-multi symbols={','.join(symbols)} from={start.isoformat()} to={end.isoformat()} force={force}",
            flush=True,
        )
        _log.info(
            "GET /api/bars-multi req_id=%s symbols=%s from=%s to=%s force=%s",
            req_id or "-",
            ",".join(symbols),
            start.isoformat(),
            end.isoformat(),
            force,
        )
        _set_progress(req_id, "started", detail=f"symbols={','.join(symbols)} force={force}")
        _flush_logs()
        t_done = timed("bars_multi")
        
        # Mapping for frontend names to backend wildcards if needed
        INTERNAL_MAPPING = {
            "DXY": "DXY_*",
            "UST10Y": "UST10Y_*",
            "VIX": "VIX_*",
        }

        for sym in symbols:
            # Resolve the real symbol name (e.g., DXY -> DXY_M6)
            pattern = INTERNAL_MAPPING.get(sym, sym)
            resolved_sym = resolve_wildcard_symbol(pattern)
            if not resolved_sym:
                _log.warning(f"Could not resolve symbol for {sym} (pattern={pattern})")
                bars_by_symbol[sym] = []
                last_time_by_symbol[sym] = None
                continue

            # In the cache and frontend results, we keep the original 'sym' name
            sym_entry = (cache.get("symbols") or {}).get(sym) or {"bars": []}
            existing_all: list[dict] = sym_entry.get("bars", []) or []
            window = slice_bars(existing_all, start_sec, end_sec)
            _set_progress(req_id, "symbol_start", symbol=sym, detail=f"resolving {sym}->{resolved_sym}")

            if force:
                # Force refresh should prioritize newest bars only, not refetch the whole range.
                overlap = 2 * 60 * 60
                if existing_all:
                    max_cached = int(existing_all[-1]["time"])
                    refresh_start = datetime.fromtimestamp(max(start_sec, max_cached - overlap))
                    _set_progress(req_id, "mt5_fetch_latest", symbol=sym, detail=f"{refresh_start.isoformat()} -> {end.isoformat()}")
                    print(f"[flow_tracking]   {sym} ({resolved_sym}) -> force refresh latest only", flush=True)
                    fetched = fetch_h1_bars(resolved_sym, refresh_start, end)
                    merged = merge_bars(existing_all, bars_to_lwc(fetched))
                else:
                    _set_progress(req_id, "mt5_fetch_bootstrap", symbol=sym, detail=f"{start.isoformat()} -> {end.isoformat()}")
                    print(f"[flow_tracking]   {sym} ({resolved_sym}) -> force bootstrap full range", flush=True)
                    fetched = fetch_h1_bars(resolved_sym, start, end)
                    merged = merge_bars(existing_all, bars_to_lwc(fetched))

                cache.setdefault("symbols", {}).setdefault(sym, {})["bars"] = merged
                sliced = slice_bars(merged, start_sec, end_sec)
                bars_by_symbol[sym] = sliced
                last_time_by_symbol[sym] = int(sliced[-1]["time"]) if sliced else None
                _set_progress(req_id, "symbol_done", symbol=sym, detail=f"bars={len(sliced)}")
                continue

            if not window:
                _set_progress(req_id, "mt5_fetch_cache_miss", symbol=sym, detail=f"{start.isoformat()} -> {end.isoformat()}")
                print(f"[flow_tracking]   {sym} ({resolved_sym}) -> fetch full range (cache miss)", flush=True)
                fetched = fetch_h1_bars(resolved_sym, start, end)
                merged = merge_bars(existing_all, bars_to_lwc(fetched))
                cache.setdefault("symbols", {}).setdefault(sym, {})["bars"] = merged
                sliced = slice_bars(merged, start_sec, end_sec)
                bars_by_symbol[sym] = sliced
                last_time_by_symbol[sym] = int(sliced[-1]["time"]) if sliced else None
                _set_progress(req_id, "symbol_done", symbol=sym, detail=f"bars={len(sliced)}")
                continue

            min_sec = int(window[0]["time"])
            max_sec = int(window[-1]["time"])
            overlap = 2 * 60 * 60

            merged = existing_all
            if min_sec > start_sec:
                # Skip backfilling old-left history in API path.
                print(f"[flow_tracking]   {sym} -> skip missing left", flush=True)
            if max_sec < end_sec:
                end_for_right = datetime.now()
                if end_for_right < datetime.fromtimestamp(max_sec - overlap):
                    end_for_right = end
                _set_progress(
                    req_id,
                    "mt5_fetch_missing_right",
                    symbol=sym,
                    detail=f"{datetime.fromtimestamp(max_sec - overlap).isoformat()} -> {end_for_right.isoformat()}",
                )
                print(f"[flow_tracking]   {sym} ({resolved_sym}) -> fetch missing right", flush=True)
                fetched = fetch_h1_bars(resolved_sym, datetime.fromtimestamp(max_sec - overlap), end_for_right)
                merged = merge_bars(merged, bars_to_lwc(fetched))

            cache.setdefault("symbols", {}).setdefault(sym, {})["bars"] = merged
            sliced = slice_bars(merged, start_sec, end_sec)
            bars_by_symbol[sym] = sliced
            last_time_by_symbol[sym] = int(sliced[-1]["time"]) if sliced else None
            _set_progress(req_id, "symbol_done", symbol=sym, detail=f"bars={len(sliced)}")

        _set_progress(req_id, "saving_cache")
        save_cache(cache)
        ms = t_done()
        print(f"[flow_tracking] bars-multi DONE perf_ms={round(ms,2)} total_ms={round((_time.perf_counter()-t_req0)*1000,2)}", flush=True)
        _log.info("DONE /api/bars-multi perf_ms=%.2f total_ms=%.2f", ms, (_time.perf_counter() - t_req0) * 1000.0)
        _set_progress(req_id, "done", detail=f"perf_ms={round(ms,2)}")
        _flush_logs()

        return (
            jsonify(
                {
                    "symbols": symbols,
                    "timeframe": "H1",
                    "from": start.isoformat(),
                    "to": end.isoformat(),
                    "barsBySymbol": bars_by_symbol,
                    "lastTimeBySymbol": last_time_by_symbol,
                    "perf_ms": round(ms, 2),
                    "req_id": req_id,
                    "build": APP_BUILD_ID,
                    "pid": os.getpid(),
                }
            ),
            200,
        )
    except Mt5Error as e:
        _set_progress((request.args.get("req_id") or "").strip() or None, "error", detail=str(e))
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        _set_progress((request.args.get("req_id") or "").strip() or None, "error", detail=f"Unexpected error: {e}")
        return jsonify({"error": f"Unexpected error: {e}"}), 500


@app.get("/api/flow-check")
def flow_check():
    """
    Flow Check analysis endpoint.
    Query params:
    - cutoff: date string YYYY-MM-DD (e.g., 2026-04-13)
    """
    try:
        cutoff_raw = (request.args.get("cutoff") or "").strip()
        if not cutoff_raw:
            return jsonify({"error": "Missing required param: cutoff (YYYY-MM-DD format)"}), 400
        
        cutoff_date = datetime.fromisoformat(cutoff_raw)
        _log.info(f"GET /api/flow-check cutoff={cutoff_raw}")
        
        result = analyze_flow_check(cutoff_date)
        
        return jsonify({
            "FlowState": str(result.FlowState),
            "DominantFlow": str(result.DominantFlow),
            "Score": float(result.Score),
            "alignment": int(result.alignment),
            "transmission": bool(result.transmission),
            "persistence": bool(result.persistence),
            "absorption": bool(result.absorption),
            "vol_spike": bool(result.vol_spike),
            "conflict": bool(result.conflict),
            "Regime": str(result.Regime),
            "assets_count": int(len(result.assets)),
        }), 200
    except ValueError as e:
        return jsonify({"error": f"Invalid cutoff date: {e}"}), 400
    except Exception as e:
        _log.error(f"Flow check error: {e}", exc_info=True)
        return jsonify({"error": f"Flow check failed: {e}"}), 500


@app.get("/")
def index():
    if FRONTEND_DIST.exists():
        return send_from_directory(FRONTEND_DIST, "index.html")
    return (
        jsonify(
            {
                "error": "Frontend not built yet.",
                "hint": "Run: cd flow_tracking/frontend && npm install && npm run build",
            }
        ),
        500,
    )


@app.get("/<path:path>")
def static_proxy(path: str):
    if not FRONTEND_DIST.exists():
        return jsonify({"error": "Frontend not built yet."}), 500

    # Support SPA routing: serve index.html for unknown paths
    full_path = FRONTEND_DIST / path
    if full_path.exists() and full_path.is_file():
        return send_from_directory(FRONTEND_DIST, path)
    return send_from_directory(FRONTEND_DIST, "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("FLOW_TRACKING_PORT", "5057"))
    app.run(host="127.0.0.1", port=port, debug=False)

