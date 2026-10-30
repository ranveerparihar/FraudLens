#this will generate data like in real world scenario#
import pandas as pd
import time
import Database_handling as dh
df = pd.read_excel("synthetic financial data PBL.xlsx")
dh.table()
print("creating database...")
for index,rows in df.iterrows():
    print("pulling data from excel...")
    transaction_id = rows["transaction_id"]
    user_id = rows["user_id"]
    user_name = rows["user_name"]
    transaction_amount = rows["transaction_amount"]
    transaction_date = rows["transaction_date"]
    transaction_method = rows["transaction_method"]
    merchant_category = rows["merchant_category"]
    state = rows["state"]
    city = rows["city"]
    device_id = rows["device_id"]
    ip_address = rows["ip_address"]
    print(f"Uploading row {index} to database")
    dh.upload(transaction_id,user_id,user_name,transaction_amount,transaction_date,transaction_method,merchant_category,state,city,device_id,ip_address)
    