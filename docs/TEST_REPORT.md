# End-to-End Test Report (Milestone 4.3)

**Project:** Creation of Intelligent Bug Diagnosis Platform with Fix Recommendation Assistance — Group 1
**Suite:** `BugAnalysisProject/tests/test_end_to_end.py`
**Command:** `cd BugAnalysisProject && python -m pytest tests -q`
**Result:** `22 passed in 1.80s`
**Embedding backend during this run:** offline hashing fallback (`EMBEDDING_BACKEND=hashing`), because the
lab runner has no network access for the MiniLM download. Re-run with
`EMBEDDING_BACKEND=sentence-transformers` on a networked machine to certify the
semantic model; all assertions are backend-agnostic.
**Isolation:** every run uses a fresh temp SQLite DB, FAISS index and watch folder
(`tests/conftest.py`), so `backend/bugs.db` is never modified.

## Five bug types exercised end to end

| # | Bug type | Ingestion channel | Fixture | Result |
|---|----------|-------------------|---------|--------|
| 1 | Database / concurrency (deadlock on `stock_levels`) | Manual JSON `POST /submit-bug` | inline payload | PASS |
| 2 | Authentication / session (SSO token dropped) | `.txt` upload `POST /upload-bug` | `fixtures/bug_auth_token.txt` | PASS |
| 3 | UI / frontend rendering (null map on mobile Safari) | `.txt` upload | `fixtures/bug_ui_render.txt` | PASS |
| 4 | Performance / memory (CSV export MemoryError) | Auto-Watch folder scan | `fixtures/bug_performance_export.log` | PASS |
| 5 | API integration (payment gateway 502) | Auto-Watch folder scan | `fixtures/bug_api_integration.log` | PASS |

For each type the suite asserts: the bug is stored with a valid severity and
status, the agent pipeline returns complete structured findings
(`bug_summary`, `error_types`, `component`, `possible_root_cause`,
`recommended_fix`, `similar_bugs`, `duplicate`, `remediation`, `rag`), and the
retrieval layer returns scored knowledge-base candidates.

## Test inventory

| Test | Milestone | What it proves | Result |
|------|-----------|----------------|--------|
| `test_health_and_meta` | 1 | App boots, CSV seeds 200 KB rows, index size == row count | PASS |
| `test_home_page_renders` | 1 | UI served with the new project title | PASS |
| `test_bug_types_end_to_end[5 cases]` | 1–3 | Five bug types, three channels, structured findings | PASS |
| `test_validation_rejects_bad_submission` | 2 | Field validation returns 400 with per-field errors | PASS |
| `test_upload_rejects_unsupported_type` | 2 | Only `.txt` / `.log` accepted | PASS |
| `test_all_bugs_and_search` | 1/2 | Legacy `/all-bugs` contract plus filtered `/api/bugs` search | PASS |
| `test_similarity_endpoint` | 1 | FAISS top-k retrieval with cosine scores | PASS |
| `test_duplicate_detection_flags_resubmission` | 3 | Duplicate agent scores a re-submitted bug | PASS |
| `test_unverified_bug_cannot_be_promoted` | 4.2 | Unverified bug promotion rejected with 409 | PASS |
| `test_resolved_and_verified_bug_grows_knowledge_base` | 4.2 | Verified fix adds 1 KB row, index grows, fix becomes retrievable | PASS |
| `test_promotion_is_idempotent` | 4.2 | Re-promoting does not duplicate KB rows | PASS |
| `test_status_workflow` | 2/4 | Valid transitions accepted, invalid status rejected | PASS |
| `test_reanalysis_is_repeatable` | 3 | Re-running the pipeline yields complete findings again | PASS |
| `test_analytics_reflect_real_data` | 4.1 | KPIs/severity/components/trend derive from live SQL; severity totals reconcile with total defects | PASS |
| `test_bug_reports_export` | 3 | Per-bug CSV structure; PDF starts with `%PDF` when ReportLab present | PASS |
| `test_analytics_exports` | 4.1 | Analytics CSV + PDF export | PASS |
| `test_bulk_bug_export` | 3 | `all_bugs.csv` contains every submission | PASS |
| `test_watch_status_and_rescan_skips_known_files` | 2 | Watch events recorded; rescan skips processed files (no duplicates) | PASS |

## Observations from the run

- Knowledge base seeded 200 historical records from `datasets/bug_dataset.csv`;
  after the verified promotion it held 201 and the vector index matched exactly.
- The promoted fix (`stock_levels` deadlock) was retrieved by a fresh similarity
  query, confirming incremental index growth without a rebuild.
- Auto-Watch processed both dropped log files on the first scan and skipped them
  on the second, so folder monitoring cannot create duplicate bugs.
- PDF export asserts `200` **or** `501`: the API returns 501 with a clear message
  when ReportLab is not installed, so the suite passes on minimal installs while
  still validating real PDF bytes when it is.

## How to reproduce

```bash
cd BugAnalysisProject
pip install -r backend/requirements.txt
python -m pytest tests -q                     # offline (hashing embedder)
EMBEDDING_BACKEND=sentence-transformers python -m pytest tests -q   # real MiniLM
```
