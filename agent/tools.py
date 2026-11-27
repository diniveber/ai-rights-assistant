"""Agent extensions: RAG over the rights knowledge base, local file reading, summary export."""

import json
import re
import zipfile
from datetime import datetime
from pathlib import Path

from rank_bm25 import BM25Okapi

from agent import config

KB_PATH = Path(__file__).resolve().parent / "data" / "rights.json"
RIGHTS: list[dict] = json.loads(KB_PATH.read_text(encoding="utf-8"))
RIGHTS_BY_ID = {r["id"]: r for r in RIGHTS}
CATEGORIES = sorted({r["category"] for r in RIGHTS})

SUPPORTED_FILE_TYPES = {".txt", ".md", ".csv", ".json", ".pdf", ".docx"}

# ---------------------------------------------------------------- RAG

_HEBREW_PREFIXES = "והבלמשכ"
_NIQQUD = re.compile(r"[֑-ׇ]")
_TOKEN = re.compile(r"[א-תa-zA-Z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Simple Hebrew-aware tokenizer: strip niqqud and also index tokens without a 1-letter prefix."""
    tokens = []
    for tok in _TOKEN.findall(_NIQQUD.sub("", text.lower())):
        tokens.append(tok)
        if len(tok) > 3 and tok[0] in _HEBREW_PREFIXES:
            tokens.append(tok[1:])
    return tokens


def _doc_text(r: dict) -> str:
    return " ".join([r["name"], r["category"], r["eligibility"], r["description"], " ".join(r["what_to_check"])])


_bm25 = BM25Okapi([_tokenize(_doc_text(r)) for r in RIGHTS])


def search_rights(keywords: list[str], categories: list[str], k: int = 6) -> list[dict]:
    """Retrieve candidate rights: every right in the chosen categories plus BM25 top-k on the keywords."""
    selected: dict[str, dict] = {}
    query = _tokenize(" ".join(keywords))
    if query:
        scores = _bm25.get_scores(query)
        ranked = sorted(range(len(RIGHTS)), key=lambda i: scores[i], reverse=True)
        for i in ranked[:k]:
            if scores[i] > 0:
                selected[RIGHTS[i]["id"]] = RIGHTS[i]
    for r in RIGHTS:
        if r["category"] in categories:
            selected.setdefault(r["id"], r)
    return list(selected.values())[:10]


# ---------------------------------------------------------------- files


class FileReadError(RuntimeError):
    pass


def read_file(path_str: str) -> tuple[str, str]:
    """Read a local text/PDF/DOCX file. Returns (file_name, text), truncated to MAX_FILE_CHARS."""
    path = Path(path_str.strip().strip('"').strip("'")).expanduser()
    if not path.is_file():
        raise FileReadError(f"הקובץ לא נמצא: {path}")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_FILE_TYPES:
        raise FileReadError(f"סוג קובץ לא נתמך ({suffix}). נתמכים: {', '.join(sorted(SUPPORTED_FILE_TYPES))}")

    try:
        if suffix == ".pdf":
            from pypdf import PdfReader
            text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
        elif suffix == ".docx":
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml").decode("utf-8")
            text = re.sub(r"<[^>]+>", "", re.sub(r"</w:p>", "\n", xml))
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001 – surface any parsing failure as a clear message
        raise FileReadError(f"לא ניתן לקרוא את הקובץ {path.name}: {e}") from e

    text = text.strip()
    if not text:
        raise FileReadError(f"לא נמצא טקסט בקובץ {path.name} (ייתכן שזה PDF סרוק)")
    if len(text) > config.MAX_FILE_CHARS:
        text = text[: config.MAX_FILE_CHARS] + "\n...[הקובץ קוצר]"
    return path.name, text


# ---------------------------------------------------------------- summary export


def summary_path() -> Path:
    return Path.cwd() / "summaries" / f"summary_{datetime.now():%Y%m%d_%H%M%S}.txt"


def export_summary(text: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
