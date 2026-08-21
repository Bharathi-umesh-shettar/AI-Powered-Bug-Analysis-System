# Technical Documentation

**Project:** Creation of Intelligent Bug Diagnosis Platform with Fix Recommendation Assistance — Group 1
**Stack:** Python 3.10+, Flask, SQLite, Sentence Transformers (`all-MiniLM-L6-v2`), FAISS

---

## 1. Purpose

The platform ingests software bug reports (manually, by file upload, or by
watching a log folder), retrieves semantically similar historical defects with a
RAG pipeline, runs a multi-agent diagnosis to produce structured findings and a
recommended fix, exports reports, analyses defect patterns, and grows its own
knowledge base from bugs that engineers mark **Resolved & Verified**.

## 2. Module map

| File | Responsibility |
|------|----------------|
| `backend/config.py` | Single source of truth for paths, thresholds, severities, statuses. Everything overridable by env var. |
| `backend/database.py` | SQLite connection helpers, non-destructive schema migration, CRUD + filtered search. |
| `backend/rag.py` | Embedding backend selection, FAISS (or numpy fallback) index, persistence, incremental `add_entry`. |
| `backend/ingest.py` | Field validation and free-text/log parsing into bug fields. |
| `backend/agents.py` | `AnalysisAgent`, `DuplicateDetectionAgent`, `RemediationAgent`, orchestrated by `DiagnosisPipeline`. |
| `backend/service.py` | Shared ingest + diagnose + persist path used by every channel. |
| `backend/autowatch.py` | Background folder poller with per-file dedup via `watch_events`. |
| `backend/knowledge.py` | Eligibility gate and promotion of verified fixes into `knowledge_base` + index. |
| `backend/analytics.py` | SQL-driven KPIs, trends, component/category frequency, recurring themes. |
| `backend/reports.py` | CSV always, PDF via ReportLab when installed. |
| `backend/app.py` | Flask routes (Milestone 1 contracts preserved). |
| `templates/`, `static/` | Five-tab dashboard UI (submit, records, auto-watch, analytics, knowledge base). |
| `tests/` | Milestone 4.3 end-to-end suite + fixtures. |

## 3. Data model

`bugs` keeps its original columns (`id`, `title`, `description`, `severity`,
`stack_trace`, `created_at`) and adds, via additive `ALTER TABLE` on startup:

| Column | Meaning |
|--------|---------|
| `status` | One of `Open`, `In Progress`, `Resolved`, `Resolved & Verified`, `Closed`. |
| `component` | Detected or supplied subsystem. |
| `category` | Defect family used by analytics. |
| `source`, `source_file` | `manual` / `upload` / `autowatch` provenance. |
| `findings_json` | Serialised structured findings from the last pipeline run. |
| `root_cause`, `confirmed_fix`, `resolution_details` | Engineer-verified outcome. |
| `verified`, `verified_at` | Verification flag driving knowledge-base growth. |
| `promoted_kb_id` | `knowledge_base.bug_id` created by promotion (prevents duplicates). |
| `updated_at` | Last mutation timestamp. |

`knowledge_base` retains its dataset schema (`bug_id`, `title`, `description`,
`category`, `severity`, `root_cause`, `suggested_fix`, `created_at`).
`watch_events` records `(path, size, mtime, processed_at, bug_id)` so a log file
is never ingested twice.

## 4. Retrieval layer

1. Text for each knowledge entry = `title + description + root_cause + suggested_fix`.
2. Encoded to 384-dim vectors; `EMBEDDING_BACKEND=auto` uses Sentence
   Transformers when importable and falls back to a deterministic hashing
   embedder for offline/CI use (`hashing`), or fails loudly with
   `sentence-transformers`.
3. Vectors are L2-normalised and inserted into `faiss.IndexFlatIP`, so inner
   product equals cosine similarity. When `faiss` is unavailable a numpy
   matrix search with identical semantics is used.
4. The index and its metadata are persisted (`faiss.index`, `faiss_meta.json`)
   and reloaded on boot; `add_entry` appends a single verified fix without a
   full rebuild.

## 5. Multi-agent diagnosis

`DiagnosisPipeline.run(bug)` returns one structured findings object:

```
bug_summary, error_types[], component, possible_root_cause,
recommended_fix, prevention[], similar_bugs[], duplicate,
duplicate_status, duplicate_confidence, remediation, rag
```

- **AnalysisAgent** — normalises the report, extracts exception/error types from
  the stack trace, infers component and category, writes the summary.
- **DuplicateDetectionAgent** — top-1 retrieval score against thresholds
  `DUPLICATE_THRESHOLD=0.85` (likely duplicate) and `SIMILAR_THRESHOLD=0.60`
  (related), plus shared-term reasoning for an explainable verdict.
- **RemediationAgent** — synthesises the recommended fix and prevention steps
  from the retrieved `root_cause` / `suggested_fix` fields, weighted by score.

Findings are stored in `findings_json`, so reports and the UI never recompute.

## 6. Knowledge base growth (Milestone 4.2)

`POST /api/bugs/<id>/resolve` sets root cause, confirmed fix and the
`verified` flag. Promotion (`knowledge.promote_to_knowledge_base`) requires:
verified is true, a non-empty confirmed fix and root cause, and no existing
`promoted_kb_id`. On success it inserts a `knowledge_base` row, calls
`rag.add_entry`, and records `promoted_kb_id` on the bug — the platform gets
smarter with each verified fix while unverified noise stays out.

## 7. Analytics (Milestone 4.1)

`GET /api/analytics` computes, from live SQL only: KPIs
(`total_defects`, `resolved_defects`, `critical_defects`,
`knowledge_base_entries`, resolution rate, duplicate rate), severity and status
distributions, component and category frequency, a time trend
(`granularity=day|week|month`), recurring themes from tokenised titles, and
top knowledge-base matches. Exported via `/api/analytics/report.csv` and
`/api/analytics/report.pdf`.

## 8. HTTP API

Milestone 1 contracts unchanged: `GET /`, `GET /health`, `POST /submit-bug`,
`POST /upload-bug`, `GET /all-bugs`.

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/meta` | Title, thresholds, index stats, watch state. |
| GET | `/api/bugs` | Filtered search (`q`, `status`, `severity`, `component`). |
| GET | `/api/bugs/<id>` | Bug + findings + KB eligibility. |
| POST | `/api/bugs/<id>/analyze` | Re-run the pipeline. |
| POST | `/api/bugs/<id>/status` | Workflow transition. |
| POST | `/api/bugs/<id>/resolve` | Resolve, verify, optionally promote. |
| POST | `/api/bugs/<id>/promote` | Manual promotion. |
| POST | `/api/similar` | Ad-hoc RAG query. |
| GET | `/api/knowledge` | Browse/search knowledge base. |
| GET/POST | `/api/watch/status\|scan\|start\|stop` | Auto-Watch control. |
| GET | `/api/analytics` | Defect pattern report. |
| GET | `/api/bugs/<id>/report.pdf\|.csv`, `/api/bugs/export.csv`, `/api/analytics/report.pdf\|.csv` | Exports (PDF returns 501 if ReportLab is absent). |

## 9. Configuration

`BUG_DB_PATH`, `FAISS_INDEX_PATH`, `FAISS_META_PATH`, `BUG_DATASET_PATH`,
`WATCH_DIR`, `WATCH_INTERVAL_SECONDS`, `WATCH_EXTENSIONS`, `WATCH_MAX_BYTES`,
`REPORT_DIR`, `EMBEDDING_MODEL`, `EMBEDDING_BACKEND`, `RAG_TOP_K`,
`DUPLICATE_THRESHOLD`, `SIMILAR_THRESHOLD`, `AUTOWATCH_ON_START`,
`APP_TITLE`, `APP_GROUP`.

## 10. Testing

`cd BugAnalysisProject && python -m pytest tests -q` — 22 tests covering the
five required bug types across all three ingestion channels, validation,
duplicate detection, KB growth, analytics and exports. See
[TEST_REPORT.md](TEST_REPORT.md).
