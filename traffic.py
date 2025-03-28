#!/usr/bin/env python3
import subprocess
import sqlite3
import time
import datetime

ports_to_monitor = {
    12450: "user1",
    23333: "user2"
}

def format_bytes(num_bytes):
    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    for unit in units:
        if num_bytes < 1024:
            return f"{num_bytes:.5f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.5f} PB"

def get_nft_counter(chain, protocol, port):
    try:
        result = subprocess.run(["nft", "list", "chain", "inet", "filter", chain],
                                capture_output=True, text=True, check=True)
    except Exception as e:
        print(f"nft命令错误: {e}")
        return 0
    counter = 0
    if chain.lower() == "input":
        search_str = f"{protocol} dport {port}"
    elif chain.lower() == "output":
        search_str = f"{protocol} sport {port}"
    else:
        search_str = f"{protocol} "
    for line in result.stdout.splitlines():
        if search_str in line:
            tokens = line.split()
            try:
                idx = tokens.index("bytes")
                value = int(tokens[idx + 1])
                counter += value
            except (ValueError, IndexError):
                continue
    return counter

conn = sqlite3.connect("traffic_history.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS traffic_daily (
    port INTEGER,
    rule TEXT,
    report_date TEXT,
    base INTEGER,
    accumulated INTEGER,
    last_raw INTEGER,
    last_update TEXT,
    PRIMARY KEY (port, rule, report_date)
)
""")
conn.commit()

cursor.execute("""
CREATE TABLE IF NOT EXISTS traffic_monthly (
    port INTEGER,
    rule TEXT,
    report_month TEXT,
    total INTEGER,
    last_update TEXT,
    PRIMARY KEY (port, rule, report_month)
)
""")
conn.commit()

def get_daily_record(report_date, port, rule):
    cursor.execute("SELECT base, accumulated, last_raw, last_update FROM traffic_daily WHERE report_date = ? AND port = ? AND rule = ?",
                   (report_date, port, rule))
    return cursor.fetchone()

def insert_daily_record(report_date, port, rule, base, accumulated, last_raw, last_update):
    cursor.execute("INSERT INTO traffic_daily (port, rule, report_date, base, accumulated, last_raw, last_update) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (port, rule, report_date, base, accumulated, last_raw, last_update))
    conn.commit()

def update_daily_record(report_date, port, rule, accumulated, last_raw, last_update):
    cursor.execute("UPDATE traffic_daily SET accumulated = ?, last_raw = ?, last_update = ? WHERE report_date = ? AND port = ? AND rule = ?",
                   (accumulated, last_raw, last_update, report_date, port, rule))
    conn.commit()

def insert_or_update_monthly(report_month, port, rule, total, last_update):
    cursor.execute("""
        INSERT INTO traffic_monthly (port, rule, report_month, total, last_update)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(port, rule, report_month) DO UPDATE SET total = ?, last_update = ?
    """, (port, rule, report_month, total, last_update, total, last_update))
    conn.commit()

def aggregate_monthly(report_month):
    cursor.execute("""
        SELECT port, rule, SUM(accumulated - base) as total
        FROM traffic_daily
        WHERE report_date LIKE ?
        GROUP BY port, rule
    """, (report_month + '-%',))
    rows = cursor.fetchall()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for row in rows:
        port, rule, total = row
        insert_or_update_monthly(report_month, port, rule, total, now)

def main_loop():
    current_date = datetime.date.today().strftime("%Y-%m-%d")
    current_month = datetime.date.today().strftime("%Y-%m")
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    for port in ports_to_monitor:
        for chain, protocol in [("input", "tcp"), ("input", "udp"),
                                  ("output", "tcp"), ("output", "udp")]:
            rule = f"{chain}_{protocol}"
            record = get_daily_record(current_date, port, rule)
            if record is None:
                raw = get_nft_counter(chain, protocol, port)
                insert_daily_record(current_date, port, rule, raw, raw, raw, now_str)
                print(f"[{now_str}] 插入新daily记录: {current_date} port {port} {rule} 初始值 {raw} ({format_bytes(raw)})")
            else:
                print(f"[{now_str}] daily记录已存在: {current_date} port {port} {rule}")
    
    while True:
        now = datetime.datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        today = now.strftime("%Y-%m-%d")
        month_str = now.strftime("%Y-%m")
        
        if today != current_date:
            print(f"[{now_str}] 日期变更: {today}")
            current_date = today
            for port in ports_to_monitor:
                for chain, protocol in [("input", "tcp"), ("input", "udp"),
                                          ("output", "tcp"), ("output", "udp")]:
                    rule = f"{chain}_{protocol}"
                    raw = get_nft_counter(chain, protocol, port)
                    insert_daily_record(current_date, port, rule, raw, raw, raw, now_str)
                    print(f"[{now_str}] 插入新daily记录: {current_date} port {port} {rule} 初始值 {raw} ({format_bytes(raw)})")
        
        if month_str != current_month:
            print(f"[{now_str}] 月份变更: 聚合上月数据 {current_month}")
            aggregate_monthly(current_month)
            current_month = month_str
        
        for port in ports_to_monitor:
            for chain, protocol in [("input", "tcp"), ("input", "udp"),
                                      ("output", "tcp"), ("output", "udp")]:
                rule = f"{chain}_{protocol}"
                record = get_daily_record(current_date, port, rule)
                if record is None:
                    continue
                base, accumulated, last_raw, _ = record
                new_raw = get_nft_counter(chain, protocol, port)
                if new_raw < last_raw:
                    delta = new_raw
                    print(f"[{now_str}] {port} {rule} 计数器重置，增量 = {new_raw} ({format_bytes(new_raw)})")
                else:
                    delta = new_raw - last_raw
                new_accumulated = accumulated + delta
                update_daily_record(current_date, port, rule, new_accumulated, new_raw, now_str)
                daily_value = new_accumulated - base
                print(f"[{now_str}] 更新daily: {current_date} port {port} {rule}: 累计 = {new_accumulated} ({format_bytes(new_accumulated)}), 日增量 = {daily_value} ({format_bytes(daily_value)})")
        
        time.sleep(60)

if __name__ == "__main__":
    main_loop()
