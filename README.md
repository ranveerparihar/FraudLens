# FraudLens: Real-Time Hybrid Financial Fraud Detection System

**FraudLens** is an end-to-end streaming fraud detection platform that simulates continuous financial transaction ingestion, performs automated data validation and rolling behavioral feature engineering, and identifies suspicious activity using a **Three-Layer Hybrid Detection Engine** (Deterministic Rule Engine, Isolation Forest, and Local Outlier Factor). Detection results are persisted in a concurrent SQLite Write-Ahead Logging (WAL) database and streamed to a real-time monitoring dashboard via FastAPI.

---

## System Architecture

```text
[synthetic financial data PBL.xlsx (95,535 records)]
                       │
                       ▼  (Sequential Stream Simulation)
        1. Data_engine.py      ──► raw_transactions
                       │
                       ▼  (Schema Validation & Quality Auditing)
      2. Data_cleaning.py      ──► cleaned_transactions
                       │
                       ▼  (Rolling User & Velocity Aggregations)
     3. Feature_engine.py      ──► engineered_transactions
                       │
                       ▼  (Isolation Forest + LOF + Rule Engine)
    4. Fraud_detection.py      ──► fraud_detection_results
                       │
                       ▼  (REST JSON Endpoints: /stats, /alerts)
          5. API.py (FastAPI + Uvicorn)
                       │
                       ▼  (Asynchronous 3s Live Polling)
         6. index.html (Web Dashboard)
```

---

## Core Capabilities

- **Checkpointed Streaming Pipeline:** Decoupled producer-consumer workers synchronized via stateful row checkpoints (`processing_state`) and SQLite Write-Ahead Logging (`PRAGMA journal_mode=WAL`) for concurrent, lock-free reads and writes.
- **Automated Data Hygiene (`Data_cleaning.py`):** Audits malformed records (`amount_missing`, `invalid_date`, `invalid_ip`, `invalid_amount`, `invalid_method`, `missing_ip`) and preserves quality telemetry without silently discarding forensic anomalies.
- **Behavioral Feature Engineering (`Feature_engine.py`):** Computes per-user historical spending baselines (`user_avg_amount`, `amount_ratio`, `user_transaction_count`) alongside temporal velocity indicators (`seconds_since_last_transaction`, `transactions_last_hour`).
- **Three-Layer Hybrid Detection Engine (`Fraud_detection.py`):**
  1. **Isolation Forest (`n_estimators=200`, `contamination=0.02`):** Isolates global multivariate outliers across log-transformed and standardized features.
  2. **Local Outlier Factor (`n_neighbors=35`, `contamination=0.02`, `novelty=True`):** Evaluates local neighborhood reachability density deviations to capture contextual anomalies.
  3. **Deterministic Rule Engine:** Evaluates explicit domain heuristics (`amount_ratio >= 3`, high-frequency bursts `>= 5 transactions/hour` within `300s`, `new_device` and `new_ip` combinations) to attach human-readable audit explanations.
- **REST API & Real-Time Dashboard (`API.py` & `index.html`):** Exposes aggregated KPI metrics and recent flagged alerts over HTTP, rendered on a responsive dashboard polling every 3 seconds.

---

## Repository Structure

| File | Role |
| :--- | :--- |
| `Data_engine.py` | Ingests `synthetic financial data PBL.xlsx` chronologically into SQLite to simulate a live transaction stream. |
| `Data_cleaning.py` | Validates raw records, standardizes types, and populates `cleaned_transactions` with binary data quality flags. |
| `Feature_engine.py` | Computes customer spending ratios and rolling velocity features into `engineered_transactions`. |
| `Fraud_detection.py` | Fits `SimpleImputer`, `StandardScaler`, Isolation Forest, and LOF on an 80% chronological baseline, scores incoming batches, runs domain rules, and persists alerts. |
| `Database_handling.py` | Database schema initialization and connection management utilities. |
| `API.py` | FastAPI application serving `index.html` and REST endpoints (`/stats`, `/alerts`, `/transactions`, `/transactions/new`). |
| `index.html` | Real-time frontend dashboard built with HTML5, Tailwind CSS, and Vanilla JavaScript. |
| `requirements.txt` | Python package dependencies. |

---

## Setup and Execution

### 1. Environment Setup
```bash
git clone https://github.com
cd FraudLens
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
pip install pandas openpyxl     # Required for Excel dataset ingestion
```

### 2. Start the API Server and Dashboard (Terminal 1)
```bash
source venv/bin/activate
uvicorn API:app --host 0.0.0.0 --port 8000 --reload
```
Navigate to `http://localhost:8000/` in your browser to access the FraudLens dashboard.

### 3. Start the Streaming Detection Pipeline (Terminal 2)
```bash
source venv/bin/activate
python Data_engine.py &
python Data_cleaning.py &
python Feature_engine.py &
python Fraud_detection.py
```
Once `100` engineered records are ingested, `Fraud_detection.py` trains the anomaly detection models on the initial 80% chronological baseline and begins writing flagged alerts to `Fraudlens.db`.

---

## API Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | Serves the real-time monitoring dashboard (`index.html`). |
| `GET` | `/stats` | Returns total scanned transactions, flagged alert count, fraud rate percentage, and per-engine detection counts. |
| `GET` | `/alerts?limit=25&flagged_only=true` | Returns recent flagged transactions with deserialized `triggered_rules` and anomaly scores. |
| `GET` | `/transactions` | Returns paginated records from `cleaned_transactions`. |
| `GET` | `/transactions/new?last_id=0` | Incremental polling endpoint for newly cleaned transactions. |

---

## Technology Stack

- **Backend & Machine Learning:** Python 3, FastAPI, Uvicorn, Scikit-Learn, NumPy, Pandas
- **Database:** SQLite3 (Write-Ahead Logging Mode)
- **Frontend:** HTML5, Tailwind CSS, JavaScript (ES6+)
