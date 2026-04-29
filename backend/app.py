from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import logging
import time as _time
import sys
import json

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
    get_mt5_connection,
    timed,
)
import mt5_service as _mt5_mod
from bars_cache import load_symbol_bars, merge_bars, save_symbol_bars, slice_bars
from flow_check import analyze_flow_check
from macro_engine import MacroEngine


BASE_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"

app = Flask(__name__, static_folder=str(FRONTEND_DIST), static_url_path="")
CORS(app)

APP_BUILD_ID = "2026-04-28-symbol-refactor-v1"

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = DATA_DIR / "backend_flow_tracking.log"
FLOW_SNAPSHOT_PATH = DATA_DIR / "flow_strength_history.json"

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

def _load_flow_snapshots() -> dict:
    if not FLOW_SNAPSHOT_PATH.exists():
        return {"updated_at": None, "snapshots": []}
    try:
        return json.loads(FLOW_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"updated_at": None, "snapshots": []}


def _save_flow_snapshots(payload: dict) -> None:
    FLOW_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = FLOW_SNAPSHOT_PATH.with_suffix(".tmp")
    try:
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if FLOW_SNAPSHOT_PATH.exists():
            os.remove(FLOW_SNAPSHOT_PATH)
        os.rename(temp_path, FLOW_SNAPSHOT_PATH)
    except Exception as e:
        _log.error(f"Failed to save flow snapshots atomically: {e}")
        if temp_path.exists():
            os.remove(temp_path)


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
        
        from mt5_service import resolve_wildcard_symbol, WILDCARD_SYMBOLS
        
        for sym in symbols:
            # Resolve the real symbol name (e.g., DXY -> DXY_M6)
            pattern = WILDCARD_SYMBOLS.get(sym, sym)
            resolved_sym = resolve_wildcard_symbol(pattern)
            if not resolved_sym:
                _log.warning(f"Could not resolve symbol for {sym} (pattern={pattern})")
                bars_by_symbol[sym] = []
                last_time_by_symbol[sym] = None
                continue

            existing_all = load_symbol_bars(resolved_sym)
            window = slice_bars(existing_all, start_sec, end_sec)
            _set_progress(req_id, "symbol_start", symbol=sym, detail=f"resolving {sym}->{resolved_sym}")

            if force or not window:
                print(f"[flow_tracking]   {sym} ({resolved_sym}) -> fetch full range", flush=True)
                fetched = fetch_h1_bars(resolved_sym, start, end)
                merged = merge_bars(existing_all, bars_to_lwc(fetched))
                save_symbol_bars(resolved_sym, merged)
                sliced = slice_bars(merged, start_sec, end_sec)
                bars_by_symbol[sym] = sliced
                last_time_by_symbol[sym] = int(sliced[-1]["time"]) if sliced else None
                continue

            min_sec = int(window[0]["time"])
            max_sec = int(window[-1]["time"])
            overlap = 2 * 60 * 60

            missing_ranges = []
            if min_sec > start_sec:
                # print(f"[flow_tracking]   {sym} -> skip missing left", flush=True)
                pass # Already handled by backfill in theory
            if max_sec < end_sec:
                missing_ranges.append((datetime.fromtimestamp(max_sec - overlap), datetime.fromtimestamp(end_sec)))

            merged = existing_all
            for a, b in missing_ranges:
                print(f"[flow_tracking]   {sym} ({resolved_sym}) -> fetch missing {a.date()} to {b.date()}", flush=True)
                fetched = fetch_h1_bars(resolved_sym, a, b)
                merged = merge_bars(merged, bars_to_lwc(fetched))

            if missing_ranges:
                save_symbol_bars(resolved_sym, merged)

            sliced = slice_bars(merged, start_sec, end_sec)
            bars_by_symbol[sym] = sliced
            last_time_by_symbol[sym] = int(sliced[-1]["time"]) if sliced else None
            _set_progress(req_id, "symbol_done", symbol=sym, detail=f"bars={len(sliced)}")

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


@app.post("/api/flow-snapshot")
def flow_snapshot():
    """
    Persist frontend flow strength rows for research backtesting.
    Expected JSON:
    {
      "snapshot_date": "YYYY-MM-DD",
      "rows": [{id, asset, date, flowType, strength, ...}]
    }
    """
    try:
        payload = request.get_json(silent=True) or {}
        rows = payload.get("rows") or []
        snapshot_date = str(payload.get("snapshot_date") or datetime.utcnow().date().isoformat())
        if not isinstance(rows, list):
            return jsonify({"error": "rows must be an array"}), 400

        # Keep only rows with numeric strength for compact research payload.
        cleaned_rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            strength = row.get("strength")
            if strength is None:
                continue
            try:
                strength_value = float(strength)
            except Exception:
                continue
            cleaned_rows.append(
                {
                    "id": str(row.get("id") or ""),
                    "asset": str(row.get("asset") or ""),
                    "date": str(row.get("date") or ""),
                    "flowType": str(row.get("flowType") or ""),
                    "strength": strength_value,
                    "updatedAt": row.get("updatedAt"),
                }
            )

        store = _load_flow_snapshots()
        snapshots = store.get("snapshots", [])
        snapshots = [s for s in snapshots if str(s.get("snapshot_date")) != snapshot_date]
        snapshots.append(
            {
                "snapshot_date": snapshot_date,
                "saved_at": datetime.utcnow().isoformat(),
                "rows": cleaned_rows,
                "rows_count": len(cleaned_rows),
            }
        )
        snapshots = sorted(snapshots, key=lambda s: str(s.get("snapshot_date")))

        out = {
            "updated_at": datetime.utcnow().isoformat(),
            "snapshots": snapshots,
        }
        _save_flow_snapshots(out)
        _log.info("Saved flow snapshot date=%s rows=%s", snapshot_date, len(cleaned_rows))
        return jsonify({"ok": True, "snapshot_date": snapshot_date, "rows_saved": len(cleaned_rows)}), 200
    except Exception as e:
        _log.error(f"Flow snapshot save error: {e}", exc_info=True)
        return jsonify({"error": f"Flow snapshot save failed: {e}"}), 500


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


# Special route for Macro Panel (separate page)
@app.get("/macro")
def macro_page():
    """Serve Macro Panel as a standalone page"""
    if FRONTEND_DIST.exists():
        return send_from_directory(FRONTEND_DIST, "macro.html")
    return jsonify({
        "error": "Frontend not built yet.",
        "hint": "Run: cd flow_tracking/frontend && npm install && npm run build",
    }), 500

@app.route("/api/macro/status", methods=["GET"])
def get_macro_status():
    """Get current macro cache status (from individual symbol files)"""
    try:
        from bars_cache import load_symbol_bars
        from mt5_service import SUPPORTED_SYMBOLS, resolve_wildcard_symbol, WILDCARD_SYMBOLS
        
        status = {}
        for sym in SUPPORTED_SYMBOLS:
            # Resolve wildcard
            resolved = sym
            if sym in WILDCARD_SYMBOLS:
                resolved = resolve_wildcard_symbol(WILDCARD_SYMBOLS[sym]) or sym
                
            bars = load_symbol_bars(resolved)
            if bars:
                times = [int(b["time"]) for b in bars]
                days = (max(times) - min(times)) // (24 * 3600)
                status[sym] = {
                    "count": len(bars),
                    "days": days,
                    "latest": datetime.fromtimestamp(max(times)).strftime("%Y-%m-%d"),
                }
        
        # Get snapshots count
        store = _load_flow_snapshots()
        snapshots = store.get("snapshots", [])
        
        return jsonify({
            "cache": status,
            "snapshots_count": len(snapshots),
            "updated_at": datetime.utcnow().isoformat() # Approx
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/macro/states", methods=["GET"])
def get_macro_states():
    """Calculate current macro states and scores"""
    try:
        from macro_engine import MacroEngine
        from mt5_service import get_mt5_connection
        
        date_str = request.args.get("date")
        
        mt5_conn = get_mt5_connection()
        if not mt5_conn:
            return jsonify({"error": "MT5 not connected"}), 503
            
        engine = MacroEngine(mt5_conn)
        # Calculate for specific date or default (today)
        result = engine.calculate(date_str)
        
        # Auto-sync to history and override USTEC
        _save_macro_to_history(result)
        
        from dataclasses import asdict
        return jsonify(asdict(result)), 200
    except Exception as e:
        _log.error(f"Error calculating macro states: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


def _save_macro_to_history(res):
    """Save a MacroResult to the snapshot store and override USTEC + individual factors"""
    try:
        store = _load_flow_snapshots()
        snapshots = store.get("snapshots", [])
        
        # Find or create snapshot for this date
        existing = next((s for s in snapshots if str(s.get("snapshot_date")) == res.date), None)
        if not existing:
            existing = {
                "snapshot_date": res.date,
                "updatedAt": datetime.utcnow().isoformat(),
                "rows": []
            }
            snapshots.append(existing)
            
        rows = existing.get("rows", [])
        updated_at = datetime.utcnow().isoformat()
        
        # 1. Override USTEC (Final Score)
        rows = [r for r in rows if not (r.get("asset") == "USTEC" and r.get("flowType") == "MACRO_SYNC")]
        rows.append({
            "id": f"macro_USTEC_{res.date}",
            "asset": "USTEC",
            "date": res.date,
            "flowType": "MACRO_SYNC",
            "strength": res.final_score,
            "updatedAt": updated_at,
        })
        
        # 2. Save individual factors
        for sym, factor in res.factors.items():
            rows = [r for r in rows if not (r.get("asset") == sym and r.get("flowType") == "MACRO_FACTOR")]
            rows.append({
                "id": f"macro_{sym}_{res.date}",
                "asset": sym,
                "date": res.date,
                "flowType": "MACRO_FACTOR",
                "strength": factor.score,
                "direction": factor.daily_state.direction,
                "speed": factor.daily_state.speed,
                "updatedAt": updated_at,
            })
            
        existing["rows"] = rows
        existing["updatedAt"] = updated_at
        store["snapshots"] = snapshots
        store["updatedAt"] = updated_at
        _save_flow_snapshots(store)
        _log.info(f"Auto-synced macro and factors for {res.date}")
    except Exception as e:
        _log.error(f"Failed to auto-sync macro history: {e}")


@app.route("/api/macro/history", methods=["GET"])
def get_macro_history():
    """Get calculated macro history from snapshots for all assets"""
    try:
        store = _load_flow_snapshots()
        snapshots = store.get("snapshots", [])
        
        history = {}
        for s in snapshots:
            date = s.get("snapshot_date")
            rows = s.get("rows", [])
            
            day_data = {}
            for r in rows:
                if r.get("flowType") in ["MACRO_SYNC", "MACRO_FACTOR"]:
                    day_data[r.get("asset")] = {
                        "strength": r.get("strength", 0),
                        "direction": r.get("direction"),
                        "speed": r.get("speed")
                    }
            if day_data:
                history[date] = day_data
        
        return jsonify(history), 200
    except Exception as e:
        _log.error(f"Error fetching macro history: {e}")
        return jsonify({"error": str(e)}), 500


from threading import Lock

# Global lock for macro sync to prevent parallel execution
_macro_sync_lock = Lock()

@app.route("/api/macro/sync", methods=["POST"])
def sync_macro_history():
    """Sync macro history for requested days with locking"""
    if not _macro_sync_lock.acquire(blocking=False):
        return jsonify({
            "error": "A sync process is already running. Please wait.",
            "status": "BUSY"
        }), 429
        
    try:
        data = request.get_json() or {}
        days = int(data.get("days", 30))
        
        mt5_conn = get_mt5_connection()
        if not mt5_conn:
            return jsonify({"error": "MT5 not connected"}), 503
            
        # 1. Run prefetch (update H1 cache)
        from fetch_flow_mt5 import main as prefetch_main
        import sys
        
        old_argv = sys.argv
        sys.argv = ["fetch_flow_mt5.py", "--days", str(days), "--symbols", "XAUUSD,UST10Y,DXY,VIX,XTIUSD"]
        try:
            prefetch_main()
        finally:
            sys.argv = old_argv
            
        # 2. Run Macro Engine calculation for the range
        engine = MacroEngine(mt5_conn)
        results = engine.calculate_range(days)
        
        # 3. Merge results into flow_strength_history.json
        for res in results:
            _save_macro_to_history(res)
            
        return jsonify({
            "ok": True,
            "days_requested": days,
            "results_count": len(results)
        }), 200
        
    except Exception as e:
        _log.error(f"Error during macro sync: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        _macro_sync_lock.release()


if __name__ == "__main__":
    port = int(os.environ.get("FLOW_TRACKING_PORT", "5057"))
    app.run(host="127.0.0.1", port=port, debug=False)


# =============================================================================
# MACRO ENGINE API ENDPOINTS
# =============================================================================

@app.get("/api/macro/states")
def macro_states():
    """
    Get macro states for all 5 symbols.
    Returns Direction, Speed, ΔSpeed for each symbol.
    """
    try:
        from macro_engine import MacroEngine
        from mt5_service import get_mt5_connection
        
        mt5_conn = get_mt5_connection()
        if not mt5_conn:
            return jsonify({"error": "MT5 not connected"}), 503
        
        engine = MacroEngine(mt5_conn)
        result = engine.calculate()
        
        # Build response
        factors_data = {}
        for symbol, factor in result.factors.items():
            ds = factor.daily_state
            factors_data[symbol] = {
                "date": ds.date,
                "direction": ds.direction,
                "speed": ds.speed,
                "delta_speed": ds.delta_speed,
                "range_norm": round(ds.range_norm, 2),
                "return_pct": round(ds.return_pct, 2),
                "delta_ratio": round(ds.delta_ratio, 2),
                "transition": factor.transition,
                "factor_state": factor.factor_state,
                "persistence": factor.persistence,
                "score": round(factor.score, 2),
            }
        
        return jsonify({
            "date": result.date,
            "factors": factors_data,
            "system_acceleration": result.system_acceleration,
            "absorption": result.absorption,
            "fragility": result.fragility,
            "deleveraging": result.deleveraging,
            "core_cluster": round(result.core_cluster, 2),
            "total_raw": round(result.total_raw, 2),
            "normalized": round(result.normalized, 2),
            "final_score": result.final_score,
            "ustec_strength": result.ustec_strength,
        }), 200
    except Exception as e:
        _log.error(f"Macro states error: {e}", exc_info=True)
        return jsonify({"error": f"Macro states failed: {e}"}), 500


@app.get("/api/macro/state/<symbol>")
def macro_state_symbol(symbol: str):
    """
    Get macro state for a specific symbol.
    """
    try:
        from macro_engine import MacroEngine
        from mt5_service import get_mt5_connection
        
        mt5_conn = get_mt5_connection()
        if not mt5_conn:
            return jsonify({"error": "MT5 not connected"}), 503
        
        engine = MacroEngine(mt5_conn)
        result = engine.calculate()
        
        factor = result.factors.get(symbol.upper())
        if not factor:
            return jsonify({"error": f"Symbol {symbol} not found"}), 404
        
        ds = factor.daily_state
        return jsonify({
            "symbol": symbol.upper(),
            "date": ds.date,
            "direction": ds.direction,
            "speed": ds.speed,
            "delta_speed": ds.delta_speed,
            "range_norm": round(ds.range_norm, 2),
            "return_pct": round(ds.return_pct, 2),
            "delta_ratio": round(ds.delta_ratio, 2),
            "transition": factor.transition,
            "factor_state": factor.factor_state,
            "pressure_state": factor.pressure_state,
            "persistence": factor.persistence,
            "base_impact": factor.base_impact,
            "delta_modifier": factor.delta_modifier,
            "impact_adj": round(factor.impact_adj, 2),
            "weight": factor.weight,
            "score": round(factor.score, 2),
        }), 200
    except Exception as e:
        _log.error(f"Macro state error: {e}", exc_info=True)
        return jsonify({"error": f"Macro state failed: {e}"}), 500


@app.post("/api/macro/calculate")
def macro_calculate():
    """
    Trigger macro calculation and optionally override USTEC strength.
    """
    try:
        from macro_engine import MacroEngine
        from mt5_service import get_mt5_connection
        
        mt5_conn = get_mt5_connection()
        if not mt5_conn:
            return jsonify({"error": "MT5 not connected"}), 503
        
        engine = MacroEngine(mt5_conn)
        result = engine.calculate()
        
        return jsonify({
            "date": result.date,
            "final_score": result.final_score,
            "ustec_strength": result.ustec_strength,
            "absorption": result.absorption,
            "fragility": result.fragility,
            "system_acceleration": result.system_acceleration,
        }), 200
    except Exception as e:
        _log.error(f"Macro calculate error: {e}", exc_info=True)
        return jsonify({"error": f"Macro calculate failed: {e}"}), 500


@app.post("/api/macro/override-strength")
def macro_override_strength():
    """
    Override USTEC strength in flow_strength_history.json.
    Expected JSON: { "date": "YYYY-MM-DD", "score": float }
    """
    try:
        payload = request.get_json(silent=True) or {}
        date_str = payload.get("date", datetime.now().strftime("%Y-%m-%d"))
        score = float(payload.get("score", 0))
        
        from macro_engine import MacroEngine
        from mt5_service import get_mt5_connection
        
        mt5_conn = get_mt5_connection()
        if not mt5_conn:
            return jsonify({"error": "MT5 not connected"}), 503
        
        # Calculate if no score provided
        if score == 0:
            engine = MacroEngine(mt5_conn)
            result = engine.calculate(date_str)
            score = result.final_score
        
        # Load existing strength history
        store = _load_flow_snapshots()
        snapshots = store.get("snapshots", [])
        
        # Find or create snapshot for date
        existing_idx = None
        for i, s in enumerate(snapshots):
            if str(s.get("snapshot_date")) == date_str:
                existing_idx = i
                break
        
        # Update USTEC strength in rows
        if existing_idx is not None:
            rows = snapshots[existing_idx].get("rows", [])
            updated = False
            for row in rows:
                if row.get("asset") == "USTEC":
                    row["strength"] = score
                    updated = True
            if not updated:
                rows.append({
                    "id": f"macro_{date_str}",
                    "asset": "USTEC",
                    "date": date_str,
                    "flowType": "MACRO_OVERRIDE",
                    "strength": score,
                    "updatedAt": datetime.utcnow().isoformat(),
                })
            snapshots[existing_idx]["rows"] = rows
        else:
            # Create new snapshot
            snapshots.append({
                "snapshot_date": date_str,
                "saved_at": datetime.utcnow().isoformat(),
                "rows": [{
                    "id": f"macro_{date_str}",
                    "asset": "USTEC",
                    "date": date_str,
                    "flowType": "MACRO_OVERRIDE",
                    "strength": score,
                    "updatedAt": datetime.utcnow().isoformat(),
                }],
                "rows_count": 1,
            })
        
        # Save
        out = {
            "updated_at": datetime.utcnow().isoformat(),
            "snapshots": snapshots,
        }
        _save_flow_snapshots(out)
        
        _log.info(f"Override USTEC strength for {date_str}: {score}")
        return jsonify({
            "ok": True,
            "date": date_str,
            "score": score,
            "message": f"USTEC strength updated to {score}",
        }), 200
    except Exception as e:
        _log.error(f"Override strength error: {e}", exc_info=True)
        return jsonify({"error": f"Override failed: {e}"}), 500

