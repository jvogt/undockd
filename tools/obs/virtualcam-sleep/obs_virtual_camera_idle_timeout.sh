#!/bin/bash

RAW_SYSTEM_SCREENSAVER_IDLE_TIME="$(defaults -currentHost read com.apple.screensaver idleTime | xargs)"

# Subtract 10 seconds (defaults to 0 if the math results in a negative number)
if [ "$RAW_SYSTEM_SCREENSAVER_IDLE_TIME" -gt 10 ]; then
    SYSTEM_SCREENSAVER_IDLE_TIME=$(( RAW_SYSTEM_SCREENSAVER_IDLE_TIME - 10 ))
else
    SYSTEM_SCREENSAVER_IDLE_TIME=0
fi

OBS_CONNECTED="false"

while true; do
    SECONDS_OF_IDLE=$(./seconds_since_inactive.sh 2>/dev/null)
    if OBS_VIRTUALCAM_STATUS_OUTPUT=$(obs-cli virtualcam status 2>/dev/null); then
        if [ "$OBS_CONNECTED" != "true" ]; then
            OBS_CONNECTED="true"
            echo "OBS Connected" >&2
        fi
        OBS_VIRTUALCAM_STATUS="$(grep "started" <<< "${OBS_VIRTUALCAM_STATUS_OUTPUT}")"
        if (( SECONDS_OF_IDLE > SYSTEM_SCREENSAVER_IDLE_TIME )); then
            if [ -n "$OBS_VIRTUALCAM_STATUS" ]; then
                echo "System idle for ${SECONDS_OF_IDLE} seconds. Stopping virtual camera." >&2
                obs-cli virtualcam stop
            fi
        else
            if [ -z "$OBS_VIRTUALCAM_STATUS" ]; then
                echo "System not idle. Starting virtual camera." >&2
                obs-cli virtualcam start
            fi
        fi

    else
        if [ "$OBS_CONNECTED" = "true" ] || [ -z "$OBS_CONNECTED" ]; then
            echo "OBS Disconnected" >&2
            OBS_CONNECTED="false"
        fi
    fi
    sleep 5
done
