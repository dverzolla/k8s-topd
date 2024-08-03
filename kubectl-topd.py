#!/opt/homebrew/bin/python3

import subprocess
import json

THRESHOLD_PERCENTAGE = 80
KUBECTL_COMMAND = "kubectl"

# Terminal Color Codes
COLOR = "\033[91m"
COLOR_RESET = "\033[0m"

def run_kubectl_command(command):
    """Run a kubectl command and return its output."""
    full_command = f"{KUBECTL_COMMAND} {command}"
    result = subprocess.run(full_command, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        return result.stdout.strip()
    else:
        raise RuntimeError(f"Command failed: {full_command}\n{result.stderr.strip()}")

def get_node_disk_usage(node_name):
    """Retrieve disk usage for a specific node."""
    disk_info_raw = run_kubectl_command(f"get --raw /api/v1/nodes/{node_name}/proxy/stats/summary")
    disk_info = json.loads(disk_info_raw)
    used_bytes = disk_info["node"]["fs"]["usedBytes"]
    capacity_bytes = disk_info["node"]["fs"]["capacityBytes"]
    return (used_bytes / capacity_bytes) * 100

def is_colorization_needed(usage_percentage):
    """Determine if colorization is needed based on usage percentage."""
    return usage_percentage > THRESHOLD_PERCENTAGE

def colorize(text, color_code):
    """Colorize text if needed."""
    return f"{color_code}{text}{COLOR_RESET}"

def print_node_metrics(node_name, cpu_cores, cpu_percentage, memory_bytes, memory_percentage, disk_usage):
    """Print metrics for a single node, applying colorization based on thresholds."""
    cpu_color = COLOR if is_colorization_needed(float(cpu_percentage.strip('%'))) else ""
    memory_color = COLOR if is_colorization_needed(float(memory_percentage.strip('%'))) else ""
    disk_color = COLOR if is_colorization_needed(disk_usage) else ""

    print(f"{node_name:<30} {cpu_cores:<12} {cpu_color}{cpu_percentage:<6}{COLOR_RESET} {memory_bytes:<14} {memory_color}{memory_percentage:<10}{COLOR_RESET} {disk_color}{disk_usage:.2f}%{COLOR_RESET}")

def main():
    print(f"{'NAME':<30} {'CPU(cores)':<12} {'CPU%':<6} {'MEMORY(bytes)':<14} {'MEMORY%':<10} {'DISK USAGE%':12}")
    top_nodes_output = run_kubectl_command("top nodes --no-headers")
    for line in top_nodes_output.splitlines():
        node_name, cpu_cores, cpu_percentage, memory_bytes, memory_percentage = line.split()[:5]
        disk_usage = get_node_disk_usage(node_name)
        print_node_metrics(node_name, cpu_cores, cpu_percentage, memory_bytes, memory_percentage, disk_usage)

main()

