#!/bin/bash
# ETH Trader Daemon - Auto-restart on crash/reboot
# This script ensures the bot is ALWAYS running

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BOT_NAME="trader.py"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/bot.log"
PID_FILE="$PROJECT_DIR/data/bot.pid"

mkdir -p "$LOG_DIR" "$PROJECT_DIR/data"

check_bot() {
    pgrep -f "python3.*$BOT_NAME" > /dev/null 2>&1
    return $?
}

start_bot() {
    echo "[$(date '+%H:%M:%S')] Starting ETH Trader Bot..."
    cd "$PROJECT_DIR"
    rm -f "$PID_FILE"
    nohup python3 -u src/$BOT_NAME >> "$LOG_FILE" 2>&1 &
    sleep 3
    
    if check_bot; then
        echo "[$(date '+%H:%M:%S')] Bot started successfully"
    else
        echo "[$(date '+%H:%M:%S')] Failed to start bot"
    fi
}

stop_bot() {
    echo "[$(date '+%H:%M:%S')] Stopping ETH Trader Bot..."
    pkill -f "python3.*$BOT_NAME" 2>/dev/null
    rm -f "$PID_FILE"
    echo "[$(date '+%H:%M:%S')] Bot stopped"
}

restart_bot() {
    stop_bot
    sleep 1
    start_bot
}

status_bot() {
    if check_bot; then
        PID=$(pgrep -f "python3.*$BOT_NAME" | head -1)
        UPTIME=$(ps -o etime= -p $PID 2>/dev/null | tr -d ' ')
        echo "[$(date '+%H:%M:%S')] Bot is RUNNING (PID: $PID, Uptime: ${UPTIME:-unknown})"
    else
        echo "[$(date '+%H:%M:%S')] Bot is STOPPED"
    fi
}

# Watchdog mode - keep bot running
daemon_mode() {
    echo "[$(date '+%H:%M:%S')] Starting Watchdog Daemon..."
    while true; do
        if ! check_bot; then
            echo "[$(date '+%H:%M:%S')] Bot crashed or stopped! Restarting..."
            start_bot
        fi
        sleep 30
    done
}

case "$1" in
    start)   start_bot ;;
    stop)    stop_bot ;;
    restart) restart_bot ;;
    status)  status_bot ;;
    daemon)  daemon_mode ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|daemon}"
        echo "  start   - Start the bot"
        echo "  stop    - Stop the bot"
        echo "  restart - Restart the bot"
        echo "  status  - Check bot status"
        echo "  daemon  - Run watchdog (auto-restart on crash)"
        exit 1
        ;;
esac
