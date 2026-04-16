# ADR-002: Add a Session-Aware Day-Trade Playbook Layer

## Status
Accepted

## Date
2026-04-16

## Context

The core engine produces a fundamentals-only directional bias for the target instruments, but day trading needs more than a raw bias:

- a clear allowed direction for the day or session
- preferred trading sessions for each instrument
- explicit no-trade windows around scheduled macro releases
- conservative handling when confidence is weak or the macro drivers are stale

The system also uses FRED as its primary macro source. FRED is suitable for research and live bias generation, but its real-time controls are date-based rather than precise intraday release-timestamp controls.

## Decision

Add a separate day-trading playbook layer that sits on top of the scoring engine.

The playbook layer:

- reuses the live bias engine for directional context
- applies configurable confidence and stale-driver gates
- uses a manually maintained official release calendar JSON file
- maps release currencies to preferred sessions and no-trade windows
- outputs a playbook with `bias`, `allowed_direction`, `trade_state`, `valid_sessions`, and `no_trade_windows`

## Alternatives Considered

### Use the raw bias output directly

- Pros: simplest implementation
- Cons: does not express session timing or release lockouts
- Rejected: not specific enough for day-trading workflows

### Build a fully automated live economic-calendar integration first

- Pros: less manual upkeep
- Cons: adds a fragile external dependency and increases operational complexity
- Rejected: premature for the current research stage

### Use snapshots only instead of live scoring

- Pros: avoids live API calls for playbook generation
- Cons: risks using stale bias if no recent run exists
- Rejected: live scoring is the safer default for intraday planning

## Consequences

- The repo now contains a sample official release calendar that must be maintained manually
- The day-trading layer is transparent about lockouts and data-quality gating
- The system remains honest: it is still a bias filter, not a news-spike execution engine
- Future work can add broader non-USD calendars or swap the static calendar file for a more automated source if needed
