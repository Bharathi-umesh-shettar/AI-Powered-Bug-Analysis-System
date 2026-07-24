# Installation Guide

## Prerequisites

- Python **3.11+**
- pip
- ~500 MB free disk (for the sentence-transformer model cache)

## Steps

```bash
git clone <your-repo-url>
cd BugAnalysisProject

python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate

pip install --upgrade pip
pip install -r requirements.txt

python app.py
```

Open <http://127.0.0.1:5000>.

## Troubleshooting

| Issue                                | Fix                                                   |
| ------------------------------------ | ----------------------------------------------------- |
| `faiss` install fails on Windows     | `pip install faiss-cpu==1.8.0` (needs Python ≤ 3.11)  |
| First run is slow                    | Model download (~90 MB) — cached afterwards           |
| `sqlite3.OperationalError: database is locked` | Close other clients; the app opens with a 30s timeout |
| Port 5000 already in use             | Edit `app.py` and change `port=5000`                  |
