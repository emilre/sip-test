#!/usr/bin/env python3
"""
Resource monitor for Asterisk load testing.
Samples CPU, memory, file descriptors, and network every 1 second.
Writes CSV output for analysis.
"""
import psutil
import csv
import time
import argparse
import os
from datetime import datetime


def find_asterisk_process():
    for proc in psutil.process_iter(['pid', 'name']):
        if proc.info['name'] == 'asterisk':
            return proc
    return None


def get_net_bytes(iface='lo'):
    counters = psutil.net_io_counters(pernic=True)
    if iface in counters:
        return counters[iface].bytes_sent, counters[iface].bytes_recv
    # fallback to total
    total = psutil.net_io_counters()
    return total.bytes_sent, total.bytes_recv


def monitor(duration, output, interval=1.0):
    ast_proc = find_asterisk_process()
    if not ast_proc:
        print("ERROR: Asterisk process not found")
        return

    print(f"Monitoring Asterisk PID {ast_proc.pid} for {duration}s -> {output}")

    # Baseline network
    prev_sent, prev_recv = get_net_bytes()
    prev_time = time.time()

    # Prime CPU measurement
    psutil.cpu_percent(interval=None)
    try:
        ast_proc.cpu_percent(interval=None)
    except (psutil.NoSuchProcess, psutil.AccessError):
        pass

    rows = []
    start = time.time()

    while (time.time() - start) < duration:
        time.sleep(interval)
        now = time.time()
        elapsed = now - prev_time

        try:
            cpu_total = psutil.cpu_percent(interval=None)
            cpu_ast = ast_proc.cpu_percent(interval=None)
            mem_info = ast_proc.memory_info()
            mem_rss_mb = round(mem_info.rss / (1024 * 1024), 2)
            try:
                fds = ast_proc.num_fds()
            except AttributeError:
                fds = len(ast_proc.open_files())
        except (psutil.NoSuchProcess, psutil.AccessError) as e:
            print(f"Lost Asterisk process: {e}")
            break

        cur_sent, cur_recv = get_net_bytes()
        net_out = round((cur_sent - prev_sent) / elapsed) if elapsed > 0 else 0
        net_in = round((cur_recv - prev_recv) / elapsed) if elapsed > 0 else 0
        prev_sent, prev_recv = cur_sent, cur_recv
        prev_time = now

        row = {
            'timestamp': datetime.now().isoformat(),
            'elapsed_s': round(now - start, 1),
            'cpu_total_pct': cpu_total,
            'cpu_asterisk_pct': cpu_ast,
            'mem_rss_mb': mem_rss_mb,
            'fds': fds,
            'net_in_bytes_sec': int(net_in),
            'net_out_bytes_sec': int(net_out),
        }
        rows.append(row)

        # Also get channel count from Asterisk if possible
        active = row['cpu_asterisk_pct']
        print(f"  [{row['elapsed_s']:>6}s] CPU: {cpu_total:5.1f}% total, {cpu_ast:5.1f}% ast | "
              f"RAM: {mem_rss_mb:>7.1f} MB | FDs: {fds:>5} | "
              f"Net: {net_in:>8.0f} B/s in, {net_out:>8.0f} B/s out")

    # Write CSV
    if rows:
        with open(output, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        print(f"\n{len(rows)} samples written to {output}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Monitor Asterisk resource usage')
    parser.add_argument('--duration', type=int, default=120, help='Duration in seconds')
    parser.add_argument('--output', default='resource_monitor.csv', help='Output CSV path')
    parser.add_argument('--interval', type=float, default=1.0, help='Sample interval in seconds')
    args = parser.parse_args()
    monitor(args.duration, args.output, args.interval)
