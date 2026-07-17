# Intent-to-Outcome Fixtures

This directory is reserved for deterministic, intentionally versioned fixtures
used by the Intent-to-Outcome Candidate surface.

Rules:

- no secrets, credentials, personal data, or copied production payloads;
- fixture clocks, IDs, and random seeds must be explicit;
- raw external text is treated as untrusted data;
- every fixture documents the scenario and expected invariant;
- live-source recordings require sanitization and a separate authorization note;
- fixture changes that alter expected behavior require focused test updates.

The initial retail scenarios are added by ITO-202. ITO-002 creates only the
boundary and does not add domain data.
