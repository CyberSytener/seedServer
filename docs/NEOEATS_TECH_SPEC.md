# NeoEats System Audit and Expansion

## Status (Feb 12, 2026)
- **Done:** [x] Inventory provider interface; [x] Provider wiring in SagaArchitect and API endpoints; [x] Inventory ledger + financial migrations.
- **Done:** [x] Provider now reads ledger tables; [x] Phase 2 block implementations (Inventory/Billing/Accounting/Alert/Admin).
- **Done:** [x] Validate blueprints for mandatory NeoEats steps and ordering.
- **Done:** [x] Add cache invalidation hooks to admin flows in runtime engine adapters; [x] Add NeoEats-specific tests for validation rules.
- **Done:** [x] Receipt ingestion saga design + block stubs.
- **Next:** [ ] Add integration tests for inventory reservation flows; [ ] Add receipt ingestion integration tests; [ ] Plan + implement Hot Offer engine; [ ] Add Vision intake workflow for inventory updates.

## Task 1: Technical Audit and Documentation

### Audit: SagaArchitect core behavior
- BlockRegistry: provides the list of valid block names and their input/output schemas used for validation and prompt context generation.
- MODEL_TIERS: chooses the Gemini model, label, and credit cost used for LLM drafting; a tier is resolved in `resolve_model_tier()` and carried in generation metadata.
- stock_snapshot: an optional list of inventory rows used to constrain LLM outputs. It is injected via the architect constructor, stock_provider, or request-specific snapshot. It is used to enrich the system prompt and to filter out-of-stock items in `_apply_stock_filter()`.

### Dependency Mapping: request to draft_blueprint
1. User request arrives at the API endpoint and calls `SagaArchitect.draft_blueprint()`.
2. `resolve_model_tier()` chooses the model and cost metadata for the request.
3. A stock snapshot is loaded via `_get_stock_snapshot()` (override -> cached snapshot -> provider).
4. `_apply_stock_filter()` removes mentions of out-of-stock items from the user prompt and appends a constraint list of in-stock items.
5. The LLM is called with a prompt that includes the registry-based prompt context and the filtered user prompt.
6. The response is parsed into JSON and returned with metadata for tracking.

### System Anatomy (current state)
- The system generates a blueprint using LLM context that includes the registry description and available input/output schema keys.
- The `_apply_stock_filter()` logic removes explicit out-of-stock ingredient names from the user request and adds an explicit constraint list. This reduces the chance that the LLM proposes unavailable ingredients.
- The validation step checks whether block names are registered and input mappings reference prior steps or permitted roots. This prevents invalid wiring and unknown block usage.

## Task 2: Functional Specification for NeoEats Core

### Unified Inventory Ledger (Single Source of Truth)

#### PostgreSQL schema (authoritative ledger)
- `inventory_item`
  - `item_id` (uuid, pk)
  - `sku` (text, unique)
  - `name` (text)
  - `category` (text)
  - `unit` (text)
  - `is_active` (boolean)
  - `created_at`, `updated_at` (timestamptz)

- `inventory_lot`
  - `lot_id` (uuid, pk)
  - `item_id` (uuid, fk -> inventory_item)
  - `expires_at` (date)
  - `quantity_total` (numeric)
  - `quantity_available` (numeric)
  - `location_id` (uuid)
  - `created_at`, `updated_at` (timestamptz)

- `inventory_reservation`
  - `reservation_id` (uuid, pk)
  - `order_id` (uuid)
  - `status` (text: reserved, released, committed)
  - `expires_at` (timestamptz)
  - `created_at`, `updated_at` (timestamptz)

- `inventory_reservation_line`
  - `reservation_id` (uuid, fk -> inventory_reservation)
  - `lot_id` (uuid, fk -> inventory_lot)
  - `quantity` (numeric)

- `inventory_ledger_event`
  - `event_id` (uuid, pk)
  - `event_type` (text: reserve, release, commit, adjust)
  - `item_id` (uuid)
  - `lot_id` (uuid)
  - `quantity` (numeric)
  - `source` (text: order, admin, waste, audit)
  - `reference_id` (uuid)
  - `created_at` (timestamptz)

#### Redis (fast reservation state)
- `reservation:{reservation_id}` -> hash with status, expires_at, order_id
- `reservation:order:{order_id}` -> reservation_id
- `inventory:lock:{item_id}` -> short TTL lock for atomic reservation windows

#### Behavior
- Reservations are atomic in PostgreSQL via transactional update of `inventory_lot.quantity_available` and insertion into `inventory_reservation` and lines.
- Redis tracks TTL for reservations and reduces contention for read-heavy checks.
- Deductions (commit) post a `inventory_ledger_event` and set reservation to committed.

### Expiry and Waste Management
- Daily Cron Block runs every 24 hours.
- It scans `inventory_lot` for `expires_at <= now() + 14 days` and creates a notification payload.
- The block returns a structured list that is passed to `NotificationBlock` to alert staff.

### Financial and Accounting Engine
- BillingBlock computes:
  - `subtotal = (cogs_total + waste_overhead) * (1 + margin_pct)`
  - `vat = subtotal * vat_pct`
  - `total = subtotal + vat`
- It also generates a `receipt_id` and returns receipt metadata.
- AccountingBlock persists the receipt and posts a daily ledger entry to a financial journal table.

### CRUD Admin Blocks
- `AdminAddProductBlock`: creates `inventory_item` and initial `inventory_lot`.
- `AdminUpdateProductBlock`: updates item metadata and optionally lot data.
- `AdminRemoveProductBlock`: sets `is_active = false` and prevents reservation.
- Each block updates the inventory provider used by the Architect to ensure prompt context reflects current inventory.

## Receipt Ingestion Saga (NeoEats)

### Vision-to-Data Pipeline
- **ReceiptScannerBlock** accepts `image_url` or `image_base64` (plus optional `vendor_hint`, `currency`, `locale`).
- Multi-modal LLM extracts structured JSON:
  - `vendor_info`: `name`, `org_nr`
  - `fiscal_data`: `total_amount`, `currency`, `vat_breakdown` (15% food, 25% services)
  - `line_items`: `{ raw_name, mapping_id, quantity, unit, price_per_unit }`
- **Fuzzy matching** resolves `raw_name` to inventory IDs using:
  - normalization (lowercase, remove diacritics/punct)
  - embedding similarity against `inventory_item.name` + synonyms
  - fallback to SKU/barcode if present on receipt
  - confidence thresholds: auto-map if >= 0.85, else require human confirmation

### Fiscal & Inventory Integration
- **Inventory update**: confirm receipt -> map line_items -> increment `inventory_lot.quantity_total` and `quantity_available` for mapped items; create `inventory_ledger_event` with source=`receipt`.
- **FiscalTransaction table** (proof of purchase):
  - `transaction_id` (uuid, pk)
  - `vendor_name`, `vendor_org_nr`
  - `total_amount`, `currency`
  - `vat_breakdown` (jsonb)
  - `receipt_date` (date)
  - `raw_payload` (jsonb)
  - `created_at` (timestamptz)
- **Human-in-the-loop**: UI presents parsed receipt for confirmation; only on approval does `ReceiptProcessorBlock` commit ledger updates and fiscal transaction rows.

### Block Stubs
- `ReceiptScannerBlock` (OCR + LLM extraction) with VAT consistency check utility.
- `ReceiptProcessorBlock` (validation + ledger/fiscal persistence) gated by approval.

## Task 3: Implementation Roadmap (2-Week Sprint)

### Phase 1: Infrastructure (Days 1-4)
- Replace static snapshots with a live provider backed by the inventory ledger tables.
- Add a cache layer for prompt inventory context generation.
- Extend `SagaArchitect` constructor to accept `inventory_provider` interface with async `list_in_stock()`.

### Phase 2: Logic (Days 5-10)
- Implement InventoryBlock (reserve, release, commit) using transactional DB operations.
- Implement BillingBlock and AccountingBlock with receipt persistence.
- Implement DailyExpiryScanBlock and AlertBlock with staff notification integration.

### Phase 3: Validation (Days 11-14)
- Update `validate_blueprint()` to require:
  - InventoryBlock in any order-processing blueprint.
  - BillingBlock and AccountingBlock in any order-processing blueprint.
  - A notification step for expirations in daily cron blueprints.
- Add lint rules: block ordering must be Inventory -> Billing -> Accounting for order flows.

## Deliverable: BlockBase stubs
- The stub classes are provided in app/core/neoeats_blocks.py.
- Register the new blocks in the shared registry when ready for activation.

## Task 4: Hot Offer Engine Plan

### Scope and Flow
- [x] Add priority inventory scan logic (expiry < 3 days, overstock thresholds) and a new block for it.
- [x] Add sales stats ingest block and data model for weekly/hourly popularity data.
- [x] Implement HotOfferGeneratorBlock to create name, slogan, and dynamic price based on COGS.
- [x] Add CulinaryValidatorBlock (balanced tier) with scoring (palatability, safety) and minimum threshold (>= 8).
- [x] Add ApprovalBlock for human-in-the-loop Chef dashboard workflow (pause, notify, webhook resume).

### Validation Layers
- [x] Implement Culinary Compatibility Matrix (hard constraints) and enforce it before LLM generation.
- [x] Implement validator prompt template and structured output parsing.
- [ ] Implement saga termination or retry strategy for low scores.

### Data & Persistence
- [x] Add DB tables: sales_stats, pending_offers (approval state), hot_offer_history.
- [x] Add Pydantic models for InventoryItem, SalesStats, PendingOffer, HotOffer.
- [ ] Add data access layer for stats ingestion and pending offer state transitions.

### Saga Integration
- [x] Register blocks: priority_inventory_scan, sales_stats_fetch, hot_offer_generator, culinary_validator, approval_block.
- [ ] Update saga blueprint validation rules for Hot Offer flow ordering.
- [ ] Add example Hot Offer blueprint + minimal integration test.

### Ops & Monitoring
- [ ] Add metrics for offer generation attempts, validator rejects, and approval latency.
- [ ] Add admin toggles for thresholds and retry policy.

## Task 5: Vision Intake Workflow (Inventory Updates)

### Scope and Flow
- [ ] Add VisionIntakeBlock to accept image_url/image_base64 plus request intent (inventory update, storage update).
- [ ] Add VisionAnalyzerBlock to call the selected vision model with a prompt to extract inventory signals (product, volume, expiration date, SKU/barcode if present).
- [ ] Add VisionConfirmationBlock to pause and request user confirmation before applying updates.
- [ ] Add VisionApplyUpdateBlock to write confirmed updates to inventory_lot or storage tables.

### Data & Storage
- [ ] Add vision_intake table for raw payloads, model outputs, and confirmation state.
- [ ] Store original image metadata (hash, size, source) for audit.

### Validation & Safety
- [ ] Add schema validation for model outputs (required fields: product_name, quantity, unit, expires_at).
- [ ] Add confidence thresholds and fallback to manual entry if below threshold.

### Saga Integration
- [ ] Register blocks: vision_intake, vision_analyzer, vision_confirmation, vision_apply_update.
- [ ] Add example blueprint for worker photo intake flow (capture -> analyze -> confirm -> update).

#### Example Blueprint: Worker Vision Intake
```json
{
  "name": "vision_intake_worker_flow",
  "version": "v1",
  "steps": [
    {
      "id": "intake",
      "block": "vision_intake",
      "inputs": {
        "intent": "storage_update",
        "image_url": {"from": "request.image_url"},
        "image_base64": {"from": "request.image_base64"},
        "prompt": {"from": "request.prompt", "default": "Extract product name, quantity, unit, and expiration date."}
      }
    },
    {
      "id": "analyze",
      "block": "vision_analyzer",
      "inputs": {
        "intake_id": {"from": "intake.intake_id"}
      }
    },
    {
      "id": "confirm",
      "block": "vision_confirmation",
      "inputs": {
        "intake_id": {"from": "intake.intake_id"},
        "approved": {"from": "request.approved", "default": false}
      }
    },
    {
      "id": "apply",
      "block": "vision_apply_update",
      "inputs": {
        "intake_id": {"from": "intake.intake_id"},
        "approved": {"from": "confirm.accepted"},
        "target": "storage"
      }
    }
  ]
}
```

### Ops & Monitoring
- [ ] Track metrics for model confidence, user confirmation rates, and update latency.
