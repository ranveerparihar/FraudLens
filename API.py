from fastapi import FastAPI
import sqlite3 as sq
app = FastAPI()
@app.get("/transactions")
def get_transactions():
    transactions = []
    conn = sq.connect("Fraudlens.db")
    cr = conn.cursor()
    cr.execute("SELECT transaction_id FROM raw_transactions;")
    data = cr.fetchall()
    for row in data:
        transactions.append({"transaction_id": row[0]})
    cr.close()
    conn.close()    
    return{"transactions": transactions}    