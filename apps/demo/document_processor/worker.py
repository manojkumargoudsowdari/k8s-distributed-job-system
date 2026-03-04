import json
import os
from pathlib import Path


def _read_input_text() -> str:
    text = os.getenv("DOC_TEXT", "")
    if text:
        return text

    doc_path = os.getenv("DOC_PATH", "")
    if doc_path:
        return Path(doc_path).read_text(encoding="utf-8")

    return ""


def _summary(text: str, words: int = 12) -> tuple[str, int]:
    normalized = " ".join(text.split())
    tokens = normalized.split(" ") if normalized else []
    count = len(tokens)
    snippet = " ".join(tokens[:words])
    return snippet, count


def main() -> int:
    doc_id = os.getenv("DOC_ID", "unknown-doc")
    tenant_id = os.getenv("TENANT_ID", "unknown-tenant")
    text = _read_input_text()
    summary, word_count = _summary(text)

    result = {
        "doc_id": doc_id,
        "summary": summary,
        "word_count": word_count,
        "tenant_id": tenant_id,
        "processed_at": "demo",
    }

    payload = json.dumps(result, sort_keys=True)
    print(payload, flush=True)

    Path("/tmp/result.json").write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
