import json
import csv
import math
from collections import defaultdict
from scipy import stats

# Load flow data
with open('flow_tracking/flow_backup_2026-04-29.json', 'r') as f:
    flow_data = json.load(f)

# Filter USTEC only
ustec = [r for r in flow_data['rows'] if r['asset'] == 'USTEC']
ustec.sort(key=lambda x: x['date'])

print("=" * 60)
print("USTEC FLOW-STRENGTH INSIGHT ANALYSIS (EXPANDED DATA)")
print("=" * 60)
print(f"\n=== DATA OVERVIEW ===")
print(f"Total USTEC flow records: {len(ustec)}")
print(f"Date range: {ustec[0]['date']} to {ustec[-1]['date']}")

# Load price data
price_data = list(csv.DictReader(open('daily_fetch/CME_MINI_DL_NQ1!, 1D.txt')))
price_map = {row['time'][:10]: float(row['close']) for row in price_data}

# Merge flow with price - calculate forward returns properly
merged = []
for i in range(1, len(ustec)):
    curr = ustec[i]
    prev = ustec[i-1]
    d = curr['date']
    
    if d in price_map and prev['date'] in price_map:
        p = price_map[d]
        pp = price_map[prev['date']]
        
        # Forward return: return from day t to day t+1
        # We need to find the next trading day
        next_day_prices = [price_map.get(r['date']) for r in ustec[i+1:i+4] if r['date'] in price_map]
        next_price = next_day_prices[0] if next_day_prices else None
        
        if next_price:
            ret_1d = (next_price - p) / p * 100
            ret_2d = (next_day_prices[1] - p) / p * 100 if len(next_day_prices) > 1 and next_day_prices[1] else None
            ret_3d = (next_day_prices[2] - p) / p * 100 if len(next_day_prices) > 2 and next_day_prices[2] else None
            
            merged.append({
                'date': d,
                'price': p,
                'prev_price': pp,
                'strength': curr['strength'],
                'prev_strength': prev['strength'],
                'direction': curr['direction'],
                'return_1d': ret_1d,
                'return_2d': ret_2d,
                'return_3d': ret_3d
            })

print(f"Merged records with forward returns: {len(merged)}")
print(f"Date range: {merged[0]['date']} to {merged[-1]['date']}")

# Calculate baseline returns for each horizon
baseline_1d = sum(m['return_1d'] for m in merged if m['return_1d'] is not None) / len(merged)
baseline_2d = sum(m['return_2d'] for m in merged if m['return_2d'] is not None) / len([m for m in merged if m['return_2d'] is not None])
baseline_3d = sum(m['return_3d'] for m in merged if m['return_3d'] is not None) / len([m for m in merged if m['return_3d'] is not None])

print(f"\n=== BASELINE RETURNS ===")
print(f"h=1 (1-day): {baseline_1d:.4f}%")
print(f"h=2 (2-day): {baseline_2d:.4f}%")
print(f"h=3 (3-day): {baseline_3d:.4f}%")

# Define divergence using log returns for price change
# Bearish divergence: price up (log return > 0) but strength down
# Bullish divergence: price down (log return < 0) but strength up

bearish_events = []
bullish_events = []

for i in range(len(merged)):
    curr = merged[i]
    
    # Price change: log return from previous price to current
    if curr['prev_price'] and curr['price']:
        log_return = math.log(curr['price'] / curr['prev_price']) * 100  # in %
    else:
        log_return = 0
    
    # Strength change
    strength_change = curr['strength'] - curr['prev_strength']
    
    # Bearish divergence: price up but strength down
    if log_return > 0 and strength_change < 0:
        event = {
            'date': curr['date'],
            'log_return': log_return,
            'strength_change': strength_change,
            'return_1d': curr['return_1d'],
            'return_2d': curr['return_2d'],
            'return_3d': curr['return_3d']
        }
        bearish_events.append(event)
    
    # Bullish divergence: price down but strength up
    if log_return < 0 and strength_change > 0:
        event = {
            'date': curr['date'],
            'log_return': log_return,
            'strength_change': strength_change,
            'return_1d': curr['return_1d'],
            'return_2d': curr['return_2d'],
            'return_3d': curr['return_3d']
        }
        bullish_events.append(event)

print(f"\n=== DIVERGENCE ANALYSIS ===")
print(f"\n--- Bearish Divergence (price up, strength down) ---")
print(f"N = {len(bearish_events)}")

if bearish_events:
    rets_1d = [e['return_1d'] for e in bearish_events if e['return_1d'] is not None]
    rets_2d = [e['return_2d'] for e in bearish_events if e['return_2d'] is not None]
    rets_3d = [e['return_3d'] for e in bearish_events if e['return_3d'] is not None]
    
    mean_1d = sum(rets_1d) / len(rets_1d) if rets_1d else 0
    mean_2d = sum(rets_2d) / len(rets_2d) if rets_2d else 0
    mean_3d = sum(rets_3d) / len(rets_3d) if rets_3d else 0
    
    print(f"h=1: mean = {mean_1d:.4f}% (excess: {mean_1d - baseline_1d:+.4f} pp)")
    print(f"h=2: mean = {mean_2d:.4f}% (excess: {mean_2d - baseline_2d:+.4f} pp)")
    print(f"h=3: mean = {mean_3d:.4f}% (excess: {mean_3d - baseline_3d:+.4f} pp)")
    
    # T-test against baseline
    if len(rets_1d) > 2:
        t_stat, p_val = stats.ttest_1samp(rets_1d, baseline_1d)
        print(f"h=1 t-test vs baseline: t={t_stat:.3f}, p={p_val:.4f}")

print(f"\n--- Bullish Divergence (price down, strength up) ---")
print(f"N = {len(bullish_events)}")

if bullish_events:
    rets_1d = [e['return_1d'] for e in bullish_events if e['return_1d'] is not None]
    rets_2d = [e['return_2d'] for e in bullish_events if e['return_2d'] is not None]
    rets_3d = [e['return_3d'] for e in bullish_events if e['return_3d'] is not None]
    
    mean_1d = sum(rets_1d) / len(rets_1d) if rets_1d else 0
    mean_2d = sum(rets_2d) / len(rets_2d) if rets_2d else 0
    mean_3d = sum(rets_3d) / len(rets_3d) if rets_3d else 0
    
    print(f"h=1: mean = {mean_1d:.4f}% (excess: {mean_1d - baseline_1d:+.4f} pp)")
    print(f"h=2: mean = {mean_2d:.4f}% (excess: {mean_2d - baseline_2d:+.4f} pp)")
    print(f"h=3: mean = {mean_3d:.4f}% (excess: {mean_3d - baseline_3d:+.4f} pp)")
    
    if len(rets_1d) > 2:
        t_stat, p_val = stats.ttest_1samp(rets_1d, baseline_1d)
        print(f"h=1 t-test vs baseline: t={t_stat:.3f}, p={p_val:.4f}")

# Transition Matrix Analysis (Full coverage from -6 to +6)
print(f"\n=== COMPREHENSIVE TRANSITION MATRIX (H+1 & H+2) ===")
matrix = defaultdict(lambda: defaultdict(list))
for m in merged:
    s_prev = int(round(m['prev_strength']))
    s_curr = int(round(m['strength']))
    if s_prev != s_curr:
        matrix[s_prev][s_curr].append({
            'r1': m['return_1d'],
            'r2': m['return_2d']
        })

for s_from in range(-6, 7):
    targets = matrix[s_from]
    if not targets: continue
    print(f"\nSource State S = {s_from:+.0f}:")
    # Sort targets by magnitude of return or state
    for s_to in sorted(targets.keys()):
        data = targets[s_to]
        n = len(data)
        # Filter out None values for calculation
        r1_list = [d['r1'] for d in data if d['r1'] is not None]
        r2_list = [d['r2'] for d in data if d['r2'] is not None]
        
        m_r1 = sum(r1_list) / len(r1_list) if r1_list else 0
        m_r2 = sum(r2_list) / len(r2_list) if r2_list else 0
        
        print(f"  -> To {s_to:+.0f}: N={n} | R(H+1)={m_r1:+.4f}% | R(H+2)={m_r2:+.4f}%")

# Strength level analysis
print(f"\n=== STRENGTH LEVEL ANALYSIS ===")
strength_stats = defaultdict(lambda: {'n': 0, 'rets': []})
for m in merged:
    if m['return_1d'] is not None:
        s = int(round(m['strength']))
        strength_stats[s]['n'] += 1
        strength_stats[s]['rets'].append(m['return_1d'])

for s in sorted(strength_stats.keys()):
    data = strength_stats[s]
    if data['n'] >= 3:
        mean_ret = sum(data['rets']) / len(data['rets'])
        print(f"  S={s:+.0f}: N={data['n']}, mean return={mean_ret:+.4f}%")

# Exact pattern analysis
print(f"\n=== EXACT PATTERN ANALYSIS ===")

# Pattern A: price up, S_t=0, then S_{t+1}=-2
pattern_a = 0
for i in range(len(merged) - 1):
    curr = merged[i]
    next_m = merged[i+1]
    if curr['price'] > curr['prev_price'] and abs(curr['strength']) < 0.5 and next_m['strength'] < -1:
        pattern_a += 1
print(f"Pattern A (price up, S_t≈0, S_t+1≈-2): N={pattern_a}")

# Pattern B: -2 -> -1 -> 0 during price decline
pattern_b = 0
for i in range(2, len(merged)):
    if (merged[i-2]['strength'] < -1 and 
        -2 <= merged[i-1]['strength'] <= 0 and
        -0.5 <= merged[i]['strength'] <= 0.5 and
        merged[i]['price'] < merged[i-2]['price']):
        pattern_b += 1
print(f"Pattern B (-2->-1->0 during decline): N={pattern_b}")

print("\n" + "=" * 60)
print("ANALYSIS COMPLETE")
print("=" * 60)