# Phase 4: Billing & Credits Integration - Implementation Complete

**Status**: ✅ COMPLETE  
**Date**: 2025-01-29  
**Scope**: Credit checking, cost debit, payment blocking, watermarking

## What Was Implemented

### 1. Photo Billing Service (`app/billing_service.py`)

**Core Classes**:
- ✅ `PhotoBillingService`: Main billing logic
- ✅ `WatermarkService`: Image watermarking
- ✅ `PhotoCreditTransaction`: Database model for audit trail
- ✅ `TransactionType` enum: debit, refund, credit, purchase

**Main Methods**:

```python
# Check user credit balance
balance = await billing_service.check_user_credits(user_id)

# Validate can afford before processing
can_afford, reason = await billing_service.validate_can_afford(
    user_id=user_id,
    cost_usd=cost_estimate,
    require_payment=True
)

# Debit credits after job completion
success, new_balance = await billing_service.debit_user_credits(
    user_id=user_id,
    cost_usd=actual_cost,
    job_id=job_id,
    reason="Photo editing - 2 variants"
)

# Refund if debit fails
success, new_balance = await billing_service.refund_user_credits(
    user_id=user_id,
    cost_usd=cost_usd,
    job_id=job_id,
    reason="Job failed - automatic refund"
)

# Get transaction history
transactions = billing_service.get_user_transaction_history(user_id)

# Convert USD to credits
credits = billing_service.usd_to_credits(5.00)  # $5 = 500 credits (default)

# Convert credits to USD
usd = billing_service.credits_to_usd(500)  # 500 credits = $5
```

**Credit System**:
- Configurable exchange rate: `credits_price_per_dollar` (default: 100 credits = $1)
- Transaction logging for audit trail
- Automatic refund on debit failure

### 2. Watermarking Service (`app/billing_service.py`)

**Features**:
- ✅ Add semi-transparent watermark to unpaid images
- ✅ Configurable watermark text
- ✅ Non-destructive watermarking (original preserved)
- ✅ Fallback to original if watermarking fails

**Usage**:
```python
# Apply watermark if unpaid
watermarked = WatermarkService.apply_watermark(
    image_bytes=image_bytes,
    watermark_text="PREVIEW - Payment Pending"
)

# Automatic watermarking based on balance
image_bytes = await WatermarkService.apply_watermark_if_unpaid(
    image_bytes=image_bytes,
    user_id=user_id,
    billing_service=billing_service
)
```

### 3. Worker Integration (`app/photo_worker.py`)

**Changes**:
- ✅ Added `billing_service` parameter to worker
- ✅ Pre-processing credit check (reject if insufficient funds)
- ✅ Post-processing credit debit
- ✅ Automatic refund on debit failure
- ✅ Cost tracking per variant

**New Workflow**:
```
1. Get job from queue
2. Check user credits (REJECT if insufficient)
3. Download original from S3
4. Generate variants
5. Debit actual cost from credits
6. If debit fails: REFUND and fail job
7. Complete job with variants
```

### 4. API Endpoints (`app/photo_api.py`)

**New Endpoints**:

**GET /api/photo/billing/credits**
```json
Response:
{
  "user_id": "user-123",
  "credits": 5000,
  "balance_usd": 50.00
}
```

**GET /api/photo/billing/transactions**
```json
Response:
{
  "user_id": "user-123",
  "transactions": [
    {
      "id": "trans-123",
      "job_id": "job-456",
      "amount": -500,
      "type": "debit",
      "reason": "Photo editing - 2 variants",
      "balance_before": 5500,
      "balance_after": 5000,
      "api_cost_usd": 5.00,
      "created_at": "2025-01-29T10:30:00"
    }
  ]
}
```

### 5. Integration (`app/photo_integration.py`)

**Changes**:
- ✅ Initialize `PhotoBillingService` with DB session
- ✅ Pass billing service to worker
- ✅ Add helper functions: `get_seed_db_session()`, `get_seed_user_service()`

**Initialization**:
```python
integration = PhotoEditingQueueIntegration()
# Now includes: billing_service, storage_service, worker
```

### 6. Configuration (`app/photo_settings.py`)

**New Settings**:
```python
PHOTO_REQUIRE_PAYMENT = True  # Block free users
PHOTO_WATERMARK_UNTIL_PAID = True  # Add watermark to previews
CREDITS_PRICE_PER_DOLLAR = 100  # 100 credits = $1
```

## Database Schema

**New Table**: `photo_credit_transactions`

```sql
CREATE TABLE photo_credit_transactions (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    job_id VARCHAR(36),
    amount FLOAT NOT NULL,
    transaction_type VARCHAR(20) NOT NULL,
    reason TEXT,
    balance_before FLOAT,
    balance_after FLOAT,
    api_cost_usd FLOAT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_user_id (user_id),
    INDEX idx_job_id (job_id),
    INDEX idx_created_at (created_at)
);
```

## Architecture & Data Flow

```
User Upload
    ↓
Face Detection + Validation
    ↓
Save Original to S3
    ↓
Enqueue Job
    ↓
Worker Starts:
    ├─ PRE-CHECK: Validate Credits ← NEW (Phase 4)
    │  ├─ Can Afford? YES → Continue
    │  └─ Can Afford? NO → Fail Job (401 Payment Required)
    ├─ Download Original from S3
    ├─ For Each Variant:
    │  ├─ Call OpenAI DALL-E 3
    │  ├─ Upload Result to S3
    │  └─ Generate Presigned URL
    ├─ DEBIT CREDITS: ← NEW (Phase 4)
    │  ├─ Debit Success? YES → Complete Job
    │  └─ Debit Failed? → Refund + Fail Job
    └─ Log Transaction to Audit Trail ← NEW (Phase 4)
    ↓
User Download (confirm):
    ├─ Apply Watermark if Unpaid ← NEW (Phase 4)
    ├─ Generate Presigned URL (24h)
    └─ Download from S3
```

## Credit Logic

### Pre-Job Credit Check
```python
# Reject BEFORE processing if insufficient funds
if balance < required_credits:
    raise PaymentRequiredError()
    # Job fails immediately - no API cost incurred
```

### Post-Job Credit Debit
```python
# Debit AFTER job completion
cost_actual = sum(variant_costs)
success, new_balance = await billing_service.debit_user_credits(
    user_id=user_id,
    cost_usd=cost_actual,
)

if not success:
    # Refund immediately if debit failed
    await billing_service.refund_user_credits(user_id, cost_actual)
    fail_job("Payment processing failed")
```

### Watermarking
```python
# Apply watermark to preview images if user is overdrawn
if user_balance < 0:
    image_bytes = WatermarkService.apply_watermark(
        image_bytes,
        "UNPAID - Complete Payment"
    )
```

## Testing

### Unit Test Example
```python
import asyncio

async def test_credit_debit():
    from app.billing_service import PhotoBillingService
    
    billing = PhotoBillingService(db_session)
    
    # Check balance
    balance = await billing.check_user_credits("user-123")
    print(f"Balance: {balance} credits (${billing.credits_to_usd(balance):.2f})")
    
    # Validate can afford
    can_afford, reason = await billing.validate_can_afford(
        user_id="user-123",
        cost_usd=5.00,
        require_payment=True
    )
    print(f"Can afford: {can_afford} - {reason}")
    
    # Debit credits
    success, new_balance = await billing.debit_user_credits(
        user_id="user-123",
        cost_usd=5.00,
        job_id="job-456",
        reason="Photo editing"
    )
    print(f"Debited: {success}, New balance: {new_balance}")

asyncio.run(test_credit_debit())
```

### Integration Test
```bash
# 1. Start services
docker-compose up

# 2. Upload photo (should check credits first)
curl -X POST http://localhost:8000/api/photo/upload \
  -F "file=@portrait.jpg" \
  -F "context=cv" \
  -F "variants=2" \
  -H "Authorization: Bearer user-token"

# 3. Check job status
curl http://localhost:8000/api/photo/status/job-123 \
  -H "Authorization: Bearer user-token"

# 4. Confirm download (applies watermark if unpaid)
curl -X POST http://localhost:8000/api/photo/confirm/job-123 \
  -H "Authorization: Bearer user-token"

# 5. Check credit balance
curl http://localhost:8000/api/photo/billing/credits \
  -H "Authorization: Bearer user-token"

# 6. View transaction history
curl http://localhost:8000/api/photo/billing/transactions \
  -H "Authorization: Bearer user-token"
```

## Failure Scenarios

### Scenario 1: Insufficient Credits
```
Upload → Check credits → FAIL (401)
→ No API call made
→ No cost incurred
→ User informed: "Insufficient credits"
```

### Scenario 2: API Call Succeeds, Debit Fails
```
Upload → Check credits → OK
→ Call OpenAI → SUCCESS (cost: $5)
→ Upload variants to S3 → SUCCESS
→ Debit credits → FAIL (database error)
→ REFUND $5 automatically
→ Job marked as FAILED
→ User notified
```

### Scenario 3: User Overdrawn
```
Next download attempt
→ Check balance: -500 credits
→ Apply watermark: "UNPAID - Complete Payment"
→ Send presigned URL with watermarked image
```

## Configuration Example

```env
# .env

# Billing
PHOTO_REQUIRE_PAYMENT=true
PHOTO_WATERMARK_UNTIL_PAID=true

# Credits
# 100 credits = $1.00
# So $5.00 cost = 500 credits debited

# Photo costs (from OpenAI)
PHOTO_COST_PER_VARIANT=0.04  # DALL-E 3 standard 1024x1024

# Database (for transactions)
DATABASE_URL=sqlite:///./seed.db
```

## Monitoring & Alerts

**Metrics to Track**:
- Average credits per user
- Debit success rate
- Refund frequency
- Watermarked image % (indicates unpaid users)
- Credit purchase rate

**Alerts**:
- Debit failure rate > 5% → investigate payment service
- User balance negative for > 7 days → send payment reminder
- Transaction log errors → database issues

## Troubleshooting

### Issue: Credit check always fails
**Cause**: User service integration not working  
**Fix**: Verify `get_seed_user_service()` returns valid user object with `credits` field

```python
# Check user structure
user = user_service.get_user(user_id)
print(user.credits)  # Should be a number, not None
```

### Issue: Watermark not appearing
**Cause**: PIL font not available or image format issue  
**Fix**: PIL defaults to basic font if truetype fails. Check image is JPEG/PNG

```python
# Verify image format
from PIL import Image
img = Image.open(image_bytes)
print(img.format)  # Should be JPEG or PNG
```

### Issue: Debit fails with database error
**Cause**: SQLAlchemy session issues or transaction log table missing  
**Fix**: Run database migration to create `photo_credit_transactions` table

```bash
# Create table
alembic upgrade head

# Or manually:
sqlite3 seed.db < schema.sql
```

## Integration with Seed's Existing Credit System

**Assumption**: Seed already has user credits system  
**Location**: `User.credits` field  
**Integration Points**:
1. `get_seed_user_service()` - Fetch user + check credits
2. `get_seed_db_session()` - Access database for transaction logging
3. User model has `.credits` field

**If Seed uses different schema**, adjust:
```python
# In billing_service.py, update check_user_credits():
user = user_service.get_user(user_id)
balance = user.premium_credits  # or whatever field name
```

## Next Phase (Phase 5)

### End-to-End Integration Tests

**Tasks**:
1. Unit tests for credit validation
2. Integration tests for upload → worker → S3 → download flow
3. Payment failure scenarios
4. Watermarking verification
5. Load tests (concurrent jobs with billing)

**Files to Create**:
- `tests/test_billing.py` - Credit logic tests
- `tests/test_photo_e2e.py` - End-to-end flow tests
- `tests/test_payment_scenarios.py` - Failure handling

## Files Modified/Created

| File | Status | Changes |
|------|--------|---------|
| `app/billing_service.py` | ✅ NEW | Full billing system |
| `app/photo_worker.py` | ✅ UPDATED | Credit check + debit |
| `app/photo_api.py` | ✅ UPDATED | Billing endpoints |
| `app/photo_integration.py` | ✅ UPDATED | Billing service init |
| `app/photo_settings.py` | ✅ UPDATED | Payment config |

## Summary

✅ Phase 4 complete! Full billing & credit system ready:
- Pre-job credit validation (prevent overspend)
- Post-job cost debit (charge for actual usage)
- Automatic refunds (if debit fails)
- Watermarking (indicate unpaid images)
- Audit trail (transaction logging)
- API endpoints (check balance, history)
- Configurable credit-to-USD exchange rate

**Ready for Phase 5**: End-to-End Integration Tests
