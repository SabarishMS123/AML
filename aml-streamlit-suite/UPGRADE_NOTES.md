# Upgrade Notes — Enterprise UI/UX + RAG Tuning Pass

## ⚠️ Do this first: rotate your credentials

The zip you sent for this upgrade contained a live `.env` file with a real
Groq API key and a Supabase **service-role** key. Those have now passed
through an upload/download and should be treated as compromised:

1. Groq console → revoke the old key, issue a new one.
2. Supabase project settings → API → regenerate the `service_role` key.
3. Put the new values in your local `.env` (never committed — `.gitignore`
   already excludes it, and it has been stripped from this delivered zip;
   only `.env.example` is included).

## 1. Table rendering bug (`<br>` tags shown as literal text)

New module: `utils/formatting.py`

- `clean_llm_markdown(text)` — inside markdown table rows, normalizes/keeps
  `<br>` tags (that's the only place a raw `<br>` is actually correct
  markdown-table syntax); outside tables, converts `<br>` runs into either
  a real newline or a bullet list. Any other stray HTML tag is escaped so
  enabling `unsafe_allow_html=True` doesn't open up arbitrary markup.
- `render_llm_markdown(st, text)` — cleans, then renders with
  `st.markdown(..., unsafe_allow_html=True)`.

Applied everywhere an LLM string reaches the UI: chat answers, chat
history replay, and the AI audit justification box on the Risk Dashboard.

## 2. UI/UX + theming

- `utils/ui.py`: `inject_custom_css()`, `metric_card()` / `metric_row()`,
  `risk_badge_html()`, `notify()` (toast wrapper), `app_header()`.
- Tech-stack line moved out of the main header into a sidebar
  **⚙️ System details** expander.
- Metric cards, upload dropzones, and document rows now use styled cards
  with shadows, rounded corners, and status pills instead of plain text.
- File uploads, CSV syncs, evaluation runs, and deletions now fire
  `st.toast()` notifications in addition to the existing inline messages.

## 3. Risk Dashboard (Plotly)

- Donut chart: risk tier distribution (High/Medium/Low), colored
  Red/Yellow/Green.
- Bar chart: total transaction volume grouped by risk level.
- Customer Risk Table: search box (Customer ID / Name), multi-select risk
  filter, emoji status-badge column, and an **⬇️ Export Risk Report (CSV)**
  button that exports the *filtered* view.

Added `plotly` to `requirements.txt`.

## 4. RAG retrieval tuning

- `match_threshold` lowered from `0.2` → `0.12` (and the fallback-trigger
  floor from `0.15` → `0.10`) in both `services/rag_chat.py` and
  `services/aml_agent.py`, so real matches phrased differently than the
  question ("PEP policy" vs "politically exposed person") aren't dropped.
- `top_k` (match_count) standardized to **5** at both call sites (was an
  inconsistent 5 / 4 default).
- Chunking tuned to **900-word chunks / 150-word overlap** (within your
  requested 800–1000 range) and is now **per-page**, so every chunk can be
  traced back to an exact page number.
- Query normalization (`normalize_query`): trims whitespace and strips
  wrapping quotes before embedding. Case is intentionally left alone —
  the embedding model already handles case, and lower-casing hurts
  acronym-heavy queries like "PEP" / "AML" / "KYC".

### Database migration required

`document_chunks` now has a `page_number` column, and the
`match_document_chunks` RPC returns `page_number` + `file_name` (joined
from `policy_documents`) so citations can show "Document.pdf, p. 4".

- **Fresh/dev database:** just re-run `database/schema.sql`.
- **Existing database with data you want to keep:** run
  `database/migration_add_page_number.sql` instead — it's additive only.
  Chunks ingested before this upgrade will show no page number until
  their source PDF is re-uploaded (existing citations still work, they
  just won't have a page number).

After migrating, **re-ingest your policy PDFs** to get page-tagged,
900/150-tuned chunks — old chunks aren't retroactively re-chunked.

## 5. Policy Chatbot UX

- Three clickable quick-prompt chips above the chat input; clicking one
  submits it immediately (no typing required).
- Every answer now shows an expandable **📚 View Cited Policy Sources**
  panel with, per source: document name + page number, the excerpt text,
  and the similarity/confidence score.

## Not changed

- `vector_store.py` — a standalone Chroma-based reference script that
  isn't imported anywhere in the running app (the app uses Supabase
  pgvector via `services/rag_chat.py`). Left untouched; let me know if you
  want it wired in or removed.
