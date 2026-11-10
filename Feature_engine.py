
import sqlite3 as sq
import time
from datetime import datetime

DB_NAME = "Fraudlens.db"
POLL_INTERVAL = 0.05


def get_connection():
    conn = sq.connect(DB_NAME, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def setup_database():
    with get_connection() as conn:
        conn.execute("PRAGMA journal_mode = WAL")

        # Create engineered transactions table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS engineered_transactions (
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
                user_transaction_count INTEGER,
                user_avg_amount REAL,
                amount_deviation REAL,
                amount_ratio REAL,
                seconds_since_last_transaction REAL,
                transactions_last_hour INTEGER,
                new_device INTEGER,
                new_ip INTEGER,
                amount_missing INTEGER,
                invalid_date INTEGER,
                invalid_ip INTEGER,
                invalid_amount INTEGER,
                invalid_method INTEGER,
                missing_ip INTEGER DEFAULT 0
            )
        """)

        # Automatically repair older database schemas
        columns = [
            column[1]
            for column in conn.execute(
                "PRAGMA table_info(engineered_transactions)"
            ).fetchall()
        ]

        if "missing_ip" not in columns:
            conn.execute("""
                ALTER TABLE engineered_transactions
                ADD COLUMN missing_ip INTEGER DEFAULT 0
            """)
            print("Added missing_ip column to existing database.")

        # Processing checkpoint table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS processing_state (
                process_name TEXT PRIMARY KEY,
                last_rowid INTEGER
            )
        """)

        conn.execute("""
            INSERT OR IGNORE INTO processing_state
            (process_name, last_rowid)
            VALUES ('feature_engineering', 0)
        """)

    print("Feature engineering database ready.")


def get_checkpoint(conn):
    result = conn.execute("""
        SELECT last_rowid
        FROM processing_state
        WHERE process_name = 'feature_engineering'
    """).fetchone()

    return result[0] if result else 0


def fetch_next_transaction(conn, last_id):
    return conn.execute("""
        SELECT
            source_rowid,
            transaction_id,
            user_id,
            transaction_amount,
            transaction_date,
            transaction_method,
            merchant_category,
            state,
            city,
            device_id,
            ip_address,
            amount_missing,
            invalid_date,
            invalid_ip,
            invalid_amount,
            invalid_method,
            missing_ip
        FROM cleaned_transactions
        WHERE source_rowid > ?
        ORDER BY source_rowid ASC
        LIMIT 1
    """, (last_id,)).fetchone()


def calculate_features(conn, row):

    source_rowid = row[0]
    transaction_id = row[1]
    user_id = row[2]
    amount = row[3]
    transaction_date = row[4]
    device_id = row[9]
    ip_address = row[10]

    # 1. Historical user transaction statistics
    previous = conn.execute("""
        SELECT
            COUNT(*),
            AVG(transaction_amount)
        FROM engineered_transactions
        WHERE user_id = ?
          AND source_rowid < ?
    """, (user_id, source_rowid)).fetchone()

    user_transaction_count = previous[0] or 0
    user_avg_amount = previous[1]

    # 2. Amount deviation and ratio
    if amount is not None and user_avg_amount is not None:

        amount_deviation = amount - user_avg_amount

        amount_ratio = (
            amount / user_avg_amount
            if user_avg_amount != 0
            else None
        )

    else:
        amount_deviation = None
        amount_ratio = None

    # 3. Time since previous user transaction
    last_transaction = conn.execute("""
        SELECT transaction_date
        FROM engineered_transactions
        WHERE user_id = ?
          AND source_rowid < ?
        ORDER BY source_rowid DESC
        LIMIT 1
    """, (user_id, source_rowid)).fetchone()

    seconds_since_last_transaction = None

    try:
        current_date = datetime.fromisoformat(transaction_date)

        if last_transaction and last_transaction[0]:
            previous_date = datetime.fromisoformat(
                last_transaction[0]
            )

            seconds_since_last_transaction = (
                current_date - previous_date
            ).total_seconds()

    except (ValueError, TypeError):
        pass

    # 4. Transactions in previous hour
    transactions_last_hour = 0

    if transaction_date:
        transactions_last_hour = conn.execute("""
            SELECT COUNT(*)
            FROM engineered_transactions
            WHERE user_id = ?
              AND source_rowid < ?
              AND datetime(transaction_date)
                  >= datetime(?, '-1 hour')
              AND datetime(transaction_date)
                  <= datetime(?)
        """, (
            user_id,
            source_rowid,
            transaction_date,
            transaction_date
        )).fetchone()[0]

    # 5. New device detection
    new_device = 0

    if device_id and device_id != "Unknown":

        device_exists = conn.execute("""
            SELECT EXISTS(
                SELECT 1
                FROM engineered_transactions
                WHERE user_id = ?
                  AND device_id = ?
                  AND source_rowid < ?
            )
        """, (
            user_id,
            device_id,
            source_rowid
        )).fetchone()[0]

        new_device = int(not device_exists)

    # 6. New IP detection
    new_ip = 0

    # row[13] = invalid_ip
    # row[16] = missing_ip
    if ip_address and not row[13] and not row[16]:

        ip_exists = conn.execute("""
            SELECT EXISTS(
                SELECT 1
                FROM engineered_transactions
                WHERE user_id = ?
                  AND ip_address = ?
                  AND invalid_ip = 0
                  AND missing_ip = 0
                  AND source_rowid < ?
            )
        """, (
            user_id,
            ip_address,
            source_rowid
        )).fetchone()[0]

        new_ip = int(not ip_exists)

    # Return all original fields and calculated features
    return (
        source_rowid,
        transaction_id,
        user_id,
        amount,
        transaction_date,
        row[5],
        row[6],
        row[7],
        row[8],
        device_id,
        ip_address,
        user_transaction_count,
        user_avg_amount,
        amount_deviation,
        amount_ratio,
        seconds_since_last_transaction,
        transactions_last_hour,
        new_device,
        new_ip,
        row[11],
        row[12],
        row[13],
        row[14],
        row[15],
        row[16]
    )


def save_features(conn, features):

    try:
        conn.execute("BEGIN")

        conn.execute("""
            INSERT OR IGNORE INTO engineered_transactions (
                source_rowid,
                transaction_id,
                user_id,
                transaction_amount,
                transaction_date,
                transaction_method,
                merchant_category,
                state,
                city,
                device_id,
                ip_address,
                user_transaction_count,
                user_avg_amount,
                amount_deviation,
                amount_ratio,
                seconds_since_last_transaction,
                transactions_last_hour,
                new_device,
                new_ip,
                amount_missing,
                invalid_date,
                invalid_ip,
                invalid_amount,
                invalid_method,
                missing_ip
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            )
        """, features)

        conn.execute("""
            UPDATE processing_state
            SET last_rowid = ?
            WHERE process_name = 'feature_engineering'
        """, (features[0],))

        conn.commit()

    except Exception:
        conn.rollback()
        raise


def main():

    setup_database()

    print("FRAUDLENS FEATURE ENGINEERING ENGINE STARTED")
    print("Processing mode: ONE TRANSACTION AT A TIME")

    conn = get_connection()

    try:
        while True:

            try:
                last_id = get_checkpoint(conn)

                row = fetch_next_transaction(conn, last_id)

                if row is None:
                    time.sleep(POLL_INTERVAL)
                    continue

                features = calculate_features(conn, row)

                save_features(conn, features)

                print("\nFEATURE ENGINEERING REPORT")
                print("Transaction ID:", features[1])
                print("Previous user transactions:", features[11])
                print("Historical average amount:", features[12])
                print("Amount deviation:", features[13])
                print("Amount ratio:", features[14])
                print("Seconds since last transaction:", features[15])
                print("Transactions in previous hour:", features[16])
                print("New device:", features[17])
                print("New IP:", features[18])
                print("Engineered row ID:", features[0])

            except Exception as error:
                conn.rollback()
                print("Feature engineering error:", error)
                time.sleep(POLL_INTERVAL)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
