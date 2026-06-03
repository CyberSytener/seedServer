#!/usr/bin/env python3
"""Analyze items delivered per drop-off trip."""
import sys, os, json
from collections import defaultdict
import statistics

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

# Use hardcoded path or relative navigation
LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "bot"

def get_hard_logs(n=20):
    logs = sorted(LOG_DIR.glob("game_*hard*.jsonl"), key=lambda p: p.name)
    valid = [l for l in logs if l.stat().st_size > 500000]
    return valid[-n:]

def analyze_drops(log_path):
    # Quick parse
    with open(log_path) as f:
        lines = [json.loads(line) for line in f]
    
    first = lines[0]
    drop_off =  tuple(first['state']['drop_off'])
    
    drops = []
    
    prev_bots = {b['id']: b for b in first['state']['bots']}
    
    for row in lines[1:]:
        if 'state' not in row: continue
        curr_bots = {b['id']: b for b in row['state']['bots']}
        
        for bid, curr_bot in curr_bots.items():
            prev_bot = prev_bots[bid]
            
            p_pos = tuple(prev_bot['position'])
            c_pos = tuple(curr_bot['position'])
            p_inv = prev_bot['inventory']
            c_inv = curr_bot['inventory']
            
            # If at drop-off and inventory decreased
            at_drop = (c_pos == drop_off) or (p_pos == drop_off)
            
            if at_drop and len(c_inv) < len(p_inv):
                delivered = len(p_inv) - len(c_inv)
                # But maybe they picked up? No, pickup increases size.
                # Dropoff decreases.
                drops.append(delivered)
                
        prev_bots = curr_bots
        
    return drops

if __name__ == "__main__":
    logs = get_hard_logs(20)
    all_drops = []
    
    print(f"{'Log':<35} {'Avg Items/Drop':<15} {'Total Drops':<12}")
    print("-" * 65)
    
    for log in logs:
        drops = analyze_drops(log)
        if not drops: continue
        avg = statistics.mean(drops)
        all_drops.extend(drops)
        print(f"{log.name:<35} {avg:<15.2f} {len(drops):<12}")
        
    if all_drops:
        grand_avg = statistics.mean(all_drops)
        try:
            grand_med = statistics.median(all_drops)
        except:
            grand_med = 0
        print("-" * 65)
        print(f"{'GRAND AVERAGE':<35} {grand_avg:<15.2f} {len(all_drops):<12}")
        print(f"{'GRAND MEDIAN':<35} {grand_med:<15.2f}")
