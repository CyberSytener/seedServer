# NMiAI Grocery Bot — Architecture Diagram

## System Overview (Mermaid)

```mermaid
graph TB
    subgraph "External"
        SERVER["NMiAI Game Server<br/>wss://game.ainm.no"]
    end

    subgraph "Entry Points"
        RUNNER["runner.py<br/>CLI: --url / --token / --difficulty"]
        LIVE["scripts/_live_hard.py<br/>Quick live runner"]
        SIM["scripts/_simulator_hard.py<br/>Offline simulator"]
        BENCH["scripts/_bench.py<br/>Batch benchmarking"]
    end

    subgraph "WebSocket Layer"
        CLIENT["client.py<br/>GameWSClient"]
        EP["endpoint.py<br/>request_game_session()"]
    end

    subgraph "Core Engine"
        ENGINE["planner.py<br/>OptimizedEngine.decide()"]
        LEGACY["decision_engine.py<br/>DecisionEngine (unused)"]
    end

    subgraph "Decision Pipeline"
        P1["Phase 1: DROP_OFF<br/>Bot at drop-off + matching items"]
        P1B["Phase 1b: EVICT<br/>Bot at drop-off + wrong items"]
        P2["Phase 2: DELIVER<br/>Bot with matching items → drop-off<br/>Distance-based priority"]
        P3["Phase 3: ASSIGN<br/>Greedy item assignment<br/>BFS distance + congestion penalty"]
        P3B["Phase 3b: PREFETCH<br/>Preview + future order items<br/>Dynamic order tracking"]
        P4["Phase 4: PARK<br/>Idle bots → rows 1,7 right half<br/>Empty-bot drop-off eviction"]
        COL["Collision Resolution<br/>Priority sorting + swap detection<br/>Alternative step fallback"]
    end

    subgraph "Support Modules"
        PATH["pathfinding.py<br/>BFS / A* / distance maps"]
        GRID["grid.py<br/>Walkability + neighbors"]
        ORDERS["orders.py<br/>Needed / preview items"]
        MODELS["models.py<br/>GameState / BotAction / Pos"]
        COLL["collision.py<br/>resolve_collisions()"]
        MAX["max_score.py<br/>OrderTracker"]
        TEL["telemetry.py<br/>RoundLogger → JSONL"]
    end

    SERVER -->|game_state JSON| CLIENT
    CLIENT -->|actions JSON| SERVER
    EP -->|HTTP: token → ws_url| CLIENT

    RUNNER --> CLIENT
    LIVE --> CLIENT
    SIM --> ENGINE
    BENCH --> SIM

    CLIENT -->|GameState| ENGINE
    ENGINE --> P1
    P1 --> P1B
    P1B --> P2
    P2 --> P3
    P3 --> P3B
    P3B --> P4
    P4 --> COL
    COL -->|RoundActions| CLIENT

    ENGINE --> PATH
    ENGINE --> GRID
    ENGINE --> ORDERS
    ENGINE --> COLL
    ENGINE --> MAX

    CLIENT --> TEL
    CLIENT --> MODELS

    style ENGINE fill:#2d5016,stroke:#4a7c23,color:#fff
    style CLIENT fill:#1a3a5c,stroke:#2e6b9e,color:#fff
    style COL fill:#5c1a1a,stroke:#9e2e2e,color:#fff
    style SERVER fill:#444,stroke:#888,color:#fff
```

---

## Decision Pipeline (Phase Flow)

```mermaid
flowchart LR
    STATE["game_state<br/>(from server)"] --> P1

    subgraph "Phase 1 — Drop-off"
        P1["Bot at drop-off?<br/>Has matching items?"]
        P1 -->|YES| DO["DROP_OFF action"]
        P1 -->|NO| P1B
        P1B["At drop-off?<br/>Wrong inventory?"]
        P1B -->|YES| EVICT["Move away<br/>priority=3"]
    end

    subgraph "Phase 2 — Delivery"
        P1B -->|NO| P2["Has matching<br/>active items?"]
        P2 -->|YES| DELIVER["Move to drop-off<br/>priority=10+max(0,30−dist)"]
        P2 -->|"Opp. pickup"| GRAB["Adjacent needed item?<br/>inv < 3 → PICK_UP"]
    end

    subgraph "Phase 3 — Assignment"
        P2 -->|NO| P3["Inventory < 3?<br/>Items available?"]
        P3 -->|YES| ASSIGN["Greedy: min(BFS_dist +<br/>return_dist×0.9 +<br/>congestion×3)<br/>priority=5"]
    end

    subgraph "Phase 3b — Prefetch"
        P3 -->|"active filled"| P3B["Remaining bots?<br/>Preview/future needs?"]
        P3B -->|YES| PREFETCH["Fetch preview items<br/>+ observed future orders<br/>priority=2"]
    end

    subgraph "Phase 4 — Parking"
        P3B -->|NO| P4["Idle bot"]
        P4 -->|"at drop-off, empty"| DODGE["Move away<br/>(deadlock fix)"]
        P4 -->|else| PARK["Park rows 1,7<br/>right half"]
    end

    subgraph "Collision"
        DO & EVICT & DELIVER & GRAB & ASSIGN & PREFETCH & DODGE & PARK --> RES["resolve_collisions()<br/>sort by priority DESC, bot_id ASC"]
        RES -->|blocked| ALT["_find_alternative_step<br/>delta ≤ 2"]
        RES -->|swap| YIELD["Both bots yield"]
        RES -->|OK| SEND["Send actions"]
        ALT --> SEND
        YIELD --> SEND
    end

    style RES fill:#5c1a1a,stroke:#9e2e2e,color:#fff
    style DELIVER fill:#1a3a5c,stroke:#2e6b9e,color:#fff
    style P1 fill:#2d5016,stroke:#4a7c23,color:#fff
```

---

## WebSocket Communication Flow

```mermaid
sequenceDiagram
    participant S as NMiAI Server
    participant C as client.py
    participant E as OptimizedEngine

    S->>C: game_state (round N)
    Note over C: Drain buffer → keep LATEST
    C->>E: decide(state) [sync, 1–4ms]
    E-->>C: RoundActions
    C->>S: {"actions": [...]}
    Note over S: Apply actions sequentially by bot_id ASC
    S->>C: game_state (round N+1)

    Note over C,S: If response late → server replays<br/>previous round's actions (DESYNC)
```

---

## Grid Layout (Hard Map: 22×14)

```
Y  0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20 21
───────────────────────────────────────────────────────────────────────
0  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W
1  W  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  W
2  W  .  W  S  A  S  W  .  W  S  A  S  W  .  W  S  A  S  W  .  .  W
3  W  .  W  S  A  S  W  .  W  S  A  S  W  .  W  S  A  S  W  .  .  W
4  W  .  W  S  A  S  W  .  W  S  A  S  W  .  W  S  A  S  W  .  .  W
5  W  .  W  S  A  S  W  .  W  S  A  S  W  .  W  S  A  S  W  .  .  W
6  W  .  W  S  A  S  W  .  W  S  A  S  W  .  W  S  A  S  W  .  .  W
7  W  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  W
8  W  .  W  S  A  S  W  .  W  S  A  S  W  .  W  S  A  S  W  .  .  W
9  W  .  W  S  A  S  W  .  W  S  A  S  W  .  W  S  A  S  W  .  .  W
10 W  .  W  S  A  S  W  .  W  S  A  S  W  .  W  S  A  S  W  .  .  W
11 W  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  W
12 W  D  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  B  W
13 W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W

Legend:
  W = Wall        S = Shelf (items on wall, pickup from A)
  A = Aisle       D = Drop-off (1,12)
  B = Bot start   . = Walkable corridor
```

---

## File Dependency Graph

```mermaid
graph LR
    PLANNER["planner.py"] --> COLLISION["collision.py"]
    PLANNER --> PATHFINDING["pathfinding.py"]
    PLANNER --> GRID["grid.py"]
    PLANNER --> ORDERS["orders.py"]
    PLANNER --> MAX_SCORE["max_score.py"]
    PLANNER --> MODELS["models.py"]

    CLIENT["client.py"] --> PLANNER
    CLIENT --> MODELS
    CLIENT --> TELEMETRY["telemetry.py"]

    RUNNER["runner.py"] --> CLIENT
    RUNNER --> PLANNER
    RUNNER --> TELEMETRY

    COLLISION --> MODELS
    PATHFINDING --> GRID
    PATHFINDING --> MODELS
    ORDERS --> MODELS
    MAX_SCORE --> MODELS
    GRID --> MODELS

    ENDPOINT["endpoint.py"] -.->|HTTP API| CLIENT

    style PLANNER fill:#2d5016,stroke:#4a7c23,color:#fff
    style CLIENT fill:#1a3a5c,stroke:#2e6b9e,color:#fff
```
