# LLM Provider Feature Flags Configuration

## Overview
Feature flags for enabling/disabling LLM providers at runtime without code changes.

## Environment Variables

### SEED_ENABLE_OPENAI
**Type**: Boolean  
**Default**: `true`  
**Description**: Enable or disable OpenAI provider

```bash
# Enable OpenAI
SEED_ENABLE_OPENAI=true

# Disable OpenAI
SEED_ENABLE_OPENAI=false
```

### SEED_ENABLE_GEMINI
**Type**: Boolean  
**Default**: `true`  
**Description**: Enable or disable Gemini provider

```bash
# Enable Gemini
SEED_ENABLE_GEMINI=true

# Disable Gemini (use only for testing)
SEED_ENABLE_GEMINI=false
```

### SEED_ENABLE_STUB
**Type**: Boolean  
**Default**: `true`  
**Description**: Enable or disable stub/mock provider

```bash
# Enable stub provider (for testing)
SEED_ENABLE_STUB=true

# Disable stub provider (in production)
SEED_ENABLE_STUB=false
```

## Configuration Examples

### Production (Gemini Only)
```bash
# .env.production
SEED_ENABLE_OPENAI=false
SEED_ENABLE_GEMINI=true
SEED_ENABLE_STUB=false

SEED_DEFAULT_PROVIDER_FAST=gemini
SEED_DEFAULT_PROVIDER_BATCH=gemini

GEMINI_API_KEY=your_gemini_key_here
```

### Development (All Providers)
```bash
# .env.development
SEED_ENABLE_OPENAI=true
SEED_ENABLE_GEMINI=true
SEED_ENABLE_STUB=true

SEED_DEFAULT_PROVIDER_FAST=stub
SEED_DEFAULT_PROVIDER_BATCH=stub
```

### Testing (Stub Only)
```bash
# .env.test
SEED_ENABLE_OPENAI=false
SEED_ENABLE_GEMINI=false
SEED_ENABLE_STUB=true

SEED_DEFAULT_PROVIDER_FAST=stub
SEED_DEFAULT_PROVIDER_BATCH=stub
```

### Hybrid (Gemini + Stub Fallback)
```bash
# .env.staging
SEED_ENABLE_OPENAI=false
SEED_ENABLE_GEMINI=true
SEED_ENABLE_STUB=true

SEED_DEFAULT_PROVIDER_FAST=gemini
SEED_DEFAULT_PROVIDER_BATCH=gemini
```

## Implementation Details

### Settings Class
```python
# app/settings.py
@dataclass(frozen=True)
class Settings:
    # ... other settings ...
    
    # LLM Provider Feature Flags
    enable_openai: bool
    enable_gemini: bool
    enable_stub: bool
```

### Runtime Validation
```python
# app/llm_client_async.py
async def generate(self, ...):
    # Check if provider is enabled
    if provider == "gemini" and not self.settings.enable_gemini:
        raise ProviderError(f"Provider '{provider}' is disabled")
    elif provider == "openai" and not self.settings.enable_openai:
        raise ProviderError(f"Provider '{provider}' is disabled")
    elif provider == "stub" and not self.settings.enable_stub:
        raise ProviderError(f"Provider '{provider}' is disabled")
    
    # Proceed with generation...
```

## Error Handling

**When provider is disabled:**
```json
{
  "error": "ProviderError",
  "message": "Provider 'openai' is disabled",
  "status": 503
}
```

**Client should handle:**
- Fallback to alternative provider
- Show user-friendly error message
- Log for monitoring/alerting

## Monitoring

### Metrics to Track
```python
# Prometheus metrics
llm_provider_requests_total{provider="gemini", status="enabled"}
llm_provider_requests_total{provider="openai", status="disabled"}
llm_provider_errors_total{provider="gemini", error_type="disabled"}
```

### Grafana Dashboard
- Provider availability status
- Request distribution by provider
- Error rate by provider and type
- Cost tracking per provider

## Admin API

### Check Provider Status
```bash
GET /admin/providers/status
Authorization: Bearer <admin_key>
```

**Response:**
```json
{
  "providers": {
    "openai": {
      "enabled": false,
      "configured": true,
      "health": "disabled"
    },
    "gemini": {
      "enabled": true,
      "configured": true,
      "health": "ok"
    },
    "stub": {
      "enabled": true,
      "configured": true,
      "health": "ok"
    }
  },
  "default_fast": "gemini",
  "default_batch": "gemini"
}
```

### Toggle Provider at Runtime (Future)
```bash
POST /admin/providers/toggle
Authorization: Bearer <admin_key>
Content-Type: application/json

{
  "provider": "openai",
  "enabled": false
}
```

## Migration Guide

### From All Providers to Gemini Only

**Step 1: Update environment**
```bash
# Add to .env
SEED_ENABLE_OPENAI=false
SEED_ENABLE_GEMINI=true
SEED_ENABLE_STUB=false
```

**Step 2: Update default providers**
```bash
SEED_DEFAULT_PROVIDER_FAST=gemini
SEED_DEFAULT_PROVIDER_BATCH=gemini
```

**Step 3: Restart service**
```bash
sudo systemctl restart seed-server
```

**Step 4: Verify**
```bash
curl http://localhost:8000/admin/providers/status
```

**Step 5: Monitor for errors**
```bash
grep "Provider.*disabled" logs/server.log
```

## Rollback Procedure

If issues occur after disabling a provider:

1. **Enable provider**
```bash
SEED_ENABLE_OPENAI=true
```

2. **Restart service**
```bash
sudo systemctl restart seed-server
```

3. **Verify recovery**
```bash
curl http://localhost:8000/health
```

## Best Practices

1. **Always enable at least one provider** - Service requires functional LLM access
2. **Test in staging first** - Verify provider changes before production
3. **Monitor after changes** - Watch error rates and latency
4. **Keep stub enabled in dev** - Useful for local testing without API keys
5. **Document configuration** - Update runbooks when changing providers
6. **Use feature flags gradually** - Roll out changes to small percentage first

## Troubleshooting

### Issue: "Provider 'gemini' is disabled" in production
**Cause**: SEED_ENABLE_GEMINI=false or missing  
**Solution**: Set SEED_ENABLE_GEMINI=true and restart

### Issue: No providers available
**Cause**: All providers disabled  
**Solution**: Enable at least one provider, preferably Gemini for production

### Issue: Default provider is disabled
**Cause**: SEED_DEFAULT_PROVIDER_FAST set to disabled provider  
**Solution**: Change default to enabled provider or enable the provider

## Related Documentation

- [Configuration Reference](CONFIGURATION_REFERENCE.md)
- [Server Capabilities](SERVER_CAPABILITIES_INVENTORY.md)
- [Operational Runbooks](OPERATIONAL_RUNBOOKS.md)
- [LLM Router Implementation](../app/router.py)

## Changelog

**2026-01-12**: Initial implementation of LLM provider feature flags
- Added SEED_ENABLE_OPENAI, SEED_ENABLE_GEMINI, SEED_ENABLE_STUB
- Integrated runtime validation in AsyncLLMClient
- Created configuration documentation
