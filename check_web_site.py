#!/usr/bin/env python3
import sys
import socket
import subprocess
import json
from threading import Thread

# Import your external interface configurations dynamically
try:
    import isp_config
except ImportError:
    print(json.dumps({"error": "Configuration file 'isp_config.py' missing in externalscripts directory."}))
    sys.exit(1)

if len(sys.argv) < 2:
    print(json.dumps({"error": "Missing URL/IP argument"}))
    sys.exit(1)

# Cleanly isolate the target address or domain
url = sys.argv[1].replace("https://", "").replace("http://", "").split('/')[0]

# Phase 1: Gather and strictly deduplicate target IPs
unique_ips = set()
try:
    addr_info = socket.getaddrinfo(url, 80, proto=socket.IPPROTO_TCP)
    for item in addr_info:
        ip = item[4][0]
        if ":" not in ip:  # IPv4 strictly enforced
            unique_ips.add(ip)
except Exception as e:
    print(json.dumps({"error": f"DNS resolution failed: {str(e)}"}))
    sys.exit(1)

target_list = sorted(list(unique_ips))
results_map = {}

def run_diagnostics(ip):
    # Fast Ping Triage using variables pulled from your config file
    p1 = subprocess.run(f"ping -c 1 -w 1 -I {isp_config.ISP1_SOURCE_IP} {ip}", shell=True, stdout=subprocess.PIPE, text=True)
    p2 = subprocess.run(f"ping -c 1 -w 1 -I {isp_config.ISP2_SOURCE_IP} {ip}", shell=True, stdout=subprocess.PIPE, text=True)
    
    lat1 = next((float(l.split('=')[1].split('/')[1].strip()) for l in p1.stdout.split('\n') if "rtt" in l or "min/avg/max" in l), 0.0)
    lat2 = next((float(l.split('=')[1].split('/')[1].strip()) for l in p2.stdout.split('\n') if "rtt" in l or "min/avg/max" in l), 0.0)

    # Native MTR ASN Traceroute using configuration profiles
    m1 = subprocess.run(f"mtr -r -c 1 -n -z -a {isp_config.ISP1_SOURCE_IP} {ip}", shell=True, stdout=subprocess.PIPE, text=True)
    m2 = subprocess.run(f"mtr -r -c 1 -n -z -a {isp_config.ISP2_SOURCE_IP} {ip}", shell=True, stdout=subprocess.PIPE, text=True)

    # Compile data output structure using the hardcoded module labels
    return {
        "ip": ip,
        "isp1_name": isp_config.ISP1_NAME,
        "isp2_name": isp_config.ISP2_NAME,
        "isp1_status": 1 if p1.returncode == 0 else 0,
        "isp1_latency": lat1,
        "isp1_trace": m1.stdout.strip() if m1.returncode == 0 else "Traceroute Failed",
        "isp2_status": 1 if p2.returncode == 0 else 0,
        "isp2_latency": lat2,
        "isp2_trace": m2.stdout.strip() if m2.returncode == 0 else "Traceroute Failed"
    }

# Phase 2: Orchestrate workers sequentially per unique target block
threads = []
def worker_wrapper(target_ip):
    metrics = run_diagnostics(target_ip)
    results_map[target_ip] = metrics

for ip in target_list:
    t = Thread(target=worker_wrapper, args=(ip,))
    threads.append(t)
    t.start()

for t in threads:
    t.join()

# Phase 3: Compile final clean JSON matrix payload back to Zabbix engine
final_output = [results_map[ip] for ip in target_list if ip in results_map]
print(json.dumps(final_output))
