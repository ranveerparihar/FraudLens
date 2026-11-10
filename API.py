
from fastapi import FastAPI, Query
import sqlite3 as sq

app = FastAPI(title="FraudLens API")

DB_NAME = "Fraudlens.db"

def get_connection():
    conn = sq.connect(DB_NAME, timeout=30)
    conn.row_factory = sq.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn

@app.get("/")
def home():
    return {"message": "FraudLens API is running"}

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
