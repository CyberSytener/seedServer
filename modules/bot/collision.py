"""Collision avoidance / cell reservation for multi-bot coordination."""
from __future__ import annotations

from typing import Optional

from .models import BotAction


def resolve_collisions(
    plans: list[tuple[int, tuple[int, int], tuple[int, int]]],
    occupied: set[tuple[int, int]],
    priorities: dict[int, int] | None = None,
) -> dict[int, tuple[int, int]]:
    """Resolve movement conflicts using iterative rollback.

    Ensures high-priority bots don't get blocked by low-priority bots
    unless physically necessary. Supports position swapping.
    """
    priorities = priorities or {}
    
    # State: Where each bot *currently* intends to go
    # Initially, everyone tries their desired move
    current_intent: dict[int, tuple[int, int]] = {}
    starts: dict[int, tuple[int, int]] = {}
    
    for bid, start, target in plans:
        current_intent[bid] = target
        starts[bid] = start

    # Static obstacles (walls/stationary bots not in plans) are 'occupied'
    # We treat these as bots with infinite priority that never move
    static_occupied = set(occupied) 
    # Note: 'occupied' arg usually contains current positions of ALL bots?
    # No, usually contains 'static' obstacles for this tick (waiters).
    # We'll assume 'occupied' are blocked cells.

    # Iteratively resolve
    # We loop until no conflicts exist.
    # Conflicts:
    # 1. Two bots want same cell.
    # 2. Bot wants cell occupied by static obstacle.
    # 3. Swap prevention? (We WANT swaps, so we ignore A->B, B->A conflicts)
    
    max_iter = len(plans) * 2 + 5
    for _ in range(max_iter):
        changes = 0
        
        # Build usage map: Cell -> List of Bots claiming it
        claims: dict[tuple[int, int], list[int]] = {}
        for bid, target in current_intent.items():
            claims.setdefault(target, []).append(bid)
            
        conflited_bots = set()
        
        # 1. Check conflicts with static obstacles
        for bid, target in current_intent.items():
            if target in static_occupied:
                # If target is static occupied, allowing it ONLY if it's the bot's own start?
                # No, static_occupied usually means "blocked by OTHER things".
                # If a bot decides to WAIT, it is in 'occupied'.
                # But here we are resolving plans.
                # If a bot is in 'plans', it is dynamic.
                # We assume 'occupied' does not overlap with 'starts' of moving bots.
                conflited_bots.add(bid)
        
        # 2. Check multi-bot claims
        for cell, claimants in claims.items():
            if len(claimants) > 1:
                # Handle Incumbency: If any claimant is staying at their start, they WIN unconditionally against movers.
                # (Unless multiple incumbents? Impossible).
                incumbent = None
                for b in claimants:
                    if starts[b] == cell:
                        incumbent = b
                        break
                
                conflicted = []
                if incumbent is not None:
                     # All others lose
                     for b in claimants:
                         if b != incumbent: conflicted.append(b)
                else:
                     # Priority battle
                     claimants.sort(key=lambda b: priorities.get(b, 0), reverse=True)
                     conflicted = claimants[1:]
                
                for b in conflicted:
                    conflited_bots.add(b)
            
        if not conflited_bots:
            break
            
        # Revert losers
        for bid in conflited_bots:
            # If already at start, we can't do anything (it's a static block)
            if current_intent[bid] == starts[bid]:
                continue
                
            # Revert to start
            current_intent[bid] = starts[bid]
            changes += 1
            
        if changes == 0:
            break # Stable

            
    return current_intent




def action_for_move(
    current: tuple[int, int],
    target: tuple[int, int],
) -> BotAction:
    """Return the BotAction to move from *current* toward *target* (one step)."""
    dx = target[0] - current[0]
    dy = target[1] - current[1]
    if dx == 1:
        return BotAction.MOVE_RIGHT
    if dx == -1:
        return BotAction.MOVE_LEFT
    if dy == 1:
        return BotAction.MOVE_DOWN
    if dy == -1:
        return BotAction.MOVE_UP
    return BotAction.WAIT
