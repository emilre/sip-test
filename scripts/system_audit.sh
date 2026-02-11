#!/bin/bash
REPORT=~/asterisk-test/baseline/system_report.txt
mkdir -p ~/asterisk-test/baseline

echo "=============================================" > "$REPORT"
echo "  PHASE 1: WSL RESOURCE DISCOVERY & BASELINE" >> "$REPORT"
echo "  Date: $(date)" >> "$REPORT"
echo "=============================================" >> "$REPORT"

echo "" >> "$REPORT"
echo "--- 1. CPU INFO ---" >> "$REPORT"
echo "CPU Count: $(nproc)" >> "$REPORT"
lscpu | grep -E "Model name|CPU\(s\)|Thread|Core|MHz" >> "$REPORT" 2>&1

echo "" >> "$REPORT"
echo "--- 2. MEMORY ---" >> "$REPORT"
free -h >> "$REPORT" 2>&1
echo "" >> "$REPORT"
head -20 /proc/meminfo >> "$REPORT" 2>&1

echo "" >> "$REPORT"
echo "--- 3. DISK I/O BASELINE ---" >> "$REPORT"
dd if=/dev/zero of=/tmp/testfile bs=1M count=256 oflag=direct 2>&1 >> "$REPORT"
rm -f /tmp/testfile

echo "" >> "$REPORT"
echo "--- 4. NETWORK (LOOPBACK) ---" >> "$REPORT"
if command -v iperf3 &>/dev/null; then
    iperf3 -s -D 2>/dev/null
    sleep 1
    iperf3 -c 127.0.0.1 -t 5 >> "$REPORT" 2>&1
    pkill iperf3 2>/dev/null
else
    echo "(iperf3 not installed - skipped)" >> "$REPORT"
fi

echo "" >> "$REPORT"
echo "--- 5. WSL-SPECIFIC LIMITS ---" >> "$REPORT"
echo "Kernel:" >> "$REPORT"
cat /proc/version >> "$REPORT" 2>&1
echo "" >> "$REPORT"
echo "ulimit -a:" >> "$REPORT"
ulimit -a >> "$REPORT" 2>&1
echo "" >> "$REPORT"
echo "sysctl:" >> "$REPORT"
sysctl fs.file-max net.core.somaxconn net.ipv4.ip_local_port_range 2>/dev/null >> "$REPORT"

echo "" >> "$REPORT"
echo "--- 6. ASTERISK STATUS ---" >> "$REPORT"
asterisk -V >> "$REPORT" 2>&1
echo "" >> "$REPORT"
sudo asterisk -rx "core show channels" >> "$REPORT" 2>&1
echo "" >> "$REPORT"
sudo asterisk -rx "core show settings" >> "$REPORT" 2>&1

echo "" >> "$REPORT"
echo "=============================================" >> "$REPORT"
echo "  END OF PHASE 1 REPORT" >> "$REPORT"
echo "=============================================" >> "$REPORT"

echo "Report saved to $REPORT"
