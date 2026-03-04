# Demo Document Processor Worker

Deterministic worker used by Demo.1 to prove the platform can run a useful workload with no platform logic changes.

## Input
- `DOC_ID`
- `TENANT_ID`
- `DOC_TEXT` (preferred) or `DOC_PATH`

## Output
- Writes one-line JSON to stdout.
- Writes the same JSON to `/tmp/result.json`.

## Local run
```bash
DOC_ID=doc-1 TENANT_ID=tenant-a DOC_TEXT="hello demo world" python apps/demo/document_processor/worker.py
```

## Container build
```bash
docker build -t job-system-doc-processor:0.1.0 apps/demo/document_processor
```
