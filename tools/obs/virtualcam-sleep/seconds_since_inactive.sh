#!/bin/bash

# Get the Human Interface Device (HID) idle time in nanoseconds
idle_nanoseconds=$(ioreg -c IOHIDSystem | awk '/HIDIdleTime/ {print $NF; exit}')

# Convert nanoseconds to seconds
idle_seconds=$((idle_nanoseconds / 1000000000))

echo "$(date): Seconds since last activity: $idle_seconds" >&2
echo $idle_seconds