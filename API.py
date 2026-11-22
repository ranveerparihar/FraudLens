
from fastapi import FastAPI, Query, FileResponse 
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware
import sqlite3 as sq
import json


app = FastAPI(title="FraudLens API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_NAME = Path(__file__).with_name("Fraudlens.db")


def get_connection():
    conn = sq.connect(DB_NAME, timeout=30)
    conn.row_factory = sq.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


@app.get("/")
def home():
    return FileResponse(Path(__file__).with_name("index.html"))


@app.get("/transactions")
def get_transactions(
    limit: int = Query(default=1000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0)
):
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT *
            FROM cleaned_transactions
            ORDER BY source_rowid ASC
            LIMIT ? OFFSET ?
        """, (limit, offset)).fetchall()

        total = conn.execute("""
            SELECT COUNT(*) FROM cleaned_transactions
        """).fetchone()[0]

    return {
        "total_records": total,
        "records_fetched": len(rows),
        "limit": limit,
        "offset": offset,
        "transactions": [dict(row) for row in rows]
    }


@app.get("/transactions/new")
def get_new_transactions(
    last_id: int = Query(default=0, ge=0),
    limit: int = Query(default=5000, ge=1, le=10000)
):
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT *
            FROM cleaned_transactions
            WHERE source_rowid > ?
            ORDER BY source_rowid ASC
            LIMIT ?
        """, (last_id, limit)).fetchall()

    transactions = [dict(row) for row in rows]

    return {
        "transactions": transactions,
        "last_id": rows[-1]["source_rowid"] if rows else last_id,
        "records_fetched": len(rows)
    }


@app.get("/transactions/count")
def get_transaction_count():
    with get_connection() as conn:
        total = conn.execute("""
            SELECT COUNT(*) FROM cleaned_transactions
        """).fetchone()[0]

    return {"total_cleaned_transactions": total}


@app.get("/alerts")
def get_alerts(
    limit: int = Query(default=100, ge=1, le=1000),
    flagged_only: bool = Query(default=True)
):
    with get_connection() as conn:
        if flagged_only:
            rows = conn.execute("""
                SELECT * FROM fraud_detection_results
                WHERE is_flagged = 1
                ORDER BY source_rowid DESC
                LIMIT ?
            """, (limit,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM fraud_detection_results
                ORDER BY source_rowid DESC
                LIMIT ?
            """, (limit,)).fetchall()


@app.get("/stats")
def get_stats():
    with get_connection() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) AS total_scanned,
                COALESCE(SUM(is_flagged), 0) AS total_flagged,
                COALESCE(SUM(CASE WHEN rule_count > 0 THEN 1 ELSE 0 END), 0) AS rule_flagged,
                COALESCE(SUM(if_flagged), 0) AS if_flagged,
                COALESCE(SUM(lof_flagged), 0) AS lof_flagged
            FROM fraud_detection_results
        """).fetchone()

        total_scanned = row["total_scanned"]
        total_flagged = row["total_flagged"]
        fraud_rate = round((total_flagged / total_scanned) * 100, 2) if total_scanned > 0 else 0.0

        return{
            "total_scanned": total_scanned,
            "total_flagged": total_flagged,
            "fraud_rate_percent": fraud_rate,
            "rule_flagged": row["rule_flagged"],
            "if_flagged": row["if_flagged"],
            "lof_flagged": row["lof_flagged"]
        }

