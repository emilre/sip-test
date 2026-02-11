#!/bin/bash
# Run 200-call AMI load test with resource monitoring
# Usage: ./run_load_test.sh [num_calls] [cps]

NUM_CALLS=${1:-200}
CPS=${2:-10}
RESULTS_DIR=~/asterisk-test/results
SCRIPTS_DIR=/mnt/c/Users/PC/Desktop/sip-test/scripts

mkdir -p "$RESULTS_DIR"

echo "============================================="
echo "  ASTERISK LOAD TEST: $NUM_CALLS calls @ $CPS cps"
echo "  $(date)"
echo "============================================="

# 1. Pre-test baseline
echo ""
echo "[1/5] Capturing pre-test baseline..."
PRE_CHANNELS=$(asterisk -rx "core show channels count" 2>/dev/null)
PRE_CPU=$(python3 -c "import psutil; print(psutil.cpu_percent(interval=1))")
PRE_MEM=$(python3 -c "import psutil; p=[p for p in psutil.process_iter(['name']) if p.info['name']=='asterisk'][0]; print(round(p.memory_info().rss/1024/1024,2))")
echo "  Pre-test CPU: ${PRE_CPU}%"
echo "  Pre-test Asterisk RSS: ${PRE_MEM} MB"
echo "  Pre-test channels: $PRE_CHANNELS"

# Save pre-test info
cat > "$RESULTS_DIR/pre_test.txt" << EOF
PRE-TEST BASELINE
Date: $(date)
CPU idle: ${PRE_CPU}%
Asterisk RSS: ${PRE_MEM} MB
Channels: $PRE_CHANNELS
EOF

# 2. Start resource monitor in background
echo ""
echo "[2/5] Starting resource monitor..."
MONITOR_DURATION=$((NUM_CALLS / CPS + 120))  # ramp time + 120s for calls to finish
python3 "$SCRIPTS_DIR/resource_monitor.py" \
    --duration "$MONITOR_DURATION" \
    --output "$RESULTS_DIR/resource_monitor.csv" \
    --interval 1 &
MONITOR_PID=$!
echo "  Monitor PID: $MONITOR_PID (duration: ${MONITOR_DURATION}s)"
sleep 2  # let monitor collect baseline samples

# 3. Run AMI load test
echo ""
echo "[3/5] Starting AMI load test ($NUM_CALLS calls @ $CPS cps)..."
python3 "$SCRIPTS_DIR/ami_load_test.py" \
    --calls "$NUM_CALLS" \
    --cps "$CPS" \
    --output "$RESULTS_DIR/ami_load_results.csv"

# 4. Wait for monitor to finish or kill it
echo ""
echo "[4/5] Waiting for resource monitor to complete..."
sleep 10  # give some post-test cool-down samples
kill $MONITOR_PID 2>/dev/null
wait $MONITOR_PID 2>/dev/null

# 5. Generate report
echo ""
echo "[5/5] Generating report..."

POST_CPU=$(python3 -c "import psutil; print(psutil.cpu_percent(interval=1))")
POST_MEM=$(python3 -c "import psutil; p=[p for p in psutil.process_iter(['name']) if p.info['name']=='asterisk'][0]; print(round(p.memory_info().rss/1024/1024,2))")

python3 - "$RESULTS_DIR" "$PRE_CPU" "$PRE_MEM" "$POST_CPU" "$POST_MEM" "$NUM_CALLS" << 'PYREPORT'
import csv, sys, os
from datetime import datetime

results_dir = sys.argv[1]
pre_cpu = float(sys.argv[2])
pre_mem = float(sys.argv[3])
post_cpu = float(sys.argv[4])
post_mem = float(sys.argv[5])
num_calls = int(sys.argv[6])

report_path = os.path.join(results_dir, "load_test_report.txt")

# Read resource monitor CSV
res_rows = []
res_file = os.path.join(results_dir, "resource_monitor.csv")
if os.path.exists(res_file):
    with open(res_file) as f:
        res_rows = list(csv.DictReader(f))

# Read AMI results
ami_rows = []
ami_file = os.path.join(results_dir, "ami_load_results.csv")
if os.path.exists(ami_file):
    with open(ami_file) as f:
        ami_rows = list(csv.DictReader(f))

with open(report_path, 'w') as rpt:
    rpt.write("=" * 60 + "\n")
    rpt.write("  ASTERISK LOAD TEST REPORT\n")
    rpt.write(f"  Date: {datetime.now().isoformat()}\n")
    rpt.write("=" * 60 + "\n\n")

    # System baseline
    rpt.write("--- SYSTEM BASELINE ---\n")
    rpt.write(f"  Pre-test CPU (idle):     {pre_cpu}%\n")
    rpt.write(f"  Pre-test Asterisk RSS:   {pre_mem} MB\n")
    rpt.write(f"  Post-test CPU (idle):    {post_cpu}%\n")
    rpt.write(f"  Post-test Asterisk RSS:  {post_mem} MB\n")
    rpt.write(f"  Memory growth:           {round(post_mem - pre_mem, 2)} MB\n\n")

    # AMI originate results
    if ami_rows:
        succeeded = sum(1 for r in ami_rows if r['success'] == 'True')
        failed = len(ami_rows) - succeeded
        resp_times = [float(r['response_time_ms']) for r in ami_rows]
        resp_times.sort()
        p95_idx = int(len(resp_times) * 0.95)

        rpt.write("--- AMI ORIGINATE RESULTS ---\n")
        rpt.write(f"  Total calls:       {len(ami_rows)}\n")
        rpt.write(f"  Succeeded:         {succeeded}\n")
        rpt.write(f"  Failed:            {failed}\n")
        rpt.write(f"  Failure rate:      {round(failed/len(ami_rows)*100, 2)}%\n")
        rpt.write(f"  Avg response:      {round(sum(resp_times)/len(resp_times), 2)} ms\n")
        rpt.write(f"  Min response:      {round(min(resp_times), 2)} ms\n")
        rpt.write(f"  Max response:      {round(max(resp_times), 2)} ms\n")
        rpt.write(f"  P95 response:      {round(resp_times[p95_idx], 2)} ms\n\n")

    # Resource usage during test
    if res_rows:
        cpus_total = [float(r['cpu_total_pct']) for r in res_rows]
        cpus_ast = [float(r['cpu_asterisk_pct']) for r in res_rows]
        mems = [float(r['mem_rss_mb']) for r in res_rows]
        fds_list = [int(r['fds']) for r in res_rows]
        net_in = [int(r['net_in_bytes_sec']) for r in res_rows]
        net_out = [int(r['net_out_bytes_sec']) for r in res_rows]

        peak_cpu = max(cpus_total)
        peak_cpu_ast = max(cpus_ast)
        peak_mem = max(mems)
        peak_fds = max(fds_list)
        min_mem = min(mems)
        min_fds = min(fds_list)

        rpt.write("--- RESOURCE USAGE DURING TEST ---\n")
        rpt.write(f"  Samples collected: {len(res_rows)}\n\n")
        rpt.write(f"  CPU Total:   avg={round(sum(cpus_total)/len(cpus_total),1)}%  peak={peak_cpu}%\n")
        rpt.write(f"  CPU Asterisk: avg={round(sum(cpus_ast)/len(cpus_ast),1)}%  peak={peak_cpu_ast}%\n")
        rpt.write(f"  Memory RSS:  min={min_mem} MB  max={peak_mem} MB  delta={round(peak_mem-min_mem,2)} MB\n")
        rpt.write(f"  File Descs:  min={min_fds}  max={peak_fds}  delta={peak_fds-min_fds}\n")
        rpt.write(f"  Net In:      avg={round(sum(net_in)/len(net_in))} B/s  peak={max(net_in)} B/s\n")
        rpt.write(f"  Net Out:     avg={round(sum(net_out)/len(net_out))} B/s  peak={max(net_out)} B/s\n\n")

        # Per-call estimates
        rpt.write("--- PER-CALL RESOURCE ESTIMATES ---\n")
        mem_per_call = round((peak_mem - min_mem) / num_calls, 3) if num_calls > 0 else 0
        fd_per_call = round((peak_fds - min_fds) / num_calls, 1) if num_calls > 0 else 0
        cpu_per_call = round(peak_cpu_ast / num_calls, 3) if num_calls > 0 else 0
        peak_net = max(max(net_in), max(net_out))
        net_per_call = round(peak_net / num_calls) if num_calls > 0 else 0

        rpt.write(f"  Memory per call:   ~{mem_per_call} MB\n")
        rpt.write(f"  FDs per call:      ~{fd_per_call}\n")
        rpt.write(f"  CPU per call:      ~{cpu_per_call}% of total\n")
        rpt.write(f"  Net BW per call:   ~{net_per_call} B/s\n\n")

        # Capacity estimate
        avail_mem = 5000  # ~5GB free from baseline
        avail_fds = 65535
        max_by_mem = int(avail_mem / mem_per_call) if mem_per_call > 0 else 99999
        max_by_fds = int(avail_fds / fd_per_call) if fd_per_call > 0 else 99999
        bottleneck = min(max_by_mem, max_by_fds)

        rpt.write("--- CAPACITY ESTIMATE ---\n")
        rpt.write(f"  Max calls by memory (~5GB free):  {max_by_mem}\n")
        rpt.write(f"  Max calls by FDs (65535 limit):   {max_by_fds}\n")
        rpt.write(f"  Estimated bottleneck:             {bottleneck} concurrent calls\n")
        rpt.write(f"  Limiting factor:                  {'Memory' if max_by_mem < max_by_fds else 'File Descriptors'}\n")

    rpt.write("\n" + "=" * 60 + "\n")
    rpt.write("  END OF REPORT\n")
    rpt.write("=" * 60 + "\n")

print(f"Report saved to {report_path}")
PYREPORT

# Copy results to Windows
cp "$RESULTS_DIR"/* /mnt/c/Users/PC/Desktop/sip-test/results/ 2>/dev/null
mkdir -p /mnt/c/Users/PC/Desktop/sip-test/results
cp "$RESULTS_DIR"/* /mnt/c/Users/PC/Desktop/sip-test/results/

echo ""
echo "============================================="
echo "  DONE. Results in ~/asterisk-test/results/"
echo "============================================="
