What this file is

This file tracks daily state of core macro assets in a structured format.

It is the input layer of the system.

Purpose
Capture current market behavior (not opinion)
Standardize inputs for all prompts (P1 → P3.3)
Enable consistent, repeatable analysis
Assets Tracked

Core drivers only:

DXY (USD)
US10Y (Rates)
VIX (Volatility)
GOLD (GC)
OIL
Input Format
Symbol	Direction	Speed	ΔSpeed	Control
Field Definitions

Direction

↑ = rising
↓ = falling
→ = sideways
→ current move only

Speed

Slow / Moderate / Fast
→ strength of the move

ΔSpeed (critical)

↑ = strengthening
→ = stable
↓ = weakening
↓↓ = continuous weakening

→ detects transition / turning point

Control

Demand = buyers in control
Supply = sellers in control
Neutral = no dominance

→ structural context (NOT current move)

Key Rules
Direction = what price is doing NOW
Control = who is in control STRUCTURALLY
ΔSpeed = most important signal
Example
Symbol	Direction	Speed	ΔSpeed	Control
DXY	↑	Slow	↓↓	Supply
VIX	↓	Moderate	↓	Supply
How to Use
Update this table daily
Feed directly into Prompt 1
Do NOT reinterpret after input
