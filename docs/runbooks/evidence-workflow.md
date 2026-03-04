# Evidence Workflow

This runbook standardizes evidence pack setup and validation.

## Initialize a milestone pack

```bash
scripts/evidence_init.sh <phase> <milestone>
```

Example:

```bash
scripts/evidence_init.sh phase4 m4.1
```

This creates:
- `docs/evidence/<phase>/<milestone>/runbook.md`
- `docs/evidence/<phase>/<milestone>/commands.txt`
- `docs/evidence/<phase>/<milestone>/outputs/`

## Validate a milestone pack

```bash
scripts/evidence_check.sh <phase> <milestone>
```

Checks:
- required files exist
- outputs directory exists
- at least one `outputs/01-*.txt` file exists

Exit code is non-zero on validation failure.
