
import pandas as pd
import sqlite3
import time
import Database_handling as dh

FILE_NAME = "synthetic financial data PBL.xlsx"
DB_NAME = "Fraudlens.db"
CHECK_INTERVAL = 0.01


def wait_for_cleaning(row_id, conn):
    while True:
        result = conn.execute("""
            SELECT last_rowid
            FROM processing_state
            WHERE process_name = 'data_cleaning'
        """).fetchone()

        if result and result[0] >= row_id:
            return

        time.sleep(CHECK_INTERVAL)


def main():
    print("FRAUDLENS LIVE TRANSACTION SIMULATOR STARTED")

    # Load Excel dataset
    df = pd.read_excel(FILE_NAME)

    # Convert transaction dates into datetime objects
    df["transaction_date"] = pd.to_datetime(
        df["transaction_date"],
        errors="coerce"
    )

    # Sort transactions chronologically
    df = df.sort_values(
        by="transaction_date",
        ascending=True,
        kind="stable",
        na_position="last"
    ).reset_index(drop=True)

    # Ensure raw transaction table exists
    dh.table()

    total = len(df)
    uploaded = 0
    ignored = 0

    print("Total transactions:", total)
    print("Mode: ONE TRANSACTION AT A TIME")
    print("Sorting: CHRONOLOGICAL")

    monitor = sqlite3.connect(DB_NAME, timeout=30)
    monitor.execute("PRAGMA busy_timeout = 30000")

    columns = [
        "transaction_id",
        "user_id",
        "user_name",
        "transaction_amount",
        "transaction_date",
        "transaction_method",
        "merchant_category",
        "state",
        "city",
        "device_id",
        "ip_address"
    ]

    try:
        for index, row in df[columns].iterrows():

            # Convert pandas values into SQLite-compatible values
            record = tuple(
                value.strftime("%Y-%m-%d %H:%M:%S")
                if isinstance(value, pd.Timestamp)
                else (None if pd.isna(value) else value)
                for value in row
            )

            try:
                # Upload one transaction
                inserted = dh.bulk_upload([record])

                if inserted == 0:
                    ignored += 1
                    continue

                # Retrieve SQLite row ID
                result = monitor.execute("""
                    SELECT rowid
                    FROM raw_transactions
                    WHERE transaction_id = ?
                """, (record[0],)).fetchone()

                if result is None:
                    raise RuntimeError(
                        f"Could not find uploaded transaction {record[0]}"
                    )

                row_id = result[0]
                uploaded += 1

                print(
                    f"\n[DATA ENGINE] Transaction {uploaded} uploaded"
                )

                print("[DATA ENGINE] Waiting for cleaning...")

                # Wait until Data Cleaning processes this transaction
                wait_for_cleaning(row_id, monitor)

                print(
                    f"[DATA ENGINE] Transaction {uploaded} cleaned successfully"
                )

            except Exception as error:
                print(f"Error at Excel row {index}: {error}")
                raise

    finally:
        monitor.close()

    print("\nSIMULATION COMPLETED")
    print("Total transactions:", total)
    print("Uploaded:", uploaded)
    print("Ignored:", ignored)


if __name__ == "__main__":
    main()
