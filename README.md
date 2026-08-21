# Creation of Intelligent Bug Diagnosis Platform with Fix Recommendation Assistance — Group 1

A full-stack Flask + RAG platform that ingests bug reports, retrieves similar
historical defects with **Sentence Transformers + FAISS**, runs a **multi-agent
diagnosis** to produce structured findings and a recommended fix, exports
PDF/CSV reports, analyses **defect patterns**, and **grows its own knowledge
base** from verified fixes.

Milestones: **M1** submission + storage + RAG · **M2** validation, `.txt`/`.log`
upload, Auto-Watch folder monitoring · **M3** multi-agent diagnosis + reports ·
**M4** defect pattern analytics, knowledge-base growth, end-to-end testing,
documentation.

---

## Tech Stack

- **Backend:** Python 3.10+, Flask, SQLite
- **AI / RAG:** Sentence Transformers (`all-MiniLM-L6-v2`), FAISS (cosine similarity), deterministic hashing fallback for offline runs
- **Reports:** ReportLab (PDF, optional), csv (always)
- **Frontend:** HTML5, CSS3, vanilla JavaScript — five-tab responsive dashboard
- **Testing:** pytest end-to-end suite

## Project Structure

```
BugAnalysisProject/
├── backend/
│   ├── app.py               # Flask app + REST APIs
│   ├── config.py            # all paths / thresholds (env-overridable)
│   ├── database.py          # SQLite schema + non-destructive migration
│   ├── rag.py               # embeddings + FAISS index (persisted)
│   ├── ingest.py            # validation + log/text parsing
│   ├── agents.py            # analysis / duplicate / remediation agents
│   ├── service.py           # shared ingest -> diagnose -> persist path
│   ├── autowatch.py         # background folder monitor (M2)
│   ├── knowledge.py         # verified-fix knowledge-base growth (M4.2)
│   ├── analytics.py         # defect pattern analytics (M4.1)
│   ├── reports.py           # PDF / CSV exports
│   ├── import_dataset.py    # CSV -> knowledge_base importer
│   └── requirements.txt
├── datasets/bug_dataset.csv # 200-record historical knowledge base
├── logs_watch/              # drop .log/.txt here for Auto-Watch
├── templates/index.html
├── static/{style.css,script.js}
├── tests/                   # end-to-end suite + 5 bug fixtures (M4.3)
└── docs/
    ├── TECHNICAL_DOCUMENTATION.md
    └── TEST_REPORT.md
```

## Installation

```bash
cd BugAnalysisProject/backend
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Running

```bash
cd BugAnalysisProject/backend
python app.py
```

Open <http://localhost:5000>. The first launch seeds `knowledge_base` from the
CSV, downloads `all-MiniLM-L6-v2` (~90 MB) and builds/persists the FAISS index.
No network? Run with `EMBEDDING_BACKEND=hashing` to use the offline embedder.

## Using the dashboard

1. **Submit** — fill the form (or upload a `.txt`/`.log` report) and get
   structured findings: summary, error types, component, root cause,
   recommended fix, prevention steps, duplicate verdict, top-5 similar bugs.
2. **Records** — search/filter by text, status, severity, component; re-analyze,
   change status, download per-bug PDF/CSV, or export all bugs.
3. **Auto-Watch** — start/stop the monitor or scan once; drop files into
   `logs_watch/` and they are ingested and diagnosed automatically.
4. **Analytics** — KPIs, severity/status distribution, component and category
   frequency, time trend, recurring themes; export PDF/CSV.
5. **Knowledge Base** — browse/search entries; resolve a bug with a confirmed
   fix and mark it **Resolved & Verified** to add it to the knowledge base and
   the live FAISS index.

## REST API

Milestone 1 contracts are unchanged (`/`, `/health`, `/submit-bug`,
`/upload-bug`, `/all-bugs`). Full endpoint table:
[docs/TECHNICAL_DOCUMENTATION.md](docs/TECHNICAL_DOCUMENTATION.md#8-http-api).

### `.txt` / `.log` upload format

```
Title: Login fails on Safari
Description: OAuth redirect drops the session cookie.
Severity: High
Component: auth-service
Stack_trace: TypeError: cannot read property 'token' of undefined
```

Free-form logs work too — the parser infers title, severity, component and
stack trace heuristically.

## Configuration

Every path and threshold lives in `backend/config.py` and is env-overridable:
`BUG_DB_PATH`, `FAISS_INDEX_PATH`, `BUG_DATASET_PATH`, `WATCH_DIR`,
`WATCH_INTERVAL_SECONDS`, `REPORT_DIR`, `EMBEDDING_MODEL`,
`EMBEDDING_BACKEND` (`auto|sentence-transformers|hashing`), `RAG_TOP_K`,
`DUPLICATE_THRESHOLD`, `SIMILAR_THRESHOLD`, `AUTOWATCH_ON_START`.

## Testing

```bash
cd BugAnalysisProject
python -m pytest tests -q
```

Runs in an isolated temp database / index / watch folder — your `bugs.db` is
never touched. Latest result: **22 passed**, covering five distinct bug types
across all three ingestion channels. See [docs/TEST_REPORT.md](docs/TEST_REPORT.md).

## How RAG works

1. Knowledge entries are encoded to 384-dim vectors and L2-normalised.
2. `faiss.IndexFlatIP` gives cosine similarity; index + metadata are persisted.
3. Each submission is encoded (title + description + stack trace) and searched.
4. Top-k matches feed the duplicate verdict and the fix recommendation.
5. Verified fixes are appended incrementally, so retrieval improves over time.

## Architecture

```
 ┌──────────┐        ┌──────────────┐  SQL   ┌────────────┐
 │ Browser  │───────▶│  Flask app   │───────▶│ SQLite DB  │
 │ 5-tab UI │◀───────│  (app.py)    │◀───────│ bugs.db    │
 └──────────┘        └───┬───┬──────┘        └────────────┘
 logs_watch/ ──▶ autowatch│   │ service.ingest_and_diagnose
                          │   ▼
                          │  ┌──────────────────────────────┐
                          │  │ DiagnosisPipeline            │
                          │  │ Analysis▸Duplicate▸Remediation│
                          │  └───────────┬──────────────────┘
                          │              ▼
                          │      ┌───────────────┐   ┌──────────────┐
                          │      │ MiniLM encode │──▶│ FAISS index  │
                          │      └───────────────┘   └──────┬───────┘
                          ▼                  verified fixes │
                 analytics / reports ◀───── knowledge.py ────┘
```

## Project Documentation

- [MIT License](../LICENSE)
- [Agile Documentation](docs/AGILE_DOCUMENTATION.md)
- [Technical Documentation](docs/TECHNICAL_DOCUMENTATION.md)
- [Test Report](docs/TEST_REPORT.md)

## License

MIT — free for academic and Infosys Springboard Internship submissions.
