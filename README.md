# 🐞 AI-Powered Bug Analysis System

**Infosys Springboard Virtual Internship 7.0 — Milestone 1**

An end-to-end Retrieval-Augmented Generation (RAG) system that ingests bug
reports, embeds them with `all-MiniLM-L6-v2`, retrieves the top-5 most
similar historical defects from a FAISS vector index, and surfaces
root-cause + fix suggestions through a professional dark-blue web UI.

---

## ✨ Features

- **Bug Submission Module** — manual form + `.txt` / `.log` upload
- **Historical Knowledge Base** — seeded from Mozilla / Apache / Eclipse / Kaggle style records
- **RAG Pipeline** — Sentence-Transformer embeddings + FAISS `IndexFlatIP` (cosine)
- **Top-5 Semantic Similarity** — score, root cause, suggested fix, category
- **Multi-Agent Architecture (design)** — Triage / Log Analysis / Root Cause / Duplicate / Remediation
- **SQLite storage** for `bugs`, `knowledge_base`, `embeddings`
- **Professional dashboard** — gradient cards, animations, dark blue theme
- **REST APIs** — `/health`, `/submit-bug`, `/upload-bug`, `/all-bugs`, `/knowledge-base`, `/stats`, `/agents`
- **Documentation** — Mermaid architecture, workflow, DFD, ER diagrams

---

## 🧱 Tech Stack

Python 3.11+, Flask, HTML5/CSS3/JavaScript, SQLite,
Sentence-Transformers (`all-MiniLM-L6-v2`), FAISS, Pandas, NumPy.

---

## 🚀 Installation

```bash
git clone <your-repo-url>
cd BugAnalysisProject
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000>.

The first run downloads the sentence-transformer model (~90 MB) and
builds the FAISS index from `datasets/historical_bugs.csv`. Subsequent
runs load the persisted index from `models/`.

---

## 📁 Folder Structure

```
BugAnalysisProject/
├── app.py
├── requirements.txt
├── README.md
├── .gitignore
├── backend/
│   ├── __init__.py
│   ├── config.py
│   ├── database.py
│   ├── embeddings.py
│   ├── knowledge_base.py
│   ├── agents.py
│   └── server.py
├── frontend/
│   ├── templates/index.html
│   └── static/
│       ├── css/styles.css
│       └── js/app.js
├── datasets/historical_bugs.csv
├── docs/
│   ├── PROJECT_REPORT.md
│   ├── INSTALLATION.md
│   ├── architecture.mmd
│   ├── workflow.mmd
│   ├── data_flow.mmd
│   └── er_diagram.mmd
└── models/         # FAISS index + metadata (auto-generated)
```

---

## 🔌 REST API

| Method | Endpoint          | Purpose                              |
| ------ | ----------------- | ------------------------------------ |
| GET    | `/health`         | Health check                         |
| POST   | `/submit-bug`     | Submit bug JSON + get similar bugs   |
| POST   | `/upload-bug`     | Upload `.txt` / `.log` bug report    |
| GET    | `/all-bugs`       | All submitted bugs                   |
| GET    | `/knowledge-base` | KB entries                           |
| GET    | `/stats`          | Dashboard stats                      |
| GET    | `/agents`         | Multi-agent design specification     |

Example:

```bash
curl -X POST http://127.0.0.1:5000/submit-bug \
  -H "Content-Type: application/json" \
  -d '{"title":"SSL handshake fails","description":"TLS 1.3 handshake error","severity":"High","component":"Network"}'
```

---

## 📚 Documentation

- [Project Report](docs/PROJECT_REPORT.md)
- [Installation Guide](docs/INSTALLATION.md)
- [Architecture Diagram](docs/architecture.mmd)
- [Workflow Diagram](docs/workflow.mmd)
- [Data Flow Diagram](docs/data_flow.mmd)
- [ER Diagram](docs/er_diagram.mmd)

---

## ✅ Milestone 1 Deliverables

Defect-analysis study · RAG architecture · Semantic similarity · Bug-report
schema · Architecture design · Agent responsibilities · Orchestration flow ·
KB model · Working bug submission · File upload · Historical KB · Data
preprocessing · Chunking · Embedding generation · FAISS indexing · Working
similarity search · Design docs · Tech stack · GitHub-ready.

---

© 2025 — Built for the Infosys Springboard Virtual Internship 7.0.
