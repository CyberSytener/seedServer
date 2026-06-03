"""Offline diagnostic: simulate game rounds to find logic bugs."""
import json
import copy
from modules.bot.models import GameState, BotAction
from modules.bot.decision_engine import DecisionEngine
from modules.bot.grid import Grid
from modules.bot.orders import compute_needed_items, get_active_order

# Realistic Easy game state (12x10, 1 bot, 2 aisles)
EASY_STATE = {
    "type": "game_state",
    "round": 0,
    "max_rounds": 300,
    "grid": {
        "width": 12,
        "height": 10,
        "walls": [
            # Aisle 1 (column 3, rows 1-4)
            [3, 1], [3, 2], [3, 3], [3, 4],
            # Aisle 2 (column 7, rows 1-4)
            [7, 1], [7, 2], [7, 3], [7, 4],
            # Top wall
            [0, 0], [1, 0], [2, 0], [3, 0], [4, 0], [5, 0],
            [6, 0], [7, 0], [8, 0], [9, 0], [10, 0], [11, 0],
        ],
    },
    "bots": [
        {"id": 0, "position": [5, 8], "inventory": []},
    ],
    "items": [
        {"id": "item_0", "type": "milk", "position": [3, 2]},
        {"id": "item_1", "type": "bread", "position": [3, 3]},
        {"id": "item_2", "type": "eggs", "position": [7, 1]},
        {"id": "item_3", "type": "butter", "position": [7, 3]},
    ],
    "orders": [
        {
            "id": "order_0",
            "items_required": ["milk", "bread", "eggs"],
            "items_delivered": [],
            "complete": False,
            "status": "active",
        },
        {
            "id": "order_1",
            "items_required": ["butter"],
            "items_delivered": [],
            "complete": False,
            "status": "preview",
        },
    ],
    "drop_off": [1, 9],
    "score": 0,
}

def apply_action(state_dict: dict, bot_idx: int, action_cmd: dict) -> dict:
    """Apply a single bot action and return updated state (simplified simulator)."""
    state = copy.deepcopy(state_dict)
    bot = state["bots"][bot_idx]
    x, y = bot["position"]
    action = action_cmd["action"]

    if action == "move_up":
        ny = y - 1
        if 0 <= ny < state["grid"]["height"] and [x, ny] not in state["grid"]["walls"]:
            bot["position"] = [x, ny]
    elif action == "move_down":
        ny = y + 1
        if 0 <= ny < state["grid"]["height"] and [x, ny] not in state["grid"]["walls"]:
            bot["position"] = [x, ny]
    elif action == "move_left":
        nx = x - 1
        if 0 <= nx < state["grid"]["width"] and [nx, y] not in state["grid"]["walls"]:
            bot["position"] = [nx, y]
    elif action == "move_right":
        nx = x + 1
        if 0 <= nx < state["grid"]["width"] and [nx, y] not in state["grid"]["walls"]:
            bot["position"] = [nx, y]
    elif action == "pick_up":
        item_id = action_cmd.get("item_id")
        if item_id:
            ix, iy = bot["position"]
            for item in state["items"]:
                if item["id"] == item_id:
                    ipos = item["position"]
                    dist = abs(ix - ipos[0]) + abs(iy - ipos[1])
                    if dist == 1 and len(bot["inventory"]) < 3:
                        bot["inventory"].append(item["type"])
                        state["items"].remove(item)
                        print(f"    ✓ PICKED UP {item_id} ({item['type']})")
                    else:
                        print(f"    ✗ PICK_UP FAILED: dist={dist} inv_size={len(bot['inventory'])}")
                    break
            else:
                print(f"    ✗ PICK_UP FAILED: item {item_id} not found")
    elif action == "drop_off":
        drop = state["drop_off"]
        if bot["position"] == drop:
            active = next((o for o in state["orders"] if o["status"] == "active"), None)
            if active:
                delivered = []
                remaining_inv = list(bot["inventory"])
                for item_type in list(remaining_inv):
                    still_needed = list(active["items_required"])
                    for d in active["items_delivered"]:
                        if d in still_needed:
                            still_needed.remove(d)
                    for d in delivered:
                        if d in still_needed:
                            still_needed.remove(d)
                    if item_type in still_needed:
                        delivered.append(item_type)
                        remaining_inv.remove(item_type)
                        state["score"] += 1
                        print(f"    ✓ DELIVERED {item_type} (+1)")
                
                active["items_delivered"].extend(delivered)
                bot["inventory"] = remaining_inv
                
                # Check order complete
                if set(active["items_delivered"]) == set(active["items_required"]) and \
                   len(active["items_delivered"]) >= len(active["items_required"]):
                    active["complete"] = True
                    state["score"] += 5
                    print(f"    ✓ ORDER COMPLETE (+5)")
        else:
            print(f"    ✗ DROP_OFF FAILED: bot at {bot['position']}, drop_off at {drop}")

    state["round"] += 1
    return state


def main():
    engine = DecisionEngine(use_astar=False, debug=False, verbose=False)
    
    state_dict = copy.deepcopy(EASY_STATE)
    
    print("=" * 60)
    print("OFFLINE DIAGNOSTIC — Easy mode simulation")
    print("=" * 60)
    
    for round_num in range(80):
        state = GameState(**state_dict)
        grid = Grid(state.grid)
        
        bot = state.bots[0]
        needed = compute_needed_items(state)
        active = get_active_order(state)
        
        print(f"\n--- Round {round_num} | Score={state_dict['score']} ---")
        print(f"  Bot0 @ {bot.pos.as_tuple()} inv={bot.inventory}")
        print(f"  Active: {active.id if active else 'None'} needed={needed}")
        print(f"  Items on map: {[(i.id, i.type, i.pos.as_tuple()) for i in state.items]}")
        print(f"  Drop-off: {state.drop_off}")
        
        actions = engine.decide(state)
        cmd = actions.actions[0]
        action_dict = cmd.to_dict()
        
        print(f"  >> ACTION: {action_dict}")
        
        state_dict = apply_action(state_dict, 0, action_dict)
        
        if state_dict["score"] > 0:
            print(f"\n  *** SCORE IS NOW {state_dict['score']} ***")
        
        if round_num > 50 and state_dict["score"] == 0:
            print(f"\n  !!! STILL SCORE=0 AFTER {round_num} ROUNDS — BUG DETECTED !!!")
            break


if __name__ == "__main__":
    main()
