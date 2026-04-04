#!/usr/bin/env bash
# Pi health logger — runs every 5 minutes via cron.
# Logs temperature, throttle flags, and memory to syslog.
# Install: echo "*/5 * * * * /home/dev/signage/toolchain/pi-health.sh" | crontab -

TEMP=$(vcgencmd measure_temp | cut -d= -f2)
THROTTLE=$(vcgencmd get_throttled | cut -d= -f2)
VOLTS=$(vcgencmd measure_volts core | cut -d= -f2)
MEM_USED=$(free -m | awk '/^Mem:/{print $3}')
MEM_TOTAL=$(free -m | awk '/^Mem:/{print $2}')
LOAD=$(cat /proc/loadavg | cut -d' ' -f1-3)

logger -t pi-health "temp=${TEMP} throttle=${THROTTLE} core_v=${VOLTS} mem=${MEM_USED}/${MEM_TOTAL}M load=${LOAD}"

# Alert on any throttle flag
if [ "$THROTTLE" != "0x0" ]; then
    logger -t pi-health -p warning "THROTTLE FLAG SET: ${THROTTLE}"
fi
