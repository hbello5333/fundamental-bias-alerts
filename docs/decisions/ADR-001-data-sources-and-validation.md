# ADR-001: Use FRED / ALFRED for the MVP Macro Data Layer

## Status

Accepted

## Date

2026-04-16

## Context

We need a data source for a fundamentals-only alert engine that:

- covers the U.S. and major developed-market macro series
- supports search and metadata inspection
- is practical for a local prototype
- supports honest historical research without pretending revised data are point-in-time truth

## Decision

Use the St. Louis Fed FRED API for current macro series retrieval and series search, with ALFRED real-time period support as the conceptual foundation for later validation work.

The MVP stays broker-agnostic and does not attempt to reconstruct a fully intraday historical macro tape.

## Alternatives Considered

### Paid macro calendar / institutional feeds

- Pros: true release timestamps, consensus fields, cleaner event studies
- Cons: higher cost, setup friction, unnecessary for the first local build
- Rejected for MVP: better as a second-stage validation upgrade

### Trading-platform indicators or discretionary news APIs

- Pros: fast to prototype
- Cons: not fundamentals-only, often opaque, harder to audit
- Rejected: conflicts with the project's stated objective

### Official-source-by-official-source direct integrations

- Pros: maximum source purity
- Cons: many APIs, inconsistent formats, slower build cycle
- Rejected for MVP: too much complexity for the first slice

## Consequences

- The engine can run hourly in real time using official/primary macro series aggregation.
- The repo can lock resolved series IDs after manual review.
- Historical validation remains honest about a key limitation:
  FRED / ALFRED real-time periods are date-based, so intraday release timing still requires a separate calendar feed.
- If we later need stronger proof, the next logical upgrade is a timestamped economic calendar plus broker or exchange price history.

