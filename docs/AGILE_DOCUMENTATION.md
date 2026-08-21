# Agile Documentation — Intelligent Bug Diagnosis Platform

**Project:** Creation of Intelligent Bug Diagnosis Platform with Fix Recommendation Assistance — Group 1  
**Framework:** Scrum  
**Team:** Group 1  
**Sprint cadence:** Milestone-driven (M1 → M2 → M3 → M4)  

---

## 1. Product Vision

Build a Flask + RAG platform that ingests bug reports, retrieves similar historical defects using Sentence Transformers and FAISS, runs a multi-agent diagnosis, and recommends structured fixes. The system learns from verified resolutions, analyses defect patterns, and exports reports for development teams.

---

## 2. Product Backlog

| ID | Backlog Item | Priority | Milestone | Status |
|----|--------------|----------|-----------|--------|
| PB-1 | Bug submission form with structured fields | High | M1 | Done |
| PB-2 | SQLite persistence for bug records | High | M1 | Done |
| PB-3 | Sentence-Transformer / FAISS RAG retrieval | High | M1 | Done |
| PB-4 | Input validation and `.txt`/`.log` upload parser | High | M2 | Done |
| PB-5 | Auto-Watch folder monitor for automatic ingestion | High | M2 | Done |
| PB-6 | Multi-agent diagnosis pipeline (analysis, duplicate, remediation) | High | M3 | Done |
| PB-7 | PDF/CSV report export | Medium | M3 | Done |
| PB-8 | Defect pattern analytics dashboard | High | M4 | Done |
| PB-9 | Knowledge-base growth from verified fixes | High | M4 | Done |
| PB-10 | End-to-end pytest suite across five bug types | High | M4 | Done |
| PB-11 | Technical and Agile documentation | Medium | M4 | Done |

---

## 3. User Stories

### Milestone 1 — Core Ingestion & Retrieval
- **US-1.1** As a QA engineer, I want to submit a bug report via a web form so that it is stored and diagnosed.
- **US-1.2** As a developer, I want the system to retrieve similar historical bugs so that I can compare symptoms and fixes.
- **US-1.3** As a maintainer, I want the knowledge base seeded from a CSV dataset on first launch so that retrieval works immediately.

### Milestone 2 — Validation & Auto-Watch
- **US-2.1** As a QA engineer, I want validation errors returned per field so that I can correct submissions quickly.
- **US-2.2** As a tester, I want to upload `.txt` or `.log` bug reports so that free-form logs are parsed automatically.
- **US-2.3** As a DevOps engineer, I want a watched folder that auto-ingests new log files so that monitoring pipelines feed the platform.

### Milestone 3 — Diagnosis & Reporting
- **US-3.1** As a developer, I want structured findings (root cause, recommended fix, prevention steps) so that I can act on the diagnosis.
- **US-3.2** As a triage lead, I want duplicate detection with confidence so that I can avoid re-analysing known issues.
- **US-3.3** As a manager, I want per-bug PDF/CSV reports so that findings can be shared offline.

### Milestone 4 — Analytics & Knowledge Growth
- **US-4.1** As a product owner, I want analytics on severity, component, and trend so that I can spot recurring defect patterns.
- **US-4.2** As a developer, I want resolved and verified fixes added to the knowledge base so that future retrieval improves.
- **US-4.3** As a mentor, I want an end-to-end test suite covering five bug types so that the platform is demonstrably reliable.

---

## 4. Sprint Planning

Sprints are mapped directly to the four implemented milestones. Each sprint delivers a potentially usable increment.

| Sprint | Goal | Key Deliverables | Backlog Items |
|--------|------|------------------|---------------|
| Sprint 1 (M1) | Ingest, store, and retrieve bugs | Flask app, SQLite schema, FAISS index, seeded knowledge base | PB-1, PB-2, PB-3 |
| Sprint 2 (M2) | Harden ingestion channels | Field validation, `.txt`/`.log` parser, Auto-Watch monitor | PB-4, PB-5 |
| Sprint 3 (M3) | Generate and export diagnoses | Analysis/Duplicate/Remediation agents, PDF/CSV reports | PB-6, PB-7 |
| Sprint 4 (M4) | Learn from data and prove quality | Analytics module, KB growth, E2E tests, documentation | PB-8, PB-9, PB-10, PB-11 |

### Sprint 4 Task Breakdown
| Task | Owner | Status |
|------|-------|--------|
| Implement KPI, severity, component, trend, and theme analytics | Group | Done |
| Implement verified-fix promotion to knowledge base + FAISS index | Group | Done |
| Create five bug-type fixtures (database, auth, UI, performance, integration) | Group | Done |
| Write end-to-end pytest suite covering all ingestion channels | Group | Done |
| Record test results and update technical documentation | Group | Done |

---

## 5. Definition of Done

A backlog item is considered Done when **all** of the following are true:

1. **Code complete:** The feature is implemented in the backend or frontend module.
2. **Integrated:** It works with the existing Flask app, SQLite schema, and FAISS retrieval layer.
3. **Tested:** Unit-level or end-to-end tests pass; manual verification is recorded where automated tests are not applicable.
4. **Documented:** Relevant sections are added to `docs/TECHNICAL_DOCUMENTATION.md` and this Agile document.
5. **Demo-ready:** The feature can be shown through the dashboard or API without errors.
6. **No regression:** Existing endpoints and the FAISS index continue to function.

---

## 6. Testing Evidence

- **Test suite:** `BugAnalysisProject/tests/test_end_to_end.py`
- **Run command:** `cd BugAnalysisProject && python -m pytest tests -q`
- **Latest recorded result:** `22 passed`
- **Embedding backend during run:** offline hashing fallback (`EMBEDDING_BACKEND=hashing`) for environments without network access.
- **Coverage:** five distinct bug types across three ingestion channels (manual JSON, `.txt`/`.log` upload, Auto-Watch folder scan).
- **Detailed report:** [TEST_REPORT.md](TEST_REPORT.md)

### Test Categories
| Category | Tests |
|----------|-------|
| Boot / health | `test_health_and_meta`, `test_home_page_renders` |
| Ingestion | `test_bug_types_end_to_end[5 cases]`, `test_validation_rejects_bad_submission`, `test_upload_rejects_unsupported_type` |
| Retrieval | `test_similarity_endpoint`, `test_duplicate_detection_flags_resubmission` |
| Knowledge growth | `test_unverified_bug_cannot_be_promoted`, `test_resolved_and_verified_bug_grows_knowledge_base`, `test_promotion_is_idempotent` |
| Workflow | `test_status_workflow`, `test_reanalysis_is_repeatable` |
| Analytics | `test_analytics_reflect_real_data`, `test_analytics_exports` |
| Reports | `test_bug_reports_export`, `test_bulk_bug_export` |
| Auto-Watch | `test_watch_status_and_rescan_skips_known_files` |

---

## 7. Retrospective Notes

- **What went well:** The milestone-driven sprints produced clear increments. The FAISS index persisted across restarts, and verified fixes were incrementally added without rebuilding the index.
- **What to improve:** Future sprints could add role-based access control and a richer frontend framework.
- **Action item:** Keep the E2E suite green before any new feature merge.
