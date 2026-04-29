# Macro Flow Tracking - Deterministic Algorithm Framework

## 1. Overview
This system implements a fully automated, deterministic macro-pressure engine. It analyzes cross-asset data (USD, Rates, Oil, Volatility, Gold) to derive a single quantitative **Flow Strength** score for USTEC. 

The core philosophy is based on **Pressure Imbalance**: Market flow is determined by the interaction of key macro drivers and their internal state transitions, not manual opinion.

---

## 2. Core Metrics
Every asset is analyzed daily using three quantitative dimensions:

### 2.1 Direction
Calculated based on daily close vs open.
- **↑ (UP)**: Positive daily candle.
- **↓ (DOWN)**: Negative daily candle.

### 2.2 Speed
Determined by the daily range quantile relative to the last 5 days.
- **F (FAST)**: Range in top 30% (> p70).
- **M (MODERATE)**: Range in middle 40%.
- **S (SLOW)**: Range in bottom 30% (< p30).

### 2.3 ΔSpeed (The Lead Signal)
The ratio of the current range to the 5-day median range.
- **↑ (Acceleration)**: Ratio > 1.2.
- **→ (Stable)**: Ratio 0.8 to 1.2.
- **↓ (Weakening)**: Ratio 0.6 to 0.8.
- **↓↓ (Exhaustion)**: Ratio < 0.6.

---

## 3. The Engine Pipeline

### 3.1 State Engine (Transitions)
Classifies the internal state of each factor:
- **Build**: Direction + Acceleration.
- **Stable**: ΔSpeed is Stable.
- **Decay**: Direction persists but Speed is Weakening.
- **Exhaustion**: ΔSpeed is Exhausted.

### 3.2 Pressure Engine (Market Health)
Detects systemic conditions across core drivers (DXY, Rates, Oil):
- **Absorption**: True if ≥ 2 conditions are met:
    1. Conflict between USD and Rates direction.
    2. ΔSpeed is Weakening/Exhausted for ≥ 2 core drivers.
    3. Volatility is not expanding (ΔSpeed ≠ ↑).
- **Fragility**: Systemic deterioration in ΔSpeed across assets.
- **Deleveraging**: High-stress condition where USD ↑ + Vol ↑.

### 3.3 Flow Engine (The Final Score)
The engine calculates a score from -10 to +10 using the following deterministic steps:

1. **Base Impact Mapping**:
   - **USD / Oil**: $\uparrow \rightarrow -1$ (Tightening), $\downarrow \rightarrow +1$ (Easing).
   - **UST10Y (Bond Price)**: $\uparrow \rightarrow +1$ (Rates DOWN/Easing), $\downarrow \rightarrow -1$ (Rates UP/Tightening).
   - **Gold**: $\uparrow \rightarrow +0.5$, $\downarrow \rightarrow -0.5$.
   - **Special Rule (Rates Latent)**: If UST10Y Price $\uparrow$ but ΔSpeed is →, impact is capped at **0.5**.

2. **Adjusted Impact**: 
   - `ImpactAdj = BaseImpact * ΔSpeedModifier`
   - Modifiers: Acceleration (1.2), Stable (1.0), Weakening (0.7), Exhaustion (0.5).

3. **Core Cluster Rule**:
   - If USD, Rates, and Oil all have the **same impact sign** (all positive or all negative), the engine applies the **Cluster Rule**: instead of summing, it takes the **Single Maximum Magnitude** of the three to represent the cluster pressure.
   - If they have conflicting signs, they are summed (cancelling each other out).

4. **Normalization**:
   - `Normalized = (TotalRaw / 6) * 10`
   - Result is clamped and rounded to a 2-decimal scale.

5. **Systemic Dampening**:
   - **Stability Filter**: Scores between -0.5 and +0.5 are zeroed out to filter noise.
   - **Exhaustion Dampening**: If ANY core driver hits ΔSpeed ↓↓, the final score is dampened by **30% (x 0.7)**.

---

## 4. Automation & Sync
- **Automatic Calculation**: The `MacroEngine` calculates these values dynamically from H1 MT5 data.
- **History Sync**: Every time the system starts via `START.bat`, it runs `sync_macro_history.py`.
- **USTEC Integration**: This script calculates the last 360 days of macro scores and automatically populates the `field strength` for **USTEC** in `flow_strength_history.json`.

## 5. UI Controls
- **📊 MACRO PANEL**: Opens a new tab with detailed tables and synchronized charts for all 5 macro assets.
- **Override USTEC**: Allows manual confirmation/push of the automated score into the session history.
- **(i) Tooltips**: Hovering over any day's "i" icon reveals the exact Direction, Speed, and ΔSpeed used for that day's calculation.
