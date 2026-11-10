
import sqlite3 as sq

DB_NAME = "Fraudlens.db"

def get_connection():
    conn = sq.connect(DB_NAME, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn

def table():
    try:
        with get_connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS raw_transactions(
                    transaction_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    user_name TEXT,
                    transaction_amount REAL,
                    transaction_date TEXT,
                    transaction_method TEXT,
                    merchant_category TEXT,
                    state TEXT,
                    city TEXT,
                    device_id TEXT,
                    ip_address TEXT
                )
            """)
        print("Raw transactions table ready.")
    except sq.Error as e:
        print("Database error:", e)
        raise

def bulk_upload(records):
    try:
        with get_connection() as conn:
            before = conn.total_changes
            conn.executemany("""
                INSERT OR IGNORE INTO raw_transactions(
                    transaction_id, user_id, user_name,
                    transaction_amount, transaction_date,
                    transaction_method, merchant_category,
                    state, city, device_id, ip_address
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, records)
            inserted = conn.total_changes - before
        return inserted
    except sq.Error as e:
        print("Bulk upload error:", e)
        raise

def upload(transaction_id, user_id, user_name, transaction_amount,
           transaction_date, transaction_method, merchant_category,
           state, city, device_id, ip_address):
    record = (
        transaction_id, user_id, user_name, transaction_amount,
        transaction_date, transaction_method, merchant_category,
        state, city, device_id, ip_address
    )
    return bulk_upload([record])
