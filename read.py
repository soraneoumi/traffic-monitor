#!/usr/bin/env python3
import sqlite3
import os
import time
from datetime import datetime, date
import calendar

DB_PATH = "./traffic_history.db"

def format_bytes(num_bytes):
    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    for unit in units:
        if num_bytes < 1024:
            return f"{num_bytes:.5f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.5f} PB"

def add_one_month(d):
    y, m = d.year, d.month
    if m == 12:
        y += 1
        m = 1
    else:
        m += 1
    d_day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, d_day)

conn = None
try:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
except Exception as e:
    print("无法连接数据库：", e)
    exit(1)

start_str = input("请输入开始日期 (YYYY-MM-DD): ").strip()
port_str = input("请输入端口号: ").strip()
try:
    start = date.fromisoformat(start_str)
    port = int(port_str)
except:
    print("输入格式错误")
    exit(1)

end = add_one_month(start)
query = (
    "SELECT SUM(accumulated - base) FROM traffic_daily "
    "WHERE port = ? AND report_date >= ? AND report_date < ?"
)
cursor.execute(query, (port, start_str, end.isoformat()))
row = cursor.fetchone()
total = row[0] if row and row[0] is not None else 0
conn.close()

print(f"从 {start_str} 到 {end.isoformat()}，端口 {port} 的总流量：{format_bytes(total)}， 字节数：{total}")
