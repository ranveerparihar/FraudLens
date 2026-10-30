import sqlite3 as sq 
conn = sq.connect("Fraudlens.db")
cr = conn.cursor()
def table():
 try:
  cr.execute("""
  CREATE TABLE IF NOT EXISTS raw_transactions(
  transaction_id TEXT PRIMARY KEY,
  user_id TEXT ,
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
  conn.commit()
 except sq.Error as e:
  print("Database error, e") 
def upload(transaction_id,user_id,user_name,transaction_amount,transaction_date,transaction_method,merchant_category,state,city,device_id,ip_address):
 cr.execute("""
 INSERT OR IGNORE INTO raw_transactions(transaction_id,user_id,user_name,transaction_amount,transaction_date,transaction_method,merchant_category,state,city,device_id,ip_address)
 VALUES (?,?,?,?,?,?,?,?,?,?,?)
""",(transaction_id,user_id,user_name,transaction_amount,transaction_date,transaction_method,merchant_category,state,city,device_id,ip_address))
 print("uploaded  values!")
 conn.commit()
