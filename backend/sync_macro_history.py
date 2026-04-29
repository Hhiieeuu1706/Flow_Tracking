import sys
import os
import logging
from datetime import datetime
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).resolve().parent
sys.path.append(str(backend_dir))

from macro_engine import MacroEngine
from mt5_service import get_mt5_connection

def main():
    # Setup logging
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
    _log = logging.getLogger("sync_macro")

    _log.info("Starting Macro History Sync...")

    # Connect to MT5
    mt5_conn = get_mt5_connection()
    if not mt5_conn:
        _log.error("MT5 not connected. Please ensure MT5 terminal is running.")
        return 1

    try:
        engine = MacroEngine(mt5_conn)
        
        # Determine lookback: incremental by default
        base_dir = backend_dir.parent
        history_path = base_dir / "data" / "flow_strength_history.json"
        
        days = 360 # Default
        if history_path.exists():
            try:
                store = json.loads(history_path.read_text(encoding="utf-8"))
                snaps = store.get("snapshots", [])
                if snaps:
                    latest_date_str = snaps[-1].get("snapshot_date")
                    if latest_date_str:
                        latest_date = datetime.strptime(latest_date_str, "%Y-%m-%d")
                        diff = (datetime.now() - latest_date).days
                        days = max(7, diff + 5) # Sync at least 7 days, or diff + 5 for overlap safety
                        _log.info(f"Incremental sync: {days} days (latest in cache: {latest_date_str})")
            except Exception:
                pass

        _log.info(f"Calculating macro scores for last {days} days...")
        
        # Logic from sync_ustec_history (since I couldn't add it to the class easily)
        import json
        
        results = engine.calculate_range(days)
        if not results:
            _log.warning("No results calculated.")
            return 0
        
        # Determine path
        base_dir = backend_dir.parent
        history_path = base_dir / "data" / "flow_strength_history.json"
        
        store = {"updated_at": None, "snapshots": []}
        if history_path.exists():
            try:
                store = json.loads(history_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        
        snapshots = store.get("snapshots", [])
        
        for res in results:
            # 1. Find or create snapshot
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
            
            # 2. Override USTEC (Final Score)
            rows = [r for r in rows if not (r.get("asset") == "USTEC" and r.get("flowType") == "MACRO_SYNC")]
            rows.append({
                "id": f"macro_USTEC_{res.date}",
                "asset": "USTEC",
                "date": res.date,
                "flowType": "MACRO_SYNC",
                "strength": res.final_score,
                "updatedAt": updated_at,
            })
            
            # 3. Save individual factors
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

        # Sort snapshots
        snapshots.sort(key=lambda x: x.get("snapshot_date", ""))
        store["snapshots"] = snapshots
        store["updated_at"] = datetime.utcnow().isoformat()
        
        # Atomic Save
        temp_path = history_path.with_suffix(".tmp")
        try:
            temp_path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
            if history_path.exists():
                os.remove(history_path)
            os.rename(temp_path, history_path)
        except Exception as e:
            _log.error(f"Failed to save snapshots: {e}")
            if temp_path.exists(): os.remove(temp_path)
            
        _log.info(f"Successfully synced {len(results)} days of detailed Macro + USTEC history")
        return 0

    except Exception as e:
        _log.error(f"Sync failed: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    sys.exit(main())
