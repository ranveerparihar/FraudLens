
import sqlite3 as sq
import pandas as pd
import ipaddress
import math
import time
from collections import Counter

DB_NAME = "Fraudlens.db"
BATCH_SIZE = 1
POLL_INTERVAL = 0.05
VALID_METHODS = {"UPI", "CARD", "BANK TRANSFER", "ATM", "ONLINE"}

def get_connection():
    conn = sq.connect(DB_NAME, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn

def setup_database():
    with get_connection() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cleaned_transactions (
                source_rowid INTEGER PRIMARY KEY,
                transaction_id TEXT UNIQUE,
                user_id TEXT,
                transaction_amount REAL,
                transaction_date TEXT,
                transaction_method TEXT,
                merchant_category TEXT,
                state TEXT,
                city TEXT,
                device_id TEXT,
                ip_address TEXT,
                amount_missing INTEGER DEFAULT 0,
                invalid_date INTEGER DEFAULT 0,
                invalid_ip INTEGER DEFAULT 0,
                invalid_amount INTEGER DEFAULT 0,
                invalid_method INTEGER DEFAULT 0,
                missing_ip INTEGER DEFAULT 0
            )
        """)
        existing_columns = {
            row[1] for row in conn.execute(
                "PRAGMA table_info(cleaned_transactions)"
            )
        }
        new_columns = {
            "invalid_amount": "INTEGER DEFAULT 0",
            "invalid_method": "INTEGER DEFAULT 0",
            "missing_ip": "INTEGER DEFAULT 0"
        }
        for column, data_type in new_columns.items():
            if column not in existing_columns:
                conn.execute(
                    f"ALTER TABLE cleaned_transactions ADD COLUMN {column} {data_type}"
                )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS processing_state (
                process_name TEXT PRIMARY KEY,
                last_rowid INTEGER
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO processing_state
            (process_name, last_rowid)
            VALUES ('data_cleaning', 0)
        """)
    print("Cleaning database ready.")

def get_last_id(conn):
    result = conn.execute("""
        SELECT last_rowid
        FROM processing_state
        WHERE process_name = 'data_cleaning'
    """).fetchone()
    return result[0] if result else 0

def fetch_new_data(conn, last_id):
    cursor = conn.execute("""
        SELECT
            rowid, transaction_id, user_id,
            transaction_amount, transaction_date,
            transaction_method, merchant_category,
            state, city, device_id, ip_address
        FROM raw_transactions
        WHERE rowid > ?
        ORDER BY rowid ASC
        LIMIT ?
    """, (last_id, BATCH_SIZE))
    records = cursor.fetchall()
    columns = [description[0] for description in cursor.description]
    return pd.DataFrame(records, columns=columns)

def is_missing(value):
    return pd.isna(value) or (
        isinstance(value, str) and value.strip() == ""
    )

def validate_ip(value):
    if is_missing(value):
        return 0, 1
    try:
        ipaddress.ip_address(str(value).strip())
        return 0, 0
    except ValueError:
        return 1, 0

def clean_batch(df):
    if df.empty:
        return [], {}

    total = len(df)
    amount_missing = df["transaction_amount"].apply(is_missing)
    amounts = pd.to_numeric(
        df["transaction_amount"], errors="coerce"
    )
    non_finite = amounts.apply(
        lambda x: pd.notna(x) and not math.isfinite(x)
    )
    invalid_amount = (~amount_missing) & (
        amounts.isna() | non_finite
    )
    amounts = amounts.mask(invalid_amount | amount_missing)

    negative_amounts = int((amounts < 0).sum())
    zero_amounts = int((amounts == 0).sum())

    dates = pd.to_datetime(
        df["transaction_date"],
        format="%Y-%m-%d %H:%M:%S",
        errors="coerce"
    )
    invalid_dates = dates.isna()
    dates = dates.dt.strftime("%Y-%m-%d %H:%M:%S")

    methods = (
        df["transaction_method"]
        .astype("string")
        .str.strip()
        .str.upper()
    )
    invalid_methods = ~methods.isin(VALID_METHODS)

    categories = (
        df["merchant_category"]
        .astype("string")
        .str.strip()
        .str.title()
    )
    states = (
        df["state"]
        .astype("string")
        .str.strip()
        .str.title()
    )
    cities = (
        df["city"]
        .astype("string")
        .str.strip()
        .str.title()
    )
    cities = cities.fillna("Unknown").replace("", "Unknown")

    devices = df["device_id"].astype("string").str.strip()
    devices = devices.fillna("Unknown").replace("", "Unknown")

    ip_results = df["ip_address"].apply(validate_ip)
    invalid_ips = ip_results.apply(lambda x: x[0])
    missing_ips = ip_results.apply(lambda x: x[1])

    transaction_ids = df["transaction_id"].tolist()
    id_counts = Counter(transaction_ids)
    duplicate_ids = sum(
        1 for count in id_counts.values() if count > 1
    )

    def db_value(value):
        if pd.isna(value):
            return None
        if hasattr(value, "item"):
            value = value.item()
        return value

    cleaned_records = []
    for i, row in df.iterrows():
        cleaned_records.append((
            int(row["rowid"]),
            db_value(row["transaction_id"]),
            db_value(row["user_id"]),
            db_value(amounts.loc[i]),
            db_value(dates.loc[i]),
            db_value(methods.loc[i]),
            db_value(categories.loc[i]),
            db_value(states.loc[i]),
            db_value(cities.loc[i]),
            db_value(devices.loc[i]),
            db_value(row["ip_address"]),
            int(amount_missing.loc[i]),
            int(invalid_dates.loc[i]),
            int(invalid_ips.loc[i]),
            int(invalid_amount.loc[i]),
            int(invalid_methods.loc[i]),
            int(missing_ips.loc[i])
        ))

    report = {
        "received": total,
        "missing_amounts": int(amount_missing.sum()),
        "invalid_amounts": int(invalid_amount.sum()),
        "negative_amounts": negative_amounts,
        "zero_amounts": zero_amounts,
        "invalid_dates": int(invalid_dates.sum()),
        "invalid_ips": int(invalid_ips.sum()),
        "missing_ips": int(missing_ips.sum()),
        "invalid_methods": int(invalid_methods.sum()),
        "duplicate_ids": duplicate_ids
    }

    return cleaned_records, report

def save_cleaned_data(conn, cleaned_records):
    if not cleaned_records:
        return 0, 0, 0

    previous_changes = conn.total_changes
    conn.executemany("""
        INSERT OR IGNORE INTO cleaned_transactions (
            source_rowid, transaction_id, user_id,
            transaction_amount, transaction_date,
            transaction_method, merchant_category,
            state, city, device_id, ip_address,
            amount_missing, invalid_date, invalid_ip,
            invalid_amount, invalid_method, missing_ip
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, cleaned_records)

    inserted = conn.total_changes - previous_changes
    ignored = len(cleaned_records) - inserted
    last_id = max(row[0] for row in cleaned_records)

    conn.execute("""
        UPDATE processing_state
        SET last_rowid = ?
        WHERE process_name = 'data_cleaning'
    """, (last_id,))

    return inserted, ignored, last_id

def main():
    setup_database()
    print("FRAUDLENS FAST DATA CLEANING ENGINE STARTED")
    print("Batch size:", BATCH_SIZE)

    conn = get_connection()

    try:
        while True:
            try:
                last_id = get_last_id(conn)
                df = fetch_new_data(conn, last_id)

                if df.empty:
                    time.sleep(POLL_INTERVAL)
                    continue

                cleaned_records, report = clean_batch(df)

                conn.execute("BEGIN")
                inserted, ignored, new_last_id = save_cleaned_data(
                    conn, cleaned_records
                )
                conn.commit()

                print("\nBATCH VALIDATION REPORT")
                print("Transactions received:", report["received"])
                print("Missing amounts:", report["missing_amounts"])
                print("Non-numeric amounts:", report["invalid_amounts"])
                print("Negative amounts:", report["negative_amounts"])
                print("Zero amounts:", report["zero_amounts"])
                print("Invalid dates:", report["invalid_dates"])
                print("Invalid IPs:", report["invalid_ips"])
                print("Missing IPs:", report["missing_ips"])
                print("Invalid transaction methods:", report["invalid_methods"])
                print("Duplicate transaction IDs in batch:", report["duplicate_ids"])
                print("New cleaned records inserted:", inserted)
                print("Records ignored:", ignored)
                print("Last processed row ID:", new_last_id)

            except Exception as error:
                conn.rollback()
                print("Processing error:", error)
                time.sleep(POLL_INTERVAL)

    finally:
        conn.close()

if __name__ == "__main__":
    main()
