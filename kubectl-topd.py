#!/usr/bin/env python3

import subprocess
import json
import argparse

THRESHOLD_PERCENTAGE = 80
KUBECTL_COMMAND = "kubectl"

COLOR = "\033[91m" # red
COLOR_RESET = "\033[0m"

def run_kubectl_command(command):
    full_command = f"{KUBECTL_COMMAND} {command}"
    result = subprocess.run(full_command, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        return result.stdout.strip()
    else:
        raise RuntimeError(f"Command failed: {full_command}\n{result.stderr.strip()}")

def get_node_disk_usage(node_name):
    disk_info_raw = run_kubectl_command(f"get --raw /api/v1/nodes/{node_name}/proxy/stats/summary")
    disk_info = json.loads(disk_info_raw)
    used_bytes = disk_info["node"]["fs"]["usedBytes"]
    capacity_bytes = disk_info["node"]["fs"]["capacityBytes"]
    return (used_bytes / capacity_bytes) * 100

def get_node_labels(node_name, requested_label_keys):
    if not requested_label_keys:
        return []
    try:
        node_info_raw = run_kubectl_command(f"get node {node_name} -o json")
        node_info = json.loads(node_info_raw)
        all_labels = node_info.get("metadata", {}).get("labels", {})
        label_values = [all_labels.get(key, "<none>") for key in requested_label_keys]
        return label_values
    except Exception as e:
        print(f"Warning: Could not fetch labels for node {node_name}: {e}") 
        return ["<error>"] * len(requested_label_keys)

def is_colorization_needed(usage_percentage):
    return usage_percentage > THRESHOLD_PERCENTAGE

def colorize(text, color_code):
    return f"{color_code}{text}{COLOR_RESET}"

def print_node_metrics(node_name, cpu_cores, cpu_percentage, memory_bytes, memory_percentage, disk_usage, label_values):
    cpu_color = COLOR if is_colorization_needed(float(cpu_percentage.strip('%'))) else ""
    memory_color = COLOR if is_colorization_needed(float(memory_percentage.strip('%'))) else ""
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

def main():
    parser = argparse.ArgumentParser(description="Extends 'kubectl top nodes' to include ephemeral disk usage and customizable label columns.")
    parser.add_argument(
        "-L", "--label-columns",
        action="append",
        default=[],
        help="Label (or comma-separated list) to display as a column. Can be specified multiple times (e.g., -L zone -L region) or as a comma-separated list (e.g., -L zone,region)." 
    )
    args = parser.parse_args()

    requested_labels = []
    if args.label_columns:
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

    top_nodes_output = run_kubectl_command("top nodes --no-headers")
    for line in top_nodes_output.splitlines():
        parts = line.split()
        node_name = parts[0]
        cpu_cores = parts[1]
        cpu_percentage = parts[2]
        memory_bytes = parts[3]
        memory_percentage = parts[4]

        disk_usage = get_node_disk_usage(node_name)
        node_label_values = get_node_labels(node_name, requested_labels)
        
        print_node_metrics(node_name, cpu_cores, cpu_percentage, memory_bytes, memory_percentage, disk_usage, node_label_values)

if __name__ == "__main__":
    main()