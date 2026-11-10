
import sqlite3
import time
import json
import numpy as np

from pathlib import Path
from datetime import datetime, timezone

from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

DB_PATH = Path(__file__).with_name("Fraudlens.db")

POLL_INTERVAL = 2
MIN_TRAINING_RECORDS = 100
TRAINING_RATIO = 0.80

CONTAMINATION = 0.02
BATCH_SIZE = 100

PROCESS_NAME = "fraud_detection"


# --------------------------------------------------
# DATABASE
# --------------------------------------------------

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def initialise_database():

    with get_connection() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS fraud_detection_results (

                source_rowid INTEGER PRIMARY KEY,

                transaction_id TEXT,
                user_id TEXT,

                transaction_amount REAL,
                transaction_date TEXT,

                transaction_method TEXT,
                merchant_category TEXT,

                state TEXT,
                city TEXT,

                is_flagged INTEGER,

                detection_method TEXT,
                triggered_rules TEXT,

                rule_count INTEGER,

                if_flagged INTEGER,
                lof_flagged INTEGER,

                if_anomaly_score REAL,
                lof_anomaly_score REAL,

                data_quality_issues TEXT,

                detection_timestamp TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS processing_state (

                process_name TEXT PRIMARY KEY,
                last_rowid INTEGER DEFAULT 0
            )
        """)

        conn.execute("""
            INSERT OR IGNORE INTO processing_state
            (process_name, last_rowid)
            VALUES (?, 0)
        """, (PROCESS_NAME,))


def get_checkpoint():

    with get_connection() as conn:

        result = conn.execute("""
            SELECT last_rowid
            FROM processing_state
            WHERE process_name = ?
        """, (PROCESS_NAME,)).fetchone()

        return result["last_rowid"]


# --------------------------------------------------
# DATA RETRIEVAL
# --------------------------------------------------

def get_all_engineered_transactions():

    with get_connection() as conn:

        rows = conn.execute("""
            SELECT *
            FROM engineered_transactions
            ORDER BY source_rowid ASC
        """).fetchall()

        return [dict(row) for row in rows]


def get_new_transactions(last_rowid):

    with get_connection() as conn:

        rows = conn.execute("""
            SELECT *
            FROM engineered_transactions
            WHERE source_rowid > ?
            ORDER BY source_rowid ASC
            LIMIT ?
        """, (last_rowid, BATCH_SIZE)).fetchall()

        return [dict(row) for row in rows]


# --------------------------------------------------
# FEATURE PREPARATION
# --------------------------------------------------

FEATURE_COLUMNS = [

    "transaction_amount",
    "user_avg_amount",
    "amount_ratio",
    "user_transaction_count",
    "seconds_since_last_transaction",
    "transactions_last_hour",
    "new_device",
    "new_ip"
]


def prepare_features(records):

    matrix = []

    for record in records:

        amount = record.get("transaction_amount")
        average = record.get("user_avg_amount")

        try:
            amount = float(amount)
        except (TypeError, ValueError):
            amount = np.nan

        try:
            average = float(average)
        except (TypeError, ValueError):
            average = np.nan

        # Log transformation reduces the influence of
        # extremely large transaction amounts.

        log_amount = (
            np.log1p(amount)
            if np.isfinite(amount) and amount >= 0
            else np.nan
        )

        log_average = (
            np.log1p(average)
            if np.isfinite(average) and average >= 0
            else np.nan
        )

        row = [
            log_amount,
            log_average
        ]

        for column in FEATURE_COLUMNS[2:]:

            try:
                value = float(record.get(column))
            except (TypeError, ValueError):
                value = np.nan

            if not np.isfinite(value):
                value = np.nan

            row.append(value)

        matrix.append(row)

    return np.asarray(matrix, dtype=float)


# --------------------------------------------------
# MODEL TRAINING
# --------------------------------------------------

imputer = None
scaler = None

isolation_forest = None
local_outlier_factor = None

models_ready = False


def train_models():

    global imputer
    global scaler
    global isolation_forest
    global local_outlier_factor
    global models_ready

    records = get_all_engineered_transactions()

    if len(records) < MIN_TRAINING_RECORDS:

        print("Waiting for sufficient training records...")
        return False

    # Chronological split.
    # The oldest 80% becomes the training baseline.

    split_index = int(len(records) * TRAINING_RATIO)

    training_records = records[:split_index]

    if len(training_records) < MIN_TRAINING_RECORDS:
        return False

    X_train = prepare_features(training_records)

    imputer = SimpleImputer(strategy="median")
    X_train = imputer.fit_transform(X_train)

    # Remove columns that are entirely missing.
    if X_train.shape[1] == 0:
        print("No usable features available.")
        return False

    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)

    isolation_forest = IsolationForest(
        n_estimators=200,
        contamination=CONTAMINATION,
        random_state=42,
        n_jobs=-1
    )

    isolation_forest.fit(X_train)

    local_outlier_factor = LocalOutlierFactor(
        n_neighbors=min(35, len(X_train) - 1),
        contamination=CONTAMINATION,
        novelty=True,
        n_jobs=-1
    )

    local_outlier_factor.fit(X_train)

    models_ready = True

    print("\nModels trained successfully.")
    print("Training records:", len(training_records))
    print("Isolation Forest: Ready")
    print("Local Outlier Factor: Ready")

    return True


# --------------------------------------------------
# RULE ENGINE
# --------------------------------------------------

def run_rule_engine(record):

    triggered_rules = []

    def number(column, default=0):

        try:
            value = float(record.get(column))
            return value if np.isfinite(value) else default
        except (TypeError, ValueError):
            return default

    amount_ratio = number("amount_ratio")
    transactions_last_hour = number("transactions_last_hour")
    seconds_since_last = number("seconds_since_last_transaction")

    new_device = number("new_device")
    new_ip = number("new_ip")

    # Rule 1: Unusually large transaction
    if amount_ratio >= 3:

        triggered_rules.append("Unusually high transaction amount")

    # Rule 2: Rapid transaction activity
    if (
        transactions_last_hour >= 5
        and 0 <= seconds_since_last <= 300
    ):

        triggered_rules.append("Rapid transaction activity")

    # Rule 3: New device and new IP
    if new_device == 1 and new_ip == 1:

        triggered_rules.append("New device and new IP address")

    # Rule 4: New device with unusual spending
    if new_device == 1 and amount_ratio >= 2:

        triggered_rules.append("New device with unusual spending")

    return triggered_rules


# --------------------------------------------------
# DATA QUALITY
# --------------------------------------------------

def get_data_quality_issues(record):

    issues = []

    quality_columns = {
        "amount_missing": "Missing transaction amount",
        "invalid_date": "Invalid transaction date",
        "invalid_ip": "Invalid IP address",
        "invalid_amount": "Invalid transaction amount",
        "invalid_method": "Invalid transaction method",
        "missing_ip": "Missing IP address"
    }

    for column, description in quality_columns.items():

        if record.get(column) == 1:
            issues.append(description)

    return issues


# --------------------------------------------------
# ANOMALY DETECTION
# --------------------------------------------------

def detect_anomalies(records):

    X = prepare_features(records)

    X = imputer.transform(X)
    X = scaler.transform(X)

    if_predictions = isolation_forest.predict(X)
    lof_predictions = local_outlier_factor.predict(X)

    if_scores = -isolation_forest.decision_function(X)
    lof_scores = -local_outlier_factor.decision_function(X)

    results = []

    for index in range(len(records)):

        results.append({

            "if_flagged": int(if_predictions[index] == -1),

            "lof_flagged": int(lof_predictions[index] == -1),

            "if_score": float(if_scores[index]),

            "lof_score": float(lof_scores[index])

        })

    return results


# --------------------------------------------------
# SAVE RESULTS
# --------------------------------------------------

def save_results(records, anomaly_results):

    with get_connection() as conn:

        for record, anomaly in zip(records, anomaly_results):

            rules = run_rule_engine(record)

            quality_issues = get_data_quality_issues(record)

            if_flagged = anomaly["if_flagged"]
            lof_flagged = anomaly["lof_flagged"]

            is_flagged = int(
                len(rules) > 0
                or if_flagged == 1
                or lof_flagged == 1
            )

            methods = []

            if rules:
                methods.append("Rule Engine")

            if if_flagged:
                methods.append("Isolation Forest")

            if lof_flagged:
                methods.append("LOF")

            conn.execute("""
                INSERT INTO fraud_detection_results (

                    source_rowid,
                    transaction_id,
                    user_id,

                    transaction_amount,
                    transaction_date,

                    transaction_method,
                    merchant_category,

                    state,
                    city,

                    is_flagged,
                    detection_method,
                    triggered_rules,

                    rule_count,

                    if_flagged,
                    lof_flagged,

                    if_anomaly_score,
                    lof_anomaly_score,

                    data_quality_issues,
                    detection_timestamp

                )

                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?
                )

                ON CONFLICT(source_rowid) DO UPDATE SET

                    is_flagged = excluded.is_flagged,
                    detection_method = excluded.detection_method,
                    triggered_rules = excluded.triggered_rules,
                    rule_count = excluded.rule_count,
                    if_flagged = excluded.if_flagged,
                    lof_flagged = excluded.lof_flagged,
                    if_anomaly_score = excluded.if_anomaly_score,
                    lof_anomaly_score = excluded.lof_anomaly_score,
                    data_quality_issues = excluded.data_quality_issues,
                    detection_timestamp = excluded.detection_timestamp

            """, (

                record["source_rowid"],
                record["transaction_id"],
                record["user_id"],

                record["transaction_amount"],
                record["transaction_date"],

                record["transaction_method"],
                record["merchant_category"],

                record["state"],
                record["city"],

                is_flagged,
                ", ".join(methods) if methods else "No detection",
                json.dumps(rules),

                len(rules),

                if_flagged,
                lof_flagged,

                anomaly["if_score"],
                anomaly["lof_score"],

                json.dumps(quality_issues),
                datetime.now(timezone.utc).isoformat()

            ))

        if records:

            last_rowid = records[-1]["source_rowid"]

            conn.execute("""
                UPDATE processing_state
                SET last_rowid = ?
                WHERE process_name = ?
            """, (last_rowid, PROCESS_NAME))


# --------------------------------------------------
# MAIN DETECTION LOOP
# --------------------------------------------------

def main():

    initialise_database()

    print("\nFraudLens Detection Engine starting...")

    while not train_models():
        time.sleep(POLL_INTERVAL)

    while True:

        last_rowid = get_checkpoint()

        records = get_new_transactions(last_rowid)

        if not records:

            time.sleep(POLL_INTERVAL)
            continue

        try:

            anomaly_results = detect_anomalies(records)

            save_results(records, anomaly_results)

            flagged_count = sum(
                1 for result in anomaly_results
                if (
                    result["if_flagged"]
                    or result["lof_flagged"]
                )
            )

            print(
                f"Processed: {len(records)} | "
                f"ML anomalies: {flagged_count}"
            )

        except Exception as error:

            print("Detection error:", error)
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
