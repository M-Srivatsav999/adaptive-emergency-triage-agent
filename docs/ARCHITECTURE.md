# Architecture & UML

All diagrams are [Mermaid](https://mermaid.js.org) (render on GitHub / VS Code / mermaid.live; export PNG/SVG for slides).

## 0. Full-scale stack

```mermaid
flowchart LR
    P([Patient / health worker]) --> UI[Frontend SPA]
    UI -->|HTTP| API[FastAPI]
    API --> SAFE[Safety layer<br/>red-flag override]
    API --> ORCH[Orchestrator]
    subgraph Agents
      IN[Intake] --> RE[Retrieval<br/>hybrid RAG] --> TR[Triage<br/>tree + Bayesian posterior] --> RC[Recommendation]
    end
    ORCH --> IN
    RE --> OV[Symptom-overlap]
    RE --> TF[TF-IDF]
    RE --> PGV[pgvector<br/>cosine / HNSW]
    PGV --- PG[(PostgreSQL 16<br/>conditions, medical_chunks,<br/>triage_sessions, feedback)]
    API --> PG
    IN & TR & RC -.-> OL[[Ollama llama3.2]]
    PGV -.-> EM[[nomic-embed-text<br/>or offline hashing embedder]]
    API --> PDF[reportlab PDF]
```

### Database ERD (PostgreSQL + pgvector)
```mermaid
erDiagram
    conditions ||--o{ medical_chunks : "has retrievable facts"
    conditions { text id PK  text condition  text[] keywords  smallint acuity  text acuity_label  text[] red_flags  text review_status }
    medical_chunks { bigint id PK  text condition_id FK  text chunk_type  text embedder  vector768 embedding }
    triage_sessions ||--o{ clinician_feedback : "reviewed by"
    triage_sessions { text id PK  timestamptz created_at  text condition  text acuity  jsonb pipeline }
    clinician_feedback { bigint id PK  text session_id  boolean correct  text corrected_condition  text notes }
```

### Retrieval fusion
Symptom-overlap (IDF-weighted cosine; abstains with <2 symptoms) + TF-IDF + pgvector are merged with reciprocal-rank
fusion (k=20). A failing signal never breaks retrieval. The ranking becomes the **prior** for Triage's Bayesian
posterior; final probabilities = 0.3 × decision-tree `predict_proba` + 0.7 × posterior.

### Safety invariants
1. Red flags in the patient's own words force EMERGENCY (never downgrade).
2. Urgency is raised to that of any plausible, more-urgent alternative (worst-case aware).
3. Confidence gate (≥ 0.85) and ≥ 3 real questions before concluding (when informative questions exist).

---

## 1. System architecture

```mermaid
flowchart LR
    P([Patient]) --> UI[Frontend<br/>index.html<br/>chat + explainability panel]
    UI -->|HTTP / JSON| API[FastAPI backend<br/>main.py]
    API --> ORCH[Orchestrator]
    subgraph Agents
      IN[Intake Agent] --> RE[Retrieval Agent<br/>RAG]
      RE --> TR[Triage Agent<br/>scoped decision tree]
      TR --> RC[Recommendation Agent]
    end
    ORCH --> IN
    RE --> KB[(knowledge_base.json<br/>81 conditions)]
    TR --> DT[scikit-learn<br/>DecisionTreeClassifier]
    IN & TR & RC -.->|local inference| OL[[Ollama<br/>Llama 3.2]]
    API --> DB[(SQLite<br/>audit trail)]
    API --> PDF[report.py<br/>reportlab]
```

Key invariant: **Retrieval runs first and hands its shortlist to Triage.** Triage's tree is
trained only on that shortlist, so the stages can never reach contradicting conclusions.

## 2. Use case diagram

```mermaid
flowchart LR
    Patient([Patient])
    Clinician([Clinician])
    Admin([Developer / Evaluator])
    subgraph System[AI-Driven Clinical Triage System]
      UC1(Describe symptoms)
      UC2(Answer yes/no questions)
      UC3(View live elimination reasoning)
      UC4(Receive urgency + recommendation)
      UC5(Download formal PDF report)
      UC6(Review session history)
      UC7(Run accuracy evaluation)
      UC8(Extend knowledge base)
    end
    Patient --- UC1 & UC2 & UC3 & UC4 & UC5
    Clinician --- UC5 & UC6
    Admin --- UC7 & UC8
    UC1 -. include .-> UC2
    UC4 -. include .-> UC3
```

## 3. Class diagram

```mermaid
classDiagram
    class Retriever { <<interface>> +retrieve(query, top_k) list }
    class HybridRetriever { +retrieve(query, top_k) list }
    class SymptomOverlapRetriever { +retrieve(query, top_k) list }
    class TfidfRetriever {
      +kb: list
      +retrieve(query, top_k) list
      +all_conditions() list
    }
    class PgVectorRetriever {
      <<implemented>>
      +retrieve(query, top_k) list
    }
    class DecisionTreeTriage {
      +kb: list
      +symptom_index: dict
      +candidate_tree(candidate_ids) CandidateTree
      +next_question(known) tuple
      +predict(known) dict
    }
    class CandidateTree {
      +symptom_index: dict
      +next_question(known) tuple
      +current_standings(known) list
      +predict(known) dict
    }
    class IntakeAgent { +run(text) dict +run_turn(history) dict }
    class RetrievalAgent { +run(intake) dict +get_retriever() }
    class TriageAgent { +run(intake, retrieval) dict }
    class RecommendationAgent { +run(triage, intake) dict }
    class LLMClient { +call_llm(prompt, fallback_fn) str +is_ollama_live() bool }
    class Store { +save_session() +get_session() +list_sessions() +delete_session() }
    class ReportBuilder { +build_report_pdf(pipeline, patient_name) bytes }

    PgVectorRetriever ..|> Retriever : same interface
    HybridRetriever o-- PgVectorRetriever
    HybridRetriever o-- TfidfRetriever
    HybridRetriever o-- SymptomOverlapRetriever
    RetrievalAgent --> HybridRetriever
    DecisionTreeTriage --> CandidateTree : creates
    TriageAgent ..> LLMClient
    IntakeAgent ..> LLMClient
    RecommendationAgent ..> LLMClient
    IntakeAgent ..> DecisionTreeTriage : extract_known_symptoms
```

## 4. Component diagram

```mermaid
flowchart TB
    subgraph Client
      FE[Frontend SPA]
    end
    subgraph Backend[FastAPI process]
      R[Routers: /dt /triage /chat /report /history /health]
      O[Orchestrator]
      A[Agents x4]
      RAG[RAG: retriever + decision_tree]
      REP[PDF reporter]
      ST[Store]
      CFG[config.py]
    end
    subgraph External[Local services]
      OL[Ollama :11434]
      SQ[(SQLite file)]
    end
    FE --> R --> O --> A --> RAG
    R --> REP
    R --> ST --> SQ
    A --> OL
    CFG -.-> R & A & ST
```

## 5. Deployment diagram

```mermaid
flowchart LR
    subgraph Host[Single local machine / hospital workstation — no cloud]
      subgraph Docker[docker compose]
        B[backend :8001<br/>FastAPI + frontend]
        O[ollama :11434<br/>llama3.2:3b]
        V1[(triage_data volume)]
        V2[(ollama_data volume)]
      end
      Browser[Web browser]
    end
    Browser -->|http://localhost:8001| B
    B -->|OLLAMA_URL| O
    B --- V1
    O --- V2
```

## 6. Sequence diagram — yes/no triage session

```mermaid
sequenceDiagram
    actor U as Patient
    participant FE as Frontend
    participant API as FastAPI
    participant IN as Intake
    participant RE as Retrieval (RAG)
    participant TR as Triage (CandidateTree)
    participant RC as Recommendation
    participant DB as SQLite

    U->>FE: "chest pain and sweating"
    FE->>API: POST /dt/start
    API->>IN: extract_known_symptoms()
    IN-->>API: known symptoms
    API->>RE: retrieve(top 4 candidates)
    RE-->>API: shortlist
    API->>TR: candidate_tree(shortlist)
    loop until confident leaf (cap 20)
        API-->>FE: question + standings
        U->>FE: yes / no
        FE->>API: POST /dt/answer
        API->>TR: predict_proba -> elimination note
    end
    API->>RC: run(triage, intake)
    RC-->>API: recommendation + cautions
    API->>DB: save_session()
    API-->>FE: full pipeline + reasoning trace
    U->>FE: Download report
    FE->>API: POST /report/pdf
    API-->>FE: PDF
```
