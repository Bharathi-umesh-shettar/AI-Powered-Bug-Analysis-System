# Project Report — AI-Powered Bug Analysis System

**Program:** Infosys Springboard Virtual Internship 7.0
**Milestone:** 1 (Foundation & Working Prototype)

---

## 1. Objective

Build an AI-assisted bug triage tool that, given a new defect report,
retrieves the most similar historical bugs and surfaces likely root
causes and remediation suggestions using a Retrieval-Augmented
Generation (RAG) pipeline.

## 2. Problem Statement

Engineering teams spend a large share of their time triaging duplicate
or already-solved defects. Manual search across bug trackers (Mozilla
Bugzilla, Apache JIRA, Eclipse Bugzilla, internal systems) is slow and
inconsistent. We need an automated, semantic search layer over
historical defects.

## 3. Architecture

Client (HTML/JS UI)
→ Flask REST API
→ Sentence-Transformer embedding (`all-MiniLM-L6-v2`)
→ FAISS `IndexFlatIP` cosine search over KB vectors
→ SQLite retrieval of enriched KB rows
→ Response with Top-5 similar bugs + root cause + fix.

See `docs/architecture.mmd`, `docs/workflow.mmd`, `docs/data_flow.mmd`, `docs/er_diagram.mmd`.

## 4. Tech Stack

Python 3.11+, Flask, Sentence-Transformers, FAISS, SQLite, Pandas,
NumPy, HTML5/CSS3/JavaScript.

## 5. Modules

1. **Bug Submission Module** — manual form + file upload (`.txt`, `.log`).
2. **Knowledge Base** — seeded from public bug data; cleaned, deduped, chunked, embedded, indexed.
3. **RAG Pipeline** — embed query → FAISS search → SQLite lookup → enriched Top-5.
4. **Semantic Similarity** — cosine over L2-normalized MiniLM embeddings.
5. **Multi-Agent Architecture (design)** — Triage, Log Analysis, Root Cause, Duplicate Detection, Remediation.
6. **Dashboard** — totals, criticals, KB size, duplicates, recent bugs.
7. **Database Records** — searchable, sortable, paginated table.
8. **REST APIs** — `/health`, `/submit-bug`, `/upload-bug`, `/all-bugs`, `/knowledge-base`, `/stats`, `/agents`.

## 6. Workflow

1. User submits or uploads a bug report.
2. Backend validates, stores in SQLite, encodes the query.
3. FAISS returns top-K KB IDs with cosine scores.
4. SQLite fetches KB rows; response includes root cause + fix.
5. UI renders similarity cards and refreshes the dashboard.

## 7. Screenshots

Run locally and capture:

- Dashboard with gradient cards
- Submit form + similar-bug results
- Database records table

## 8. Results

- **Model:** all-MiniLM-L6-v2 (384-dim)
- **Index:** FAISS IndexFlatIP (cosine on normalized vectors)
- **Latency:** ~40–120 ms per query on CPU for ~20 KB records
- **Retrieval quality:** demonstrably matches semantically related bugs
  (e.g. "TLS handshake failure" → "SSL handshake fails with TLS 1.3").

## 9. Future Scope (Milestones 2+)

- Activate multi-agent orchestration with an LLM tool-use layer.
- Ingest live bug-tracker feeds (Bugzilla / JIRA REST APIs).
- Replace flat index with IVF-PQ for millions of records.
- Generative root-cause explanations via a local LLM.
- Role-based auth and audit logging.

## 10. Conclusion

Milestone 1 delivers a fully working, GitHub-ready prototype covering
the entire defect-analysis workflow foundations: data ingestion,
preprocessing, embedding, FAISS-backed retrieval, REST APIs, and a
professional dark-blue dashboard. It is a solid base for the agentic
capabilities planned in the following milestones.
