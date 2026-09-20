"""
utils/formatting.py

Post-processing helpers for text that comes back from the LLM (Groq) before
it is handed to `st.markdown`.

Why this exists
----------------
Groq/Llama occasionally emits markdown tables where a cell's line breaks are
encoded as literal `<br>` / `<br/>` tags (a common pattern models pick up
from HTML-flavoured training data), e.g.:

    | Document Type | Notes |
    |---|---|
    | Proof of address | Recent bank statement<br>Residential utility bill |

`st.markdown(text)` (the default, `unsafe_allow_html=False`) does not
interpret raw HTML, so those tags show up as ugly literal text:
"Recent bank statement<br>Residential utility bill".

`clean_llm_markdown` normalizes this safely:
  - Inside a markdown table row (a line containing `|`), `<br>` tags are
    kept (tables are the one place raw `<br>` is actually the *correct*
    markdown-table way to do a line break inside a cell) but normalized to
    a single canonical form and any stray whitespace around them is tidied.
  - Outside a table, `<br>` tags are converted to real newlines (or, when
    they're separating short list-like fragments, into a bullet list) since
    a bare `<br>` in prose is never desired.
  - Any other raw HTML tags outside of tables are escaped so we don't
    accidentally allow arbitrary markup through when the caller renders
    with `unsafe_allow_html=True` for table support.
"""

from __future__ import annotations

import html
import re

_BR_TAG_RE = re.compile(r"<br\s*/?>", flags=re.IGNORECASE)
_ANY_TAG_RE = re.compile(r"<(?!br\s*/?>)([^>]+)>", flags=re.IGNORECASE)


def _is_table_row(line: str) -> bool:
    """Heuristic: a markdown table row/separator contains a pipe and isn't
    just incidental punctuation."""
    stripped = line.strip()
    if not stripped:
        return False
    return stripped.count("|") >= 1


def clean_llm_markdown(text: str) -> str:
    """Normalize `<br>`-style line breaks so markdown (and any embedded
    markdown tables) render correctly under `st.markdown(..., unsafe_allow_html=True)`.

    Safe to call on any LLM output, including text with no tables at all.
    """
    if not text:
        return text

    lines = text.split("\n")
    cleaned_lines: list[str] = []

    for line in lines:
        if _is_table_row(line):
            # Keep <br> tags (they're valid inside an HTML-rendered table
            # cell) but collapse duplicates / stray whitespace around them.
            normalized = _BR_TAG_RE.sub("<br>", line)
            normalized = re.sub(r"(<br>\s*){2,}", "<br>", normalized)
            # Escape any *other* stray tags so we don't open up arbitrary
            # HTML injection when the caller uses unsafe_allow_html=True.
            normalized = _ANY_TAG_RE.sub(lambda m: html.escape(m.group(0)), normalized)
            cleaned_lines.append(normalized)
        else:
            # Outside a table: turn <br> into a real newline. If a line has
            # several <br>-separated fragments, present them as a bullet
            # list instead of one run-on line.
            if _BR_TAG_RE.search(line):
                fragments = [f.strip() for f in _BR_TAG_RE.split(line) if f.strip()]
                if len(fragments) > 1:
                    cleaned_lines.append("\n".join(f"- {f}" for f in fragments))
                else:
                    cleaned_lines.append("\n".join(fragments))
            else:
                escaped = _ANY_TAG_RE.sub(lambda m: html.escape(m.group(0)), line)
                cleaned_lines.append(escaped)

    return "\n".join(cleaned_lines)


def render_llm_markdown(st_module, text: str, **kwargs) -> None:
    """Convenience wrapper: clean then render via st.markdown with HTML
    enabled (required so <br> tags kept inside table cells actually take
    effect). Use this everywhere an LLM answer / reasoning string reaches
    the UI instead of calling st.markdown / st.write directly on raw text.
    """
    st_module.markdown(clean_llm_markdown(text), unsafe_allow_html=True, **kwargs)


def normalize_query(question: str) -> str:
    """Normalize a user query before embedding / retrieval:
      - trims surrounding whitespace
      - strips wrapping straight or curly quotes the user may have pasted
      - collapses internal whitespace runs

    Case is intentionally left untouched — the sentence-transformer model
    is already case-robust and lower-casing can hurt retrieval for acronyms
    (e.g. "PEP", "AML", "KYC").
    """
    if not question:
        return question
    q = question.strip()
    q = q.strip("\"'“”‘’")
    q = q.strip()
    q = re.sub(r"\s+", " ", q)
    return q
