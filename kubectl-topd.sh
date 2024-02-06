#!/bin/bash
# https://github.com/dverzolla/k8s-topd

get_disk_usage() {
    node_name=$1
    disk_info=$(kubectl get --raw /api/v1/nodes/$node_name/proxy/stats/summary)
    if [ $? -eq 0 ]; then
        used_bytes=$(echo $disk_info | jq '.node.fs.usedBytes')
        capacity_bytes=$(echo $disk_info | jq '.node.fs.capacityBytes')
        disk_usage=$(echo | awk -v used="$used_bytes" -v capacity="$capacity_bytes" '{printf "%.2f%%", (used / capacity) * 100}')
        echo "$disk_usage"
    else
        echo "Error"
    fi
}

# column widths
name_width=30
cpu_cores_width=12
cpu_percentage_width=6
memory_bytes_width=14
memory_percentage_width=10
disk_usage_width=12

printf "%-${name_width}s %-${cpu_cores_width}s %-${cpu_percentage_width}s %-${memory_bytes_width}s %-${memory_percentage_width}s %-${disk_usage_width}s\n" "NAME" "CPU(cores)" "CPU%" "MEMORY(bytes)" "MEMORY%" "DISK USAGE%"

top_nodes=$(kubectl top nodes --no-headers)
if [ $? -ne 0 ]; then
    echo "Failed to get node data."
    exit 1
fi

echo "$top_nodes" | while read -r line; do
    node_name=$(echo $line | awk '{print $1}')
    cpu_cores=$(echo $line | awk '{print $2}')
    cpu_percentage=$(echo $line | awk '{print $3}')
    memory_bytes=$(echo $line | awk '{print $4}')
    memory_percentage=$(echo $line | awk '{print $5}')

    disk_usage=$(get_disk_usage "$node_name")

    printf "%-${name_width}s %-${cpu_cores_width}s %-${cpu_percentage_width}s %-${memory_bytes_width}s %-${memory_percentage_width}s %-${disk_usage_width}s\n" "$node_name" "$cpu_cores" "$cpu_percentage" "$memory_bytes" "$memory_percentage" "$disk_usage"
done
