# Notices and third-party components

**This project is free to use, copy and share** (code: MIT License, see `LICENSE`).
It collects no analytics, shows no advertisements and sends no data anywhere: patient text stays on the machine.

## Knowledge-base content
`backend/rag/knowledge_base.json` and `symptom_lexicon.json` are offered under
**Creative Commons Attribution 4.0 (CC BY 4.0)** - share and adapt freely, with credit. Entries are tagged with their
clinical review status; entries marked DRAFT have **not** been reviewed by a clinician.

## Third-party software (check each licence before redistributing a bundle)
| Component | Licence (to the best of our knowledge) |
|---|---|
| FastAPI, Uvicorn, httpx, Pydantic | MIT / BSD |
| scikit-learn, NumPy | BSD-3-Clause |
| ReportLab | BSD |
| psycopg 3 | LGPL-3.0 |
| PostgreSQL, pgvector | PostgreSQL Licence |
| Ollama | MIT |
| Nomic Embed (`nomic-embed-text`) | Apache-2.0 |
| Llama 3.2 model weights | Meta **Llama 3.2 Community Licence** (requires attribution - "Built with Llama" - and acceptance of Meta's acceptable-use policy when you redistribute) |

If you distribute a bundle that includes model weights, include the licence texts that come with them.
The licences listed here are our understanding at the time of writing - confirm against the upstream projects.

## Medical notice
Decision-support only. Not a medical device. Not a substitute for a doctor. If someone may be seriously ill, seek
emergency care immediately.
