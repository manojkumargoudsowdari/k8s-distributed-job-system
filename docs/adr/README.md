# Architecture Decision Records (ADR)

This folder stores architecture decisions for the platform in short, durable records.

## Naming
- File pattern: `NNNN-short-title.md`
- Example: `0004-tenant-identity-source.md`

## Format
Each ADR should include:
- Context
- Decision
- Alternatives considered
- Consequences

Use the template in [`0000-template.md`](./0000-template.md).

## Workflow
- Create a new ADR when introducing non-trivial architecture or operational policy.
- Keep ADRs immutable once accepted; create a follow-up ADR for reversals/updates.
- Reference ADR IDs in PR descriptions when behavior changes are tied to a decision.
