"""
Flow Check Analysis Engine for ICMarkets MT5.
Implements the comprehensive flow analysis rule engine based on FINAL PRODUCTION READY specs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

from mt5_service import (
    fetch_h1_bars,
    resolve_wildcard_symbol,
    Bar,
    Mt5Error,
)

_log = logging.getLogger("flow_tracking.flow_check")

@dataclass
class AssetMetrics:
    """Calculated metrics for a single asset across 3 daily sessions."""
    asset: str
    change_t0: float
    change_t1: float
    change_t2: float
    open: float
    t_2h: float
    close: float
    avg_daily_move_20d: float
    core_move: float
    late_move: float
    total_move: float
    late_dominant: bool
    core_dir: int
    late_dir: int
    session_type: str
    flag_distortion: bool
    flag_acceleration: bool
    avg_change: float
    norm_strength: float
    direction: int
    accel: float
    consistency: float
    slope: float
    slope_norm: float
    impulse: float
    strength_class: str

@dataclass
class FlowCheckResult:
    """Final output of flow check analysis."""
    FlowState: str
    DominantFlow: str
    Regime: str
    Score: float
    assets: dict[str, AssetMetrics]
    alignment: int
    transmission: bool
    persistence: bool
    absorption: bool
    vol_spike: bool
    conflict: bool

def sign(x: float) -> int:
    if x < 0: return -1
    if x > 0: return 1
    return 0

def calculate_asset_metrics(
    asset_name: str,
    bars_t0: list[Bar],
    bars_t1: list[Bar],
    bars_t2: list[Bar],
    avg_daily_move_20d: float,
    invert_direction: bool = False,
) -> AssetMetrics:
    def get_daily_ohlc(bars: list[Bar]) -> tuple[float, float, float, float]:
        if not bars: return 0, 0, 0, 0
        o, c = bars[0].open, bars[-1].close
        h = max(b.high for b in bars)
        l = min(b.low for b in bars)
        return float(o), float(h), float(l), float(c)

    o0, h0, l0, c0 = get_daily_ohlc(bars_t0)
    o1, h1, l1, c1 = get_daily_ohlc(bars_t1)
    o2, h2, l2, c2 = get_daily_ohlc(bars_t2)

    change_t0 = ((c0 - o0) / o0 * 100) if o0 != 0 else 0
    change_t1 = ((c1 - o1) / o1 * 100) if o1 != 0 else 0
    change_t2 = ((c2 - o2) / o2 * 100) if o2 != 0 else 0

    # T_2h is the marker 3 hours before close (index -4)
    if len(bars_t0) >= 4:
        t_2h = float(bars_t0[-4].close)
    else:
        t_2h = float(bars_t0[0].close)

    # II. SESSION MODULE
    core_move = (t_2h - o0) / o0 if o0 != 0 else 0
    late_move = (c0 - t_2h) / t_2h if t_2h != 0 else 0
    total_move = (c0 - o0) / o0 if o0 != 0 else 0
    
    # Sign of moves
    core_dir, late_dir = sign(core_move), sign(late_move)
    
    # Late Dominant if LateMove has higher magnitude than CoreMove
    late_dominant = bool(abs(late_move) > abs(core_move))

    if late_dominant and core_dir != late_dir: session_type = "DISTORTION"
    elif late_dominant and core_dir == late_dir: session_type = "ACCELERATION"
    else: session_type = "NORMAL"

    flag_distortion = bool(session_type == "DISTORTION")
    flag_acceleration = bool(session_type == "ACCELERATION")

    # III. NORMALIZATION ENGINE
    avg_change = (abs(change_t0) + abs(change_t1) + abs(change_t2)) / 3.0
    norm_strength = float(avg_change / avg_daily_move_20d if avg_daily_move_20d != 0 else 0)

    # Direction is determined ONLY by T0 as requested.
    if norm_strength < 0.2:
        direction = 0
    else:
        direction = sign(change_t0)

    # Note: Distortion NO LONGER zeros the direction. It only penalizes the impulse strength.
    
    if invert_direction and direction != 0: 
        direction *= -1

    accel_denom = (abs(change_t1) + abs(change_t2)) / 2.0
    accel = float(abs(change_t0) / (accel_denom + 1e-6))

    signs = [sign(change_t0), sign(change_t1), sign(change_t2)]
    pos_count = signs.count(1)
    neg_count = signs.count(-1)
    same_sign = max(pos_count, neg_count)

    if same_sign == 3: consistency = 1.0
    elif same_sign == 2: consistency = 0.7
    else: consistency = 0.4

    # IV. SLOPE + IMPULSE
    slope = (change_t0 * 0.5) + (change_t1 * 0.3) + (change_t2 * 0.2)
    slope_norm = slope / avg_daily_move_20d if avg_daily_move_20d != 0 else 0
    impulse = float(abs(slope_norm) * accel * consistency)
    impulse = min(impulse, 3.0)
    
    if flag_distortion: 
        impulse *= 0.5 # Apply penalty for late-day distortion

    if impulse > 2.0: strength_class = "EXTREME"
    elif impulse > 1.3: strength_class = "STRONG"
    elif impulse > 0.7: strength_class = "NORMAL"
    else: strength_class = "WEAK"

    return AssetMetrics(
        asset=asset_name, change_t0=float(change_t0), change_t1=float(change_t1), change_t2=float(change_t2),
        open=o0, t_2h=t_2h, close=c0, avg_daily_move_20d=float(avg_daily_move_20d),
        core_move=float(core_move), late_move=float(late_move), total_move=float(total_move),
        late_dominant=late_dominant, core_dir=core_dir, late_dir=late_dir,
        session_type=session_type, flag_distortion=flag_distortion, flag_acceleration=flag_acceleration,
        avg_change=float(avg_change), norm_strength=norm_strength, direction=direction,
        accel=accel, consistency=consistency, slope=float(slope), slope_norm=float(slope_norm),
        impulse=impulse, strength_class=strength_class
    )

def _group_sessions_from_bars(bars: list[Bar]) -> dict[str, list[Bar]]:
    sessions = {}
    for bar in bars:
        # Shift time by -7 hours to align 07:00 AM as the day start (00:00)
        key = datetime.fromtimestamp(bar.time - 25200).date().isoformat()
        sessions.setdefault(key, []).append(bar)
    return sessions

def _calculate_avg_daily_move_20d(bars: list[Bar]) -> float:
    sessions = _group_sessions_from_bars(bars)
    dates = sorted(sessions.keys())[-20:]
    moves = []
    for d in dates:
        b = sessions[d]
        if b and b[0].open != 0: moves.append(abs((b[-1].close - b[0].open) / b[0].open * 100))
    return float(sum(moves) / len(moves)) if moves else 1.0

def analyze_flow_check(cutoff_date: datetime) -> FlowCheckResult:
    # Ensure window is wide enough for the -7h shift and weekend gaps
    start_time = (cutoff_date - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    end_time = (cutoff_date + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    symbols = ["USTEC", "US30", "US500", "XAUUSD", "BTCUSD", ("UST10Y", "UST10Y_*"), ("DXY", "DXY_*"), ("VIX", "VIX_*")]
    all_bars: dict[str, list[Bar]] = {}
    for s in symbols:
        name, pat = (s[0], s[1]) if isinstance(s, tuple) else (s, s)
        res = resolve_wildcard_symbol(pat)
        if not res: continue
        try: all_bars[name] = fetch_h1_bars(res, start_time, end_time)
        except Mt5Error: continue

    if not all_bars: raise Mt5Error("No data available in MT5")
    
    asset_sessions = {n: _group_sessions_from_bars(b) for n, b in all_bars.items()}
    
    # Target dates relative to cutoff
    # Shift cutoff by -7h same as bars to get the correct 'logical' date string
    d0 = (cutoff_date - timedelta(hours=7)).date().isoformat()
    
    # We need to find d1 and d2 (previous 2 TRADING days)
    all_known_dates = sorted(set().union(*(s.keys() for s in asset_sessions.values())))
    if d0 not in all_known_dates:
        # If today has no data yet, take the most recent available date as d0
        idx = -1
        while idx >= -len(all_known_dates):
            if all_known_dates[idx] <= d0:
                d0 = all_known_dates[idx]
                break
            idx -= 1
            
    try:
        idx0 = all_known_dates.index(d0)
        if idx0 < 2: raise Mt5Error(f"Insufficient historical data before {d0}")
        d1 = all_known_dates[idx0 - 1]
        d2 = all_known_dates[idx0 - 2]
    except (ValueError, IndexError):
        raise Mt5Error(f"Date alignment failed for {d0}")

    metrics: dict[str, AssetMetrics] = {}
    for name, sessions in asset_sessions.items():
        b0, b1, b2 = sessions.get(d0, []), sessions.get(d1, []), sessions.get(d2, [])
        if not b0: continue
        avg = _calculate_avg_daily_move_20d(all_bars[name])
        try: metrics[name] = calculate_asset_metrics(name, b0, b1, b2, avg, invert_direction=(name=="UST10Y"))
        except Exception: continue

    # V. CORE STATES
    dxy, rates, vix, eq = metrics.get("DXY"), metrics.get("UST10Y"), metrics.get("VIX"), (metrics.get("US500") or metrics.get("US30") or metrics.get("USTEC"))
    btc, gold = metrics.get("BTCUSD"), metrics.get("XAUUSD")

    usd_up = bool(dxy.direction == 1) if dxy else False
    usd_down = bool(dxy.direction == -1) if dxy else False
    rates_up = bool(rates.direction == 1) if rates else False
    rates_down = bool(rates.direction == -1) if rates else False
    vol_up = bool(vix.direction == 1) if vix else False
    vol_down = bool(vix.direction == -1) if vix else False
    eq_up = bool(eq.direction == 1) if eq else False
    eq_down = bool(eq.direction == -1) if eq else False
    btc_up = bool(btc.direction == 1) if btc else False
    btc_down = bool(btc.direction == -1) if btc else False
    gold_up = bool(gold.direction == 1) if gold else False
    gold_down = bool(gold.direction == -1) if gold else False

    # VII. FLOW VALIDATION
    alignment = int(sum([usd_down, rates_down, vol_down, gold_down, eq_up]))
    transmission = bool((usd_down or rates_down) and eq_up and not (dxy.flag_distortion if dxy else False))
    persistence = True 
    
    abs_score = int(sum([vol_up, (usd_up and eq_up), (gold_up and usd_up), (rates_down and usd_up)]))
    absorption = bool(abs_score >= 2)
    vol_spike = bool((vix.impulse > 2.5 and vix.accel > 1.5) if vix else False)
    if vol_spike: transmission, persistence, absorption = False, False, True

    # VIII. REGIME DETECTOR
    if vol_spike: regime = "PANIC"
    elif usd_down and rates_down: regime = "LIQUIDITY"
    elif rates_up and not eq_up: regime = "TIGHTENING"
    elif eq_up and btc_up: regime = "SPEC"
    else: regime = "MIXED"

    # IX. SCORING
    usd_w, rates_w, vol_w, eq_w, btc_w, gold_w = 1.5, 1.5, 1.5, 1.2, 1.0, 0.8
    if regime == "PANIC": vol_w, usd_w = 2.5, 2.0
    elif regime == "LIQUIDITY": usd_w, rates_w = 1.8, 1.8
    elif regime == "SPEC": eq_w, btc_w = 2.0, 1.8

    impulses = {
        "DXY": (dxy.impulse if dxy else 0),
        "Rates": (rates.impulse if rates else 0),
        "VIX": (vix.impulse if vix else 0),
        "EQ": (eq.impulse if eq else 0),
        "BTC": (btc.impulse if btc else 0),
        "Gold": (gold.impulse if gold else 0),
    }

    usd_s = float((-1 if usd_up else 1 if usd_down else 0) * impulses["DXY"] * usd_w)
    rates_s = float((-1 if rates_up else 1 if rates_down else 0) * impulses["Rates"] * rates_w)
    vol_s = float((-1 if vol_up else 1 if vol_down else 0) * impulses["VIX"] * vol_w)
    eq_s = float((1 if eq_up else -1 if eq_down else 0) * impulses["EQ"] * eq_w)
    btc_s = float((1 if btc_up else -1 if btc_down else 0) * impulses["BTC"] * btc_w)
    gold_s = float((-1 if gold_up else 1 if gold_down else 0) * impulses["Gold"] * gold_w)
    
    score = usd_s + rates_s + vol_s + eq_s + btc_s + gold_s
    if absorption: score *= 0.5
    if not transmission: score *= 0.7
    
    major_consistency = min([m.consistency for m in [dxy, rates, eq] if m] or [1.0])
    if major_consistency < 0.7: score *= 0.6
    
    final_score = float(max(-10.0, min(10.0, score)))
    
    # X. OUTPUT
    if absorption: flow_state = "ABSORBED"
    elif alignment >= 4 and transmission and persistence: flow_state = "ACTIVE"
    elif alignment >= 3: flow_state = "LATENT"
    else: flow_state = "WEAK"

    core_sum, spec_sum = abs(usd_s + rates_s), abs(eq_s + btc_s)
    if core_sum > spec_sum: dominant = "CORE"
    elif spec_sum > abs(usd_s): dominant = "SPEC"
    elif gold_up and vol_up: dominant = "HEDGE"
    else: dominant = "MIXED"

    return FlowCheckResult(
        FlowState=flow_state, DominantFlow=dominant, Regime=regime, Score=final_score,
        assets=metrics, alignment=alignment, transmission=transmission,
        persistence=persistence, absorption=absorption, vol_spike=vol_spike, conflict=bool(abs_score >= 2)
    )
