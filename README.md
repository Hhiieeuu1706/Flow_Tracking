# Macro State Input – Structured Framework

## Overview
This file tracks the daily state of core macro assets in a structured format.  
It serves as the input layer for the system.

## Purpose
- Capture current market behavior (not opinion)  
- Standardize inputs across all modules (P1 → P3.3)  
- Enable consistent and repeatable analysis  

---

## Core Drivers
The system focuses on key macro assets:

- **DXY (USD)** → global liquidity  
- **US10Y (Rates)** → tightening vs easing  
- **VIX (Volatility)** → risk conditions  
- **Gold (GC)** → defensive behavior  
- **Oil (Energy)** → inflation pressure  

---

## Input Structure

Each asset is described using four components:

- **Direction**
- **Speed**
- **ΔSpeed (critical)**
- **Control**

---

## Definitions

### Direction
Represents the current price movement:

- ↑ = rising  
- ↓ = falling  
- → = sideways  

→ reflects **current move only**

---

### Speed
Measures the strength of the move:

- Slow  
- Moderate  
- Fast  

---

### ΔSpeed (Critical Signal)
Captures change in momentum:

- ↑ = strengthening  
- → = stable  
- ↓ = weakening  
- ↓↓ = continuous weakening  

→ Used to detect **transitions and potential turning points**

---

### Control
Indicates structural dominance:

- **Demand** = buyers in control  
- **Supply** = sellers in control  
- **Neutral** = no clear dominance  

→ reflects **structural context (not current move)**

---

## Key Principles

- **Direction** = what price is doing now  
- **Control** = who is in control structurally  
- **ΔSpeed** = most important signal (momentum change)  

---

## Example
