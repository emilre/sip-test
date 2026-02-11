#!/usr/bin/env python3
"""
AMI-based load test for Asterisk.
Originates N concurrent calls via Local channels and tracks results.
Uses proper ActionID-based response correlation.
"""
import socket
import time
import argparse
import csv
import threading
from datetime import datetime


class AMIClient:
    def __init__(self, host='127.0.0.1', port=5038, username='loadtest', secret='loadtest123'):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(5)
        self.sock.connect((host, port))
        self._buffer = ''
        self._responses = {}  # ActionID -> response dict
        self._lock = threading.Lock()
        self._running = True
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)

        # Read banner
        banner = self._read_raw()
        print(f"AMI Banner: {banner.strip()}")

        # Login
        resp = self.send_action({
            'Action': 'Login',
            'Username': username,
            'Secret': secret,
        }, action_id='login')
        if not resp or resp.get('Response') != 'Success':
            raise Exception(f"AMI Login failed: {resp}")
        print("AMI Login: OK")

        # Start background reader after login
        self._reader_thread.start()

    def _read_raw(self):
        """Read raw data from socket."""
        chunks = []
        while True:
            try:
                data = self.sock.recv(8192).decode('utf-8', errors='replace')
                if not data:
                    break
                chunks.append(data)
                if '\r\n\r\n' in data:
                    break
            except socket.timeout:
                break
        return ''.join(chunks)

    def _parse_messages(self, data):
        """Parse AMI messages from raw data. Returns list of dicts."""
        self._buffer += data
        messages = []
        while '\r\n\r\n' in self._buffer:
            msg_text, self._buffer = self._buffer.split('\r\n\r\n', 1)
            msg = {}
            for line in msg_text.split('\r\n'):
                if ': ' in line:
                    key, val = line.split(': ', 1)
                    msg[key] = val
            if msg:
                messages.append(msg)
        return messages

    def _reader_loop(self):
        """Background thread that reads and routes all AMI messages."""
        while self._running:
            try:
                data = self.sock.recv(16384).decode('utf-8', errors='replace')
                if not data:
                    break
                messages = self._parse_messages(data)
                for msg in messages:
                    action_id = msg.get('ActionID', '')
                    if action_id:
                        with self._lock:
                            self._responses[action_id] = msg
            except socket.timeout:
                continue
            except OSError:
                break

    def send_action(self, action, action_id=None, timeout=5.0):
        """Send an AMI action and wait for its response by ActionID."""
        if action_id is None:
            action_id = f"act-{time.monotonic_ns()}"
        action['ActionID'] = action_id

        msg = '\r\n'.join(f'{k}: {v}' for k, v in action.items()) + '\r\n\r\n'
        try:
            self.sock.sendall(msg.encode())
        except OSError:
            return None

        # If reader thread isn't running yet (during login), read directly
        if not self._reader_thread.is_alive():
            data = self._read_raw()
            messages = self._parse_messages(data)
            for m in messages:
                if m.get('ActionID') == action_id:
                    return m
                with self._lock:
                    self._responses[m.get('ActionID', '')] = m
            return None

        # Wait for response from background reader
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if action_id in self._responses:
                    return self._responses.pop(action_id)
            time.sleep(0.01)
        return None

    def originate(self, call_id):
        action_id = f'load-{call_id}'
        resp = self.send_action({
            'Action': 'Originate',
            'Channel': 'Local/s@test-loopback',
            'Application': 'Playback',
            'Data': 'demo-instruct&demo-instruct&demo-instruct',
            'CallerID': f'"LoadTest" <{call_id}>',
            'Variable': f'CALL_ID={call_id}',
            'Async': 'true',
        }, action_id=action_id)
        return resp

    def get_channels(self):
        resp = self.send_action({
            'Action': 'Command',
            'Command': 'core show channels count',
        })
        return resp

    def logoff(self):
        self._running = False
        try:
            self.send_action({'Action': 'Logoff'}, timeout=2)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def run_test(num_calls, cps, output_file):
    client = AMIClient()
    results = []
    delay = 1.0 / cps
    peak_channels = 0

    print(f"\nOriginating {num_calls} calls at {cps} calls/sec...")
    print(f"Expected duration: ~{num_calls/cps:.0f}s ramp + call duration\n")

    test_start = time.time()

    for i in range(1, num_calls + 1):
        call_start = time.time()
        response = client.originate(i)
        call_elapsed = time.time() - call_start

        if response is None:
            success = False
            resp_text = 'No response (timeout)'
        else:
            success = response.get('Response') == 'Success'
            resp_text = f"{response.get('Response', '?')}: {response.get('Message', '')}"

        results.append({
            'call_id': i,
            'timestamp': datetime.now().isoformat(),
            'response_time_ms': round(call_elapsed * 1000, 2),
            'success': success,
            'response_snippet': resp_text[:100],
        })

        if i % 10 == 0:
            elapsed = time.time() - test_start
            actual_cps = i / elapsed if elapsed > 0 else 0
            succeeded_so_far = sum(1 for r in results if r['success'])
            print(f"  Originated {i}/{num_calls} calls | "
                  f"elapsed: {elapsed:.1f}s | CPS: {actual_cps:.1f} | "
                  f"OK: {succeeded_so_far} fail: {i - succeeded_so_far}")

        remaining = delay - call_elapsed
        if remaining > 0:
            time.sleep(remaining)

    ramp_time = time.time() - test_start
    print(f"\nAll {num_calls} calls originated in {ramp_time:.1f}s")
    print(f"Actual average CPS: {num_calls/ramp_time:.1f}")

    # Wait for calls to finish
    print("\nWaiting for calls to complete...")
    for attempt in range(60):
        time.sleep(2)
        try:
            resp = client.get_channels()
            if resp:
                # Response contains output in 'Output' or as combined text
                output = resp.get('Output', str(resp))
                for line in output.split('\n'):
                    if 'active channel' in line:
                        parts = line.strip().split()
                        try:
                            count = int(parts[0])
                            if count > peak_channels:
                                peak_channels = count
                            if count == 0:
                                print("  All channels cleared.")
                                break
                            print(f"  {count} active channels remaining...")
                        except (ValueError, IndexError):
                            pass
                else:
                    continue
                break
        except Exception:
            pass
    else:
        # Final check
        time.sleep(5)
        print("  Wait complete.")

    # Write results CSV
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)

    # Summary
    succeeded = sum(1 for r in results if r['success'])
    failed = num_calls - succeeded
    resp_times = [r['response_time_ms'] for r in results]
    resp_times_sorted = sorted(resp_times)
    p95_idx = int(len(resp_times_sorted) * 0.95)

    summary = {
        'total_calls': num_calls,
        'succeeded': succeeded,
        'failed': failed,
        'failure_rate_pct': round(failed / num_calls * 100, 2),
        'ramp_time_s': round(ramp_time, 1),
        'actual_cps': round(num_calls / ramp_time, 1),
        'avg_response_ms': round(sum(resp_times) / len(resp_times), 2),
        'min_response_ms': round(min(resp_times), 2),
        'max_response_ms': round(max(resp_times), 2),
        'p95_response_ms': round(resp_times_sorted[p95_idx], 2),
        'peak_channels': peak_channels,
    }

    print(f"\n{'='*50}")
    print(f"  LOAD TEST SUMMARY")
    print(f"{'='*50}")
    for k, v in summary.items():
        print(f"  {k:>20}: {v}")

    # Write summary
    summary_file = output_file.replace('.csv', '_summary.txt')
    with open(summary_file, 'w') as f:
        f.write(f"AMI LOAD TEST SUMMARY\n")
        f.write(f"Date: {datetime.now().isoformat()}\n")
        f.write(f"{'='*50}\n")
        for k, v in summary.items():
            f.write(f"{k:>20}: {v}\n")
    print(f"\nResults: {output_file}")
    print(f"Summary: {summary_file}")

    client.logoff()
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='AMI Load Test for Asterisk')
    parser.add_argument('--calls', type=int, default=200, help='Number of calls')
    parser.add_argument('--cps', type=int, default=10, help='Calls per second')
    parser.add_argument('--output', default='ami_load_results.csv', help='Output CSV')
    args = parser.parse_args()
    run_test(args.calls, args.cps, args.output)
