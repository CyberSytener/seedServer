# Jobs API Contract (Canonical + Deprecation)

Updated: 2026-02-17

## Canonical contract

- Submit text actions: `POST /v1/actions`
- Read job state: `GET /v1/jobs/{job_id}`
- Cancel queued job: `POST /v1/jobs/{job_id}/cancel`

These endpoints are the primary contract for new clients.

## Deprecated endpoints

The following endpoints remain available for backward compatibility but are deprecated:

- `POST /v1/jobs/submit`
- `GET /v1/jobs/status/{job_id}`
- `GET /v1/jobs/status/{job_id}/stream`
- `GET /v1/jobs/list`

Deprecation metadata is sent via response headers:

- `Deprecation: true`
- `Sunset: Tue, 30 Jun 2026 00:00:00 GMT`
- `Link: <successor>; rel="successor-version", </docs/jobs_api_contract.md>; rel="deprecation"`

## Migration guidance

- Clients using `POST /v1/jobs/submit` should migrate submission to `POST /v1/actions` where possible.
- Clients polling `GET /v1/jobs/status/{job_id}` should migrate to `GET /v1/jobs/{job_id}`.
- Streaming users should migrate to canonical job polling + existing event channels used by current app flow.

## Notes

- Legacy endpoints are still supported during migration window.
- New integrations should not use deprecated routes.
