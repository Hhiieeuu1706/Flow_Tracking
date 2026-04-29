"""
Macro Engine - Complete Flow Analysis System
Implements: State Engine → Pressure Engine → Portfolio Engine → Flow Engine
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
import logging

_log = logging.getLogger("flow_tracking.macro_engine")

# =============================================================================
# DATA TYPES
# =============================================================================

class Direction:
    UP = "↑"
    DOWN = "↓"
    FLAT = "→"


class Speed:
    SLOW = "S"
    MODERATE = "M"
    FAST = "F"


class DeltaSpeed:
    UP = "↑"
    STABLE = "→"
    DOWN = "↓"
    EXHAUSTED = "↓↓"


class TransitionState:
    ACCELERATION = "Acceleration"
    STABLE = "Stable"
    WEAKENING = "Weakening"
    EXHAUSTION = "Exhaustion"


class PressureType:
    CORE = "Core"
    EVENT = "Event"
    GAMMA = "Gamma"
    FORCED = "Forced"


@dataclass
class DailyState:
    """Daily OHLC state for a symbol"""
    date: str
    symbol: str
    open: float = 0
    high: float = 0
    low: float = 0
    close: float = 0
    range_val: float = 0
    
    # Calculated fields
    direction: str = "→"  # ↑, ↓, →
    speed: str = "M"      # S, M, F
    delta_speed: str = "→"  # ↑, →, ↓, ↓↓
    range_norm: float = 0
    
    # Raw values for debugging
    return_pct: float = 0
    delta_ratio: float = 0


@dataclass
class FactorState:
    """State of a single factor (USD, Rates, Oil, etc.)"""
    symbol: str
    daily_state: DailyState
    
    # Engine outputs
    transition: str = ""  # Acceleration, Stable, Weakening, Exhaustion
    factor_state: str = ""  # Build, Stable, Decay, Exhaustion
    pressure_state: str = ""  # Build, Stable, Decay, Exhaustion
    persistence: float = 0
    
    # Flow Engine inputs
    base_impact: float = 0
    delta_modifier: float = 1.0
    impact_adj: float = 0
    weight: float = 1.5
    score: float = 0


@dataclass
class MacroResult:
    """Final macro result for a day"""
    date: str
    
    # Factor states
    factors: dict[str, FactorState] = field(default_factory=dict)
    
    # System-level
    system_acceleration: str = ""  # Accelerating, Stable, Decelerating
    absorption: bool = False
    fragility: bool = False
    deleveraging: bool = False
    
    # Flow Engine outputs
    core_cluster: float = 0
    total_raw: float = 0
    normalized: float = 0
    final_score: float = 0
    
    # USTEC strength to override
    ustec_strength: float = 0


# =============================================================================
# DATA FETCHER
# =============================================================================

class DataFetcher:
    """Fetch H1 data and aggregate to daily OHLC"""
    
    def __init__(self, mt5_service):
        from mt5_service import WILDCARD_SYMBOLS
        self.mt5 = mt5_service
        self.SYMBOLS_MAP = WILDCARD_SYMBOLS
    
    def fetch_and_aggregate(self, symbol: str, days_back: int = 7, end_date: datetime = None) -> list[DailyState]:
        """Fetch H1 data and aggregate to daily states"""
        from mt5_service import fetch_h1_bars, resolve_wildcard_symbol, Bar
        
        # Resolve wildcard symbol
        pat = self.SYMBOLS_MAP.get(symbol, symbol)
        resolved = resolve_wildcard_symbol(pat)
        if not resolved:
            _log.warning(f"Cannot resolve {pat}")
            return []
        
        # Fetch H1 bars
        if end_date is None:
            end_date = datetime.now()
        start_time = end_date - timedelta(days=days_back + 10) # Overfetch for weekend merging
        
        try:
            bars = fetch_h1_bars(resolved, start_time, end_date)
        except Exception as e:
            _log.error(f"Error fetching {resolved}: {e}")
            return []
        
        if not bars:
            return []
        
        # Aggregate to daily (cutoff: 00:00 UTC)
        return self._aggregate_bars(bars)
    
    def _aggregate_bars(self, bars: list) -> list[DailyState]:
        """Aggregate H1 bars to daily OHLC with Weekend Consolidation"""
        from mt5_service import Bar
        
        if not bars:
            return []
        
        # Group bars by date (Trading Day logic: Sat/Sun/Early Mon -> Friday)
        daily_bars: dict[str, list[Bar]] = {}
        for bar in bars:
            # We use local time for weekday check to match MT5 server days better
            # But we normalize to UTC for the date key
            dt = datetime.utcfromtimestamp(bar.time)
            
            # Weekend Consolidation Logic (Aggressive):
            # Saturday (5) -> Move to Friday (-1 day)
            # Sunday (6) -> Move to Friday (-2 days)
            # Monday (0) before 10:00 AM UTC -> Move to Friday (-3 days)
            # This captures Sunday gap and early Asian session into Friday move.
            
            w = dt.weekday()
            if w == 5: # Sat
                dt = dt - timedelta(days=1)
            elif w == 6: # Sun
                dt = dt - timedelta(days=2)
            elif w == 0 and dt.hour < 10: # Early Mon
                dt = dt - timedelta(days=3)
                
            date_key = dt.strftime("%Y-%m-%d")
            daily_bars.setdefault(date_key, []).append(bar)
        
        # Aggregate each day
        states = []
        for date_key in sorted(daily_bars.keys()):
            day_bars = daily_bars[date_key]
            # Skip very low activity days (holidays or partial segments)
            if len(day_bars) < 3: 
                continue
            
            o = day_bars[0].open
            c = day_bars[-1].close
            h = max(b.high for b in day_bars)
            l = min(b.low for b in day_bars)
            
            # Calculate return
            return_pct = ((c - o) / o * 100) if o != 0 else 0
            
            state = DailyState(
                date=date_key,
                symbol="",
                open=float(o),
                high=float(h),
                low=float(l),
                close=float(c),
                range_val=float(h - l),
                return_pct=return_pct
            )
            states.append(state)
        
        return states


# =============================================================================
# STATE CALCULATOR
# =============================================================================

class StateCalculator:
    """Calculate Direction, Speed, ΔSpeed using quantile-based method"""
    
    EPSILON = 0.15  # 15% of ATR for direction threshold
    
    def calculate(self, daily_states: list[DailyState]) -> list[DailyState]:
        """Calculate all state fields for daily states"""
        if len(daily_states) < 6:
            return daily_states
        
        # Calculate for each day (starting from day 5, need 5 days history)
        for i in range(5, len(daily_states)):
            history = daily_states[i-5:i]  # 5 days before
            current = daily_states[i]
            
            # 1. Direction
            current.direction = self._calc_direction(current, history)
            
            # 2. Speed (quantile-based)
            current.speed = self._calc_speed(current, history)
            
            # 3. ΔSpeed (ratio method)
            current.delta_speed = self._calc_delta_speed(current, history)
            
            # 4. Range normalized
            ranges = [s.range_val for s in history]
            median_range = sorted(ranges)[2]  # Median of 5
            current.range_norm = current.range_val / median_range if median_range > 0 else 1.0
        
        return daily_states
    
    def _calc_direction(self, current: DailyState, history: list[DailyState]) -> str:
        """Calculate direction (Simple UP/DOWN)"""
        # Price change in units
        price_change = current.close - current.open
        
        if price_change >= 0:
            return Direction.UP
        else:
            return Direction.DOWN

    def _calc_speed(self, current: DailyState, history: list[DailyState]) -> str:
        """Calculate speed using quantile (README: FAST > p70, SLOW < p30)"""
        ranges = [s.range_val for s in history]
        sorted_ranges = sorted(ranges)
        
        p30 = sorted_ranges[1]  # ~30%
        p70 = sorted_ranges[3]  # ~70%
        
        r = current.range_val
        if r < p30:
            return Speed.SLOW
        elif r > p70:
            return Speed.FAST
        else:
            return Speed.MODERATE

    def _calc_delta_speed(self, current: DailyState, history: list[DailyState]) -> str:
        """Calculate ΔSpeed using ratio method (README boundaries)"""
        ranges = [s.range_val for s in history]
        median_range = sorted(ranges)[2]
        
        if median_range == 0:
            return DeltaSpeed.STABLE
        
        ratio = current.range_val / median_range
        current.delta_ratio = ratio
        
        if ratio > 1.2:
            return DeltaSpeed.UP
        elif ratio >= 0.8:
            return DeltaSpeed.STABLE
        elif ratio >= 0.6:
            return DeltaSpeed.DOWN
        else:
            return DeltaSpeed.EXHAUSTED


# =============================================================================
# STATE ENGINE
# =============================================================================

class StateEngine:
    """State Engine - Transition Classification"""
    
    def process(self, factor: FactorState) -> FactorState:
        """Process factor state using transitions from README"""
        ds = factor.daily_state.delta_speed
        direction = factor.daily_state.direction
        
        # Transition Classification
        if ds == DeltaSpeed.UP:
            factor.transition = TransitionState.ACCELERATION
            factor.factor_state = "Build"
        elif ds == DeltaSpeed.STABLE:
            factor.transition = TransitionState.STABLE
            factor.factor_state = "Stable"
        elif ds == DeltaSpeed.DOWN:
            factor.transition = TransitionState.WEAKENING
            factor.factor_state = "Decay"
        else: # EXHAUSTED
            factor.transition = TransitionState.EXHAUSTION
            factor.factor_state = "Exhaustion"
            
        return factor


# =============================================================================
# PRESSURE ENGINE
# =============================================================================

class PressureEngine:
    """Pressure Engine - Market Health (Absorption, Fragility, Deleveraging)"""
    
    CORE_SYMBOLS = ["DXY", "UST10Y", "XTIUSD"]
    
    def process(self, factors: dict[str, FactorState], result: MacroResult) -> MacroResult:
        """Process all factors for pressure detection using README Section 4.2"""
        
        # 1. Detect Conflict
        usd = factors.get("DXY")
        rates = factors.get("UST10Y")
        usd_rates_conflict = False
        if usd and rates and usd.daily_state.direction != Direction.FLAT and rates.daily_state.direction != Direction.FLAT:
            usd_rates_conflict = usd.daily_state.direction != rates.daily_state.direction
            
        # 2. Core ΔSpeed Deterioration
        weak_count = 0
        for sym in self.CORE_SYMBOLS:
            f = factors.get(sym)
            if f and f.daily_state.delta_speed in [DeltaSpeed.DOWN, DeltaSpeed.EXHAUSTED]:
                weak_count += 1
                
        # 3. Volatility not expanding
        vix = factors.get("VIX")
        vol_not_expanding = vix and vix.daily_state.delta_speed != DeltaSpeed.UP
        
        # Absorption Detection (≥ 2 conditions)
        conditions = 0
        if usd_rates_conflict: conditions += 1
        if weak_count >= 2: conditions += 1
        if vol_not_expanding: conditions += 1
        result.absorption = (conditions >= 2)
        
        # Deleveraging: USD ↑ + Vol ↑
        usd_up = usd and usd.daily_state.direction == Direction.UP
        vol_up = vix and vix.daily_state.direction == Direction.UP
        result.deleveraging = (usd_up and vol_up)
        
        # Fragility: Deterioration across assets
        result.fragility = (weak_count >= 2)
        
        return result


# =============================================================================
# PORTFOLIO ENGINE
# =============================================================================

class PortfolioEngine:
    """Portfolio Pressure Engine (Persistence & System State)"""
    
    PERSISTENCE = {
        DeltaSpeed.UP: 1.0,
        DeltaSpeed.STABLE: 0.7,
        DeltaSpeed.DOWN: 0.4,
        DeltaSpeed.EXHAUSTED: 0.2,
    }
    
    def process(self, factors: dict[str, FactorState], result: MacroResult) -> MacroResult:
        """Calculate persistence and system acceleration"""
        for sym, factor in factors.items():
            factor.persistence = self.PERSISTENCE.get(factor.daily_state.delta_speed, 0.7)
            
        # System Acceleration
        up_count = 0
        down_count = 0
        for sym in ["DXY", "UST10Y", "XTIUSD"]:
            f = factors.get(sym)
            if f:
                if f.daily_state.delta_speed == DeltaSpeed.UP: up_count += 1
                elif f.daily_state.delta_speed in [DeltaSpeed.DOWN, DeltaSpeed.EXHAUSTED]: down_count += 1
        
        if up_count > down_count: result.system_acceleration = "Accelerating"
        elif down_count > up_count: result.system_acceleration = "Decelerating"
        else: result.system_acceleration = "Stable"
        
        return result


# =============================================================================
# FLOW ENGINE
# =============================================================================

class FlowEngine:
    """Flow Engine - Complete Score Calculation (README Step 8.14)"""
    
    # 8.1 Base Impact Mapping (README 4.1)
    BASE_IMPACT = {
        "DXY": {Direction.UP: -1, Direction.DOWN: +1, Direction.FLAT: 0},
        "UST10Y": {Direction.UP: +1, Direction.DOWN: -1, Direction.FLAT: 0},
        "XTIUSD": {Direction.UP: -1, Direction.DOWN: +1, Direction.FLAT: 0},
        "XAUUSD": {Direction.UP: +0.5, Direction.DOWN: -0.5, Direction.FLAT: 0},
        "VIX": {Direction.UP: 0, Direction.DOWN: 0, Direction.FLAT: 0},
    }
    
    # 8.2 ΔSpeed Modifier (README 4.2 / Promt 3.5)
    DELTA_MODIFIER = {
        DeltaSpeed.UP: 1.2,
        DeltaSpeed.STABLE: 1.0,
        DeltaSpeed.DOWN: 0.7,
        DeltaSpeed.EXHAUSTED: 0.5,
    }
    
    # NEW: Speed Modifier (Promt 3.5 Line 221)
    SPEED_MODIFIER = {
        Speed.FAST: 1.5,
        Speed.MODERATE: 1.0,
        Speed.SLOW: 0.5,
    }
    
    WEIGHTS = {
        "DXY": 1.5,
        "UST10Y": 1.5,
        "XTIUSD": 0.6,
        "XAUUSD": 0.8,
        "VIX": 0,
    }
    
    def calculate(self, factors: dict[str, FactorState], result: MacroResult) -> MacroResult:
        """Run complete Flow Engine formula per Promt 3.5 (V7.3)"""
        
        # Step 1: Calculate individual factor scores (Weighted)
        for symbol, factor in factors.items():
            ds = factor.daily_state.delta_speed
            dir_val = factor.daily_state.direction
            speed_val = factor.daily_state.speed
            
            # 8.1 Base Impact
            base = self.BASE_IMPACT.get(symbol, {}).get(dir_val, 0)
            
            # Special Rule (README 4.1): Rates Latent cap
            if symbol == "UST10Y" and dir_val == Direction.UP and ds == DeltaSpeed.STABLE:
                base = min(base, 0.5)
                
            factor.base_impact = base
            
            # ΔSpeed Modifier (1.2, 1.0, 0.7, 0.5)
            factor.delta_modifier = self.DELTA_MODIFIER.get(ds, 1.0)
            
            # Speed Modifier (1.5, 1.0, 0.5)
            speed_mod = self.SPEED_MODIFIER.get(speed_val, 1.0)
            
            factor.impact_adj = factor.base_impact * factor.delta_modifier
            factor.weight = self.WEIGHTS.get(symbol, 1.0)
            
            # Final Score per factor: (Impact * ΔSpeed_mod) * Speed_mod * Weight * Persistence
            factor.score = factor.impact_adj * speed_mod * factor.weight * factor.persistence
        
        # Step 2: Core Cluster Rule (Promt 3.5: MAX magnitude if same impact sign)
        result.core_cluster = self._calc_core_cluster(factors)
        
        # Step 3: Raw Total (Cluster + Gold)
        gold = factors.get("XAUUSD")
        gold_score = gold.score if gold else 0
        result.total_raw = result.core_cluster + gold_score
        
        # Step 4: Absorption Decay (Promt 3.5: x0.5 if flag active)
        if result.absorption:
            result.total_raw *= 0.5
            
        # Step 5: Normalization (Promt 3.5: Target range -10 to +10)
        # Normalized = (TotalRaw / 6.0) * 10.0
        result.normalized = (result.total_raw / 6.0) * 10.0
        
        # Step 6: Stability Filter (Filter out noise near 0)
        if -0.5 <= result.normalized <= 0.5:
            result.final_score = 0
        else:
            result.final_score = result.normalized
            
        # Step 7: Non-Directional Compression (Promt 3.5 Line 127)
        # IF ΔSpeed ↓↓ across core -> Final Score MUST ∈ [-2, +2]
        exhausted_count = sum(
            1 for sym in ["DXY", "UST10Y", "XTIUSD"]
            if factors.get(sym) and factors[sym].daily_state.delta_speed == DeltaSpeed.EXHAUSTED
        )
        if exhausted_count >= 2:
            result.final_score = max(-2, min(2, result.final_score))
            _log.info(f"Systemic Compression active (Exhaustion={exhausted_count})")
            
        # Clamp to final range and round
        result.final_score = max(-10, min(10, result.final_score))
        result.final_score = round(result.final_score, 2)
        
        return result
    
    def _calc_core_cluster(self, factors: dict[str, FactorState]) -> float:
        """Calculate cluster pressure: if all have same IMPACT sign, take max magnitude"""
        usd = factors.get("DXY")
        rates = factors.get("UST10Y")
        oil = factors.get("XTIUSD")
        
        if not all([usd, rates, oil]):
            return 0
            
        # Use individual scores for cluster logic
        scores = [usd.score, rates.score, oil.score]
        
        # Check if all have the same sign (and are not zero)
        all_positive = all(s > 0 for s in scores)
        all_negative = all(s < 0 for s in scores)
        
        if all_positive or all_negative:
            # All same impact direction - return single max magnitude
            return max(scores, key=abs)
            
        # Otherwise raw sum (conflicting drivers cancel each other out)
        return sum(scores)
    
    def _apply_compression(self, factors: dict[str, FactorState], result: MacroResult) -> float:
        """Apply non-directional compression"""
        # Check if ΔSpeed ↓↓ at ≥2 core
        exhausted_count = 0
        for sym in ["DXY", "UST10Y", "XTIUSD"]:
            f = factors.get(sym)
            if f and f.daily_state.delta_speed == DeltaSpeed.EXHAUSTED:
                exhausted_count += 1
        
        # Check if all core are Latent
        all_latent = all(
            f.daily_state.delta_speed == DeltaSpeed.STABLE
            for sym, f in factors.items()
            if sym in ["DXY", "UST10Y", "XTIUSD"] and f
        )
        
        if exhausted_count >= 2 or all_latent:
            # Clamp to [-1, +1]
            return max(-1, min(1, result.total_raw))
        
        return result.total_raw


# =============================================================================
# MAIN MACRO ENGINE
# =============================================================================

class MacroEngine:
    """Main Macro Engine - orchestrates all components"""
    
    SYMBOLS = ["XAUUSD", "UST10Y", "DXY", "VIX", "XTIUSD"]
    
    def __init__(self, mt5_service):
        self.fetcher = DataFetcher(mt5_service)
        self.state_calc = StateCalculator()
        self.state_engine = StateEngine()
        self.pressure_engine = PressureEngine()
        self.portfolio_engine = PortfolioEngine()
        self.flow_engine = FlowEngine()
    
    def calculate(self, date: str = None) -> MacroResult:
        """Calculate macro result for a date (default: today)"""
        # 1. Resolve effective date string
        effective_date = date
        if not effective_date:
            effective_date = datetime.now().strftime("%Y-%m-%d")
        
        # 2. Create the final result container immediately
        res_obj = MacroResult(date=effective_date)
        
        # 3. Handle historical target date if needed
        target_dt = None
        if date:
            try:
                target_dt = datetime.strptime(date, "%Y-%m-%d")
                target_dt = target_dt.replace(hour=23, minute=59, second=59)
            except Exception:
                pass

        # 4. Step 1: Fetch and calculate states for each symbol
        factors_map = {}
        for symbol in self.SYMBOLS:
            daily_states = self.fetcher.fetch_and_aggregate(symbol, days_back=15, end_date=target_dt)
            
            if len(daily_states) < 6:
                _log.warning(f"Insufficient data for {symbol}")
                continue
            
            # Calculate states
            daily_states = self.state_calc.calculate(daily_states)
            
            # Get latest state
            current_state = daily_states[-1]
            current_state.symbol = symbol
            
            f_state = FactorState(
                symbol=symbol,
                daily_state=current_state
            )
            
            # Process through engines
            f_state = self.state_engine.process(f_state)
            factors_map[symbol] = f_state
        
        res_obj.factors = factors_map
        
        # 5. Process through remaining engines
        res_obj = self.pressure_engine.process(factors_map, res_obj)
        res_obj = self.portfolio_engine.process(factors_map, res_obj)
        res_obj = self.flow_engine.calculate(factors_map, res_obj)
        
        # 6. Final scores
        res_obj.ustec_strength = res_obj.final_score
        _log.info(f"Macro calculation complete.")
        return res_obj

    def calculate_range(self, days: int = 360) -> list[MacroResult]:
        """
        Calculate macro results for a range of days (Optimized)
        Fetches full range of data first to avoid redundant MT5 calls.
        """
        _log.info(f"Starting optimized range calculation for {days} days...")
        results = []
        
        # 1. Fetch ALL data for all symbols first
        total_fetch_days = days + 15
        all_data: dict[str, dict[str, DailyState]] = {}
        
        for symbol in self.SYMBOLS:
            _log.info(f"Prefetching {total_fetch_days} days for {symbol}...")
            states_list = self.fetcher.fetch_and_aggregate(symbol, days_back=total_fetch_days)
            if states_list:
                full_states = self.state_calc.calculate(states_list)
                all_data[symbol] = {s.date: s for s in full_states}
            else:
                _log.warning(f"No data for {symbol}")
        
        # 2. Iterate and calculate
        ref_symbol = self.SYMBOLS[0]
        if ref_symbol not in all_data:
            return []
            
        all_dates = sorted(all_data[ref_symbol].keys())
        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        
        # STRICT RULE: Skip the latest date as it's likely incomplete/live
        target_dates = [d for d in all_dates if d < today_str]
        
        # Keep only requested window
        target_dates = target_dates[-days:] if days > 0 else target_dates
        
        for date_str in target_dates:
            factors = {}
            for symbol in self.SYMBOLS:
                symbol_data = all_data.get(symbol, {})
                day_state = symbol_data.get(date_str)
                if not day_state: continue
                
                # Check history context
                sorted_sym_dates = sorted(symbol_data.keys())
                try:
                    idx = sorted_sym_dates.index(date_str)
                    if idx < 5: continue
                except ValueError: continue
                
                factor = FactorState(symbol=symbol, daily_state=day_state)
                factor = self.state_engine.process(factor)
                factors[symbol] = factor
            
            if not factors: continue
                
            result = MacroResult(date=date_str, factors=factors)
            result = self.pressure_engine.process(factors, result)
            result = self.portfolio_engine.process(factors, result)
            result = self.flow_engine.calculate(factors, result)
            result.ustec_strength = result.final_score
            
            results.append(result)
            _log.info(f"Macro result for {date_str}: score={result.final_score}")
            
        _log.info(f"Range calculation complete. Generated {len(results)} results.")
        return results