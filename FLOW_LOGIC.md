What this is

A deterministic macro framework to measure market pressure (buy vs sell imbalance) — not price direction.

Assets Covered (Core Drivers)

The system is built on cross-asset macro relationships:

USD (DXY) → global liquidity / funding
Rates (US10Y / Real Yields) → tightening vs easing
Volatility (VIX) → leverage / risk conditions
Energy (Oil) → inflation pressure
Gold (GC) → hedge / defensive reaction

👉 These form the core pressure engine

System Structure (4 Prompts)
Prompt 1 — Macro State
Encode market state (Direction, Speed, ΔSpeed, Control)
Prompt 2 — Pressure Engine
Convert state → pressure (build / decay / exhaustion)
Prompt 3 — Regime Engine
Classify structure (build / latent / absorption / compression)
Prompt 3.3 — Flow Scoring
Quantify pressure → score (-10 → +10)
Core Theory
1. Pressure > Price

Markets move because of pressure imbalance, not price patterns.

2. Transition > Trend

The system focuses on change, not direction.

ΔSpeed ↓ → weakening
ΔSpeed ↓↓ → exhaustion (early reversal)
ΔSpeed ↑ → strengthening
3. Structure vs Move
Direction = current move
Control = structural dominance

Example:

↑ + Supply → weak / counter-trend move
4. Absorption

When pressure fails to transmit:

conflicting core drivers
weak follow-through
ΔSpeed deterioration

→ signal becomes fragile / non-persistent

Data Philosophy

Uses:

Structured manual input
Official macro data

Avoids:

News
Price action
Indicators

👉 Manual input = ground truth

Multi-AI (Anti-Bias Layer)

Run 3 AIs in parallel on the same input:

3/3 agree → High confidence
2/3 agree → Medium
Conflict → Reject / review

→ reduces subjectivity and inconsistency

Output
Pressure (buy vs sell imbalance)
Regime (build / absorption / compression)
Score (-10 → +10)