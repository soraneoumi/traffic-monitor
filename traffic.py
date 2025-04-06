#!/usr/bin/env python3
import subprocess
import sqlite3
import time
import datetime
import json
import traceback

ports_to_monitor = {
    12450: "user1",
    23333: "user2"
}

def format_bytes(num_bytes):
    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    for unit in units:
        if num_bytes < 1024:
            if unit == 'B' or unit == 'KB' or unit == 'MB':
                 return f"{num_bytes:.2f} {unit}"
            else:
                 return f"{num_bytes:.5f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.5f} PB"

def get_nft_counter(chain, protocol, port):
    try:
        command = ["nft", "list", "chain", "inet", "filter", chain]
        result = subprocess.run(command,
                                capture_output=True, text=True, check=True, timeout=10)
    except subprocess.CalledProcessError as e:
        print(f"nft命令错误 (CalledProcessError): {e}. Command: {' '.join(command)}. Stderr: {e.stderr.strip()}")
        return None
    except FileNotFoundError:
        print(f"nft命令错误: 'nft' command not found.")
        return None
    except subprocess.TimeoutExpired:
        print(f"nft命令错误: Command {' '.join(command)} timed out after 10 seconds.")
        return None
    except Exception as e:
        print(f"nft命令执行时发生未知错误: {e}. Command: {' '.join(command)}")
        return None

    counter = 0
    if chain.lower() == "input":
        search_str = f"{protocol} dport {port}"
    elif chain.lower() == "output":
        search_str = f"{protocol} sport {port}"
    else:
        search_str = f"{protocol} "

    lines = result.stdout.splitlines()
    found_match = False
    parsed_successfully = False

    for line in lines:
        if search_str in line:
            found_match = True
            tokens = line.split()
            try:
                idx = tokens.index("bytes")
                value = int(tokens[idx + 1])
                counter += value
                parsed_successfully = True
            except (ValueError, IndexError):
                print(f"警告: 在行 '{line}' 中找到 '{search_str}' 但解析 'bytes' 失败。")
                continue
            except Exception as e:
                 print(f"警告: 解析行 '{line}' 时发生未知错误: {e}")
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
        total = total if total is not None else 0
        insert_or_update_monthly(report_month, port, rule, total, now)

def main_loop():
    current_date = datetime.date.today().strftime("%Y-%m-%d")
    current_month = datetime.date.today().strftime("%Y-%m")
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(f"[{now_str}] 脚本启动，初始化检查日期: {current_date}")
    for port in ports_to_monitor:
        for chain, protocol in [("input", "tcp"), ("input", "udp"),
                                  ("output", "tcp"), ("output", "udp")]:
            rule = f"{chain}_{protocol}"
            record = get_daily_record(current_date, port, rule)
            if record is None:
                print(f"[{now_str}] {current_date} port {port} {rule} 无记录，尝试获取初始值...")
                raw = get_nft_counter(chain, protocol, port)

                if raw is None:
                    print(f"[{now_str}] 错误：无法获取 {port} {rule} 的初始 nft 计数器。将跳过创建今日记录，稍后重试。")
                else:
                    insert_daily_record(current_date, port, rule, raw, raw, raw, now_str)
                    print(f"[{now_str}] 插入新daily记录: {current_date} port {port} {rule} 初始值 {raw} ({format_bytes(raw)})")
            else:
                pass

    print(f"[{now_str}] 初始化检查完成，进入主循环...")
    while True:
        now = datetime.datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        today = now.strftime("%Y-%m-%d")
        month_str = now.strftime("%Y-%m")

        if today != current_date:
            print(f"[{now_str}] 日期变更: 从 {current_date} 到 {today}")
            prev_month_to_aggregate = current_month
            current_date = today
            current_month = month_str

            if current_month != prev_month_to_aggregate:
                 print(f"[{now_str}] 月份变更: 聚合上月数据 {prev_month_to_aggregate}")
                 try:
                     aggregate_monthly(prev_month_to_aggregate)
                     print(f"[{now_str}] 月度数据聚合完成: {prev_month_to_aggregate}")
                 except Exception as e:
                     print(f"[{now_str}] 错误: 聚合月度数据 {prev_month_to_aggregate} 时出错: {e}")

            print(f"[{now_str}] 为新日期 {current_date} 创建记录...")
            for port in ports_to_monitor:
                for chain, protocol in [("input", "tcp"), ("input", "udp"),
                                          ("output", "tcp"), ("output", "udp")]:
                    rule = f"{chain}_{protocol}"
                    if get_daily_record(current_date, port, rule) is None:
                        raw = get_nft_counter(chain, protocol, port)
                        if raw is None:
                            print(f"[{now_str}] 错误：日期变更后无法获取 {port} {rule} 的初始 nft 计数器。将跳过创建今日记录，稍后重试。")
                        else:
                            insert_daily_record(current_date, port, rule, raw, raw, raw, now_str)
                            print(f"[{now_str}] 插入新daily记录: {current_date} port {port} {rule} 初始值 {raw} ({format_bytes(raw)})")

        for port in ports_to_monitor:
            for chain, protocol in [("input", "tcp"), ("input", "udp"),
                                      ("output", "tcp"), ("output", "udp")]:
                rule = f"{chain}_{protocol}"
                record = get_daily_record(current_date, port, rule)

                if record is None:
                    raw = get_nft_counter(chain, protocol, port)
                    if raw is None:
                         continue
                    else:
                        insert_daily_record(current_date, port, rule, raw, raw, raw, now_str)
                        print(f"[{now_str}] 补插入daily记录: {current_date} port {port} {rule} 初始值 {raw} ({format_bytes(raw)})")
                        record = get_daily_record(current_date, port, rule)
                        if record is None:
                            print(f"[{now_str}] 致命错误: 插入记录后无法立即读取 {current_date} {port} {rule}！")
                            continue

                base, accumulated, last_raw, _ = record
                new_raw = get_nft_counter(chain, protocol, port)

                if new_raw is None:
                    print(f"[{now_str}] 错误：无法获取 {port} {rule} 的当前 nft 计数器。跳过本次更新。")
                    continue

                delta = 0
                if new_raw < last_raw:
                    delta = new_raw
                    print(f"[{now_str}] {port} {rule} 计数器重置或回滚: last_raw={last_raw}, new_raw={new_raw}。增量计为 {delta} ({format_bytes(delta)})")
                else:
                    delta = new_raw - last_raw

                if delta < 0:
                     print(f"警告: 计算出的 delta 为负 ({delta}) for {port} {rule}. new_raw={new_raw}, last_raw={last_raw}. 重置 delta 为 0。")
                     delta = 0

                if delta > 0:
                    new_accumulated = accumulated + delta
                    update_daily_record(current_date, port, rule, new_accumulated, new_raw, now_str)
                    daily_value = new_accumulated - base
                    print(f"[{now_str}] 更新daily: {current_date} port {port} {rule}: Raw={new_raw}(+{delta}), Acc={new_accumulated} ({format_bytes(new_accumulated)}), Day={daily_value} ({format_bytes(daily_value)})")
                elif new_raw == last_raw:
                    pass
                else:
                    new_accumulated = accumulated
                    update_daily_record(current_date, port, rule, new_accumulated, new_raw, now_str)
                    daily_value = new_accumulated - base
                    print(f"[{now_str}] 更新daily (重置为0): {current_date} port {port} {rule}: Raw={new_raw}(+{delta}), Acc={new_accumulated} ({format_bytes(new_accumulated)}), Day={daily_value} ({format_bytes(daily_value)})")

        time.sleep(60)

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，正在关闭数据库连接...")
    except Exception as e:
        print(f"\n主循环发生未捕获异常: {e}")
        traceback.print_exc()
    finally:
        if conn:
            conn.close()
            print("数据库连接已关闭。")
