#!/usr/bin/env python3

import subprocess
import argparse
import re
import time
import atexit
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

THRESHOLD_PERCENTAGE = 80
KUBECTL_COMMAND = "kubectl"

COLOR = "\033[91m"  # red
COLOR_RESET = "\033[0m"

_proxy_proc = None

def start_kubectl_proxy():
    global _proxy_proc
    _proxy_proc = subprocess.Popen(
        [KUBECTL_COMMAND, "proxy", "--port=0", "--address=127.0.0.1", "--accept-hosts=.+", "--accept-paths=.+"] ,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    # Ensure cleanup on exit
    def _cleanup():
        try:
            if _proxy_proc and _proxy_proc.poll() is None:
                _proxy_proc.terminate()
        except Exception:
            pass
    atexit.register(_cleanup)

    start = time.time()
    port = None
    while time.time() - start < 5:
        line = _proxy_proc.stdout.readline()
        if not line:
            time.sleep(0.05)
            continue
        m = re.search(r"Starting to serve on 127\.0\.0\.1:(\d+)", line)
        if m:
            port = int(m.group(1))
            break
    if not port:
        try:
            leftover = _proxy_proc.stdout.read()
        except Exception:
            leftover = ""
        raise RuntimeError(f"Failed to start kubectl proxy. Output so far:\n{leftover or '(no output)'}")

    return f"http://127.0.0.1:{port}"

_BIN = {
    "Ki": 1024,
    "Mi": 1024**2,
    "Gi": 1024**3,
    "Ti": 1024**4,
    "Pi": 1024**5,
    "Ei": 1024**6,
}

_DEC = {
    "n": 1e-9,
    "u": 1e-6,
    "m": 1e-3,
    "": 1.0,
    "k": 1e3, "K": 1e3,
    "M": 1e6,
    "G": 1e9,
    "T": 1e12,
    "P": 1e15,
    "E": 1e18,
}

def parse_memory_to_bytes(q: str) -> int:
    q = str(q).strip()
    if not q:
        return 0
    for suf, mult in _BIN.items():
        if q.endswith(suf):
            base = float(q[:-len(suf)] or 0)
            return int(base * mult)
    m = re.match(r"^([0-9.]+)([kKMGTPE]?)$", q)
    if m:
        val = float(m.group(1))
        suf = m.group(2)
        mult = _DEC.get(suf, 1.0)
        return int(val * mult)
    if q.isdigit():
        return int(q)
    try:
        return int(float(q))
    except Exception:
        return 0

def parse_cpu_to_millicores(q: str) -> int:
    q = str(q).strip()
    if not q:
        return 0
    if q.endswith("m"):
        return int(float(q[:-1]))
    if q.endswith("n"):
        n = float(q[:-1] or 0)
        return int(n * 1000.0 / 1e9)
    try:
        cores = float(q)
        return int(cores * 1000.0)
    except Exception:
        return 0

def http_get_json(session: requests.Session, url: str, timeout: float, params=None):
    r = session.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

def list_nodes(session, base_url, selector, timeout):
    url = f"{base_url}/api/v1/nodes"
    params = {"labelSelector": selector} if selector else None
    return http_get_json(session, url, timeout, params=params)

def list_node_metrics(session, base_url, timeout):
    url = f"{base_url}/apis/metrics.k8s.io/v1beta1/nodes"
    return http_get_json(session, url, timeout)

def fetch_node_disk_usage(session, base_url, node_name, timeout):
    url = f"{base_url}/api/v1/nodes/{node_name}/proxy/stats/summary"
    data = http_get_json(session, url, timeout)
    used = data["node"]["fs"]["usedBytes"]
    cap = data["node"]["fs"]["capacityBytes"]
    if cap == 0:
        return 0.0
    return (used / cap) * 100.0

def is_colorization_needed(usage_percentage):
    return usage_percentage > THRESHOLD_PERCENTAGE

def colorize(text, color_code):
    return f"{color_code}{text}{COLOR_RESET}"

def print_node_metrics(node_name, cpu_cores, cpu_percentage, memory_bytes, memory_percentage, disk_usage, label_values):
    cpu_color = COLOR if is_colorization_needed(float(str(cpu_percentage).strip('%') or 0)) else ""
    memory_color = COLOR if is_colorization_needed(float(str(memory_percentage).strip('%') or 0)) else ""
    disk_color = COLOR if is_colorization_needed(disk_usage) else ""

    name_w = 30
    cpu_cores_w = 12
    cpu_perc_w = 6
    mem_bytes_w = 14
    mem_perc_w = 10
    disk_usage_w = 12
    label_col_w = 15

    output_parts = [
        f"{node_name:<{name_w}}",
        f"{cpu_cores:<{cpu_cores_w}}",
        f"{cpu_color}{cpu_percentage:<{cpu_perc_w}}{COLOR_RESET}",
        f"{memory_bytes:<{mem_bytes_w}}",
        f"{memory_color}{memory_percentage:<{mem_perc_w}}{COLOR_RESET}",
        f"{disk_color}{f'{disk_usage:.2f}%':<{disk_usage_w}}{COLOR_RESET}"
    ]

    label_display_parts = []
    for value in label_values:
        label_display_parts.append(f"{str(value):<{label_col_w}}")

    print(" ".join(output_parts + label_display_parts))

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9%]+", "", s.lower())

_BUILTIN_COL_MAP = {
    _norm("name"): "name",

    # CPU
    _norm("cpu(cores)"): "cpu_m",
    _norm("cpucores"): "cpu_m",
    _norm("cpu"): "cpu_m",
    _norm("cpu%"): "cpu_perc",

    # Memory
    _norm("memory(bytes)"): "mem_bytes",
    _norm("memory"): "mem_bytes",
    _norm("mem"): "mem_bytes",
    _norm("memory%"): "mem_perc",
    _norm("mem%"): "mem_perc",

    # Disk
    _norm("disk usage%"): "disk_perc",
    _norm("disk%"): "disk_perc",
    _norm("disk"): "disk_perc",
}

def parse_order_by(spec: str, requested_labels):
    if not spec:
        return []

    orders = []
    for raw in spec.split(","):
        item = raw.strip()
        if not item:
            continue

        m = re.match(r"^(.*?)(?::(asc|desc))?$", item, re.IGNORECASE)
        col = (m.group(1) or "").strip()
        direction = (m.group(2) or "asc").lower()
        reverse = (direction == "desc")

        ncol = _norm(col)

        key = _BUILTIN_COL_MAP.get(ncol)
        if key:
            orders.append((key, reverse, None))
            continue

        label_match = None
        for lk in requested_labels:
            if _norm(lk) == ncol or lk == col:
                label_match = lk
                break
        if label_match is not None:
            orders.append(("label", reverse, label_match))
            continue

        for alias, builtin_key in _BUILTIN_COL_MAP.items():
            if alias.startswith(ncol) or ncol.startswith(alias):
                orders.append((builtin_key, reverse, None))
                break

    return orders

def sort_rows_in_place(rows, order_specs):
    if not order_specs:
        return
    for key, reverse, label_key in reversed(order_specs):
        if key == "label":
            rows.sort(key=lambda r: (r["labels"].get(label_key, "") or ""), reverse=reverse)
        else:
            def _k(r):
                v = r.get(key, None)
                if v is None:
                    return float("-inf") if not reverse else float("inf")
                return v
            rows.sort(key=_k, reverse=reverse)

def main():
    parser = argparse.ArgumentParser(
        description="Top nodes via API server (kubectl proxy), with ephemeral disk and customizable label columns."
    )
    parser.add_argument(
        "-L", "--label-columns",
        action="append",
        default=[],
        help=("Label (or comma-separated list) to display as a column. "
              "Can be specified multiple times (e.g., -L zone -L region) or as a comma-separated list (e.g., -L zone,region).")
    )
    parser.add_argument(
        "-l", "--selector",
        help=("Label selector to filter nodes (behaves like 'kubectl -l'). "
              "Examples: -l env=prod  |  -l 'nodepool in (blue,green)'")
    )
    parser.add_argument(
        "-O", "--order-by",
        help=("Order rows by column(s). Comma-separated. "
              "Use :asc or :desc (default asc). "
              "Examples: -O 'CPU%%:desc'  |  -O 'group:asc,CPU%%:desc'. "
              "Valid columns: name, cpu(cores), cpu%%, memory(bytes), memory%%, disk%%, and any -L label key.")
    )
    parser.add_argument(
        "--proxy-url",
        help=("Base URL of an existing kubectl proxy, e.g. http://127.0.0.1:8001 . "
              "If omitted, the script will start its own 'kubectl proxy'.")
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="HTTP timeout (seconds) for API calls. Default: 5.0"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=16,
        help="Max concurrent requests for disk stats. Default: 16"
    )
    args = parser.parse_args()

    # parse -L columns
    requested_labels = []
    for item in args.label_columns:
        requested_labels.extend([label.strip() for label in item.split(',') if label.strip()])
    seen = set()
    requested_labels = [x for x in requested_labels if not (x in seen or seen.add(x))]

    header_parts = [
        f"{'NAME':<30}",
        f"{'CPU(cores)':<12}",
        f"{'CPU%':<6}",
        f"{'MEMORY(bytes)':<14}",
        f"{'MEMORY%':<10}",
        f"{'DISK USAGE%':<12}"
    ]
    label_col_w = 15
    for label_key in requested_labels:
        header_parts.append(f"{label_key.upper():<{label_col_w}}")
    print(" ".join(header_parts))

    if args.proxy_url:
        base_url = args.proxy_url.rstrip("/")
    else:
        base_url = start_kubectl_proxy()

    session = requests.Session()

    nodes_json = list_nodes(session, base_url, args.selector, args.timeout)
    items = nodes_json.get("items", [])
    if not items:
        return

    node_names = []
    labels_by_node = {}
    cpu_capacity_m = {}
    mem_capacity_bytes = {}

    for item in items:
        meta = item.get("metadata", {})
        status = item.get("status", {})
        name = meta.get("name")
        if not name:
            continue
        node_names.append(name)
        labels_by_node[name] = meta.get("labels", {}) or {}
        cap = status.get("capacity", {}) or {}
        cpu_capacity_m[name] = parse_cpu_to_millicores(cap.get("cpu", "0"))
        mem_capacity_bytes[name] = parse_memory_to_bytes(cap.get("memory", "0"))

    selected = set(node_names)

    # metrics 
    metrics_json = list_node_metrics(session, base_url, args.timeout)
    metrics_items = metrics_json.get("items", [])
    cpu_used_m = {}
    mem_used_bytes = {}
    for it in metrics_items:
        meta = it.get("metadata", {}) or {}
        name = meta.get("name")
        if not name or name not in selected:
            continue
        usage = it.get("usage", {}) or {}
        cpu_used_m[name] = parse_cpu_to_millicores(usage.get("cpu", "0"))
        mem_used_bytes[name] = parse_memory_to_bytes(usage.get("memory", "0"))

    # disk (concurrent)
    disk_usage = {}
    max_workers = max(1, min(args.concurrency, len(node_names)))
    futures = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for n in node_names:
            futures[pool.submit(fetch_node_disk_usage, session, base_url, n, args.timeout)] = n
        for fut in as_completed(futures):
            n = futures[fut]
            try:
                disk_usage[n] = float(fut.result())
            except Exception:
                disk_usage[n] = 0.0

    # sorting
    rows = []
    for name in node_names:
        used_m = cpu_used_m.get(name, 0)
        cap_m = cpu_capacity_m.get(name, 0) or 1
        cpu_perc = (used_m / cap_m) * 100.0

        mem_used = mem_used_bytes.get(name, 0)
        mem_cap = mem_capacity_bytes.get(name, 0) or 1
        mem_perc = (mem_used / mem_cap) * 100.0

        rows.append({
            "name": name,
            "cpu_m": float(used_m),
            "cpu_perc": float(cpu_perc),
            "mem_bytes": float(mem_used),
            "mem_perc": float(mem_perc),
            "disk_perc": float(disk_usage.get(name, 0.0)),
            "labels": labels_by_node.get(name, {}),
        })

    order_specs = parse_order_by(args.order_by, requested_labels)
    sort_rows_in_place(rows, order_specs)

    for r in rows:
        name = r["name"]
        cpu_cores_str = f"{int(r['cpu_m'])}m"
        cpu_perc_str = f"{int(round(r['cpu_perc']))}%"
        mem_bytes_str = f"{int(r['mem_bytes'])}"
        mem_perc_str = f"{int(round(r['mem_perc']))}%"
        disk = r["disk_perc"]

        label_values = []
        if requested_labels:
            all_labels = r["labels"]
            label_values = [all_labels.get(k, "<none>") for k in requested_labels]

        print_node_metrics(name, cpu_cores_str, cpu_perc_str, mem_bytes_str, mem_perc_str, disk, label_values)

if __name__ == "__main__":
    main()
