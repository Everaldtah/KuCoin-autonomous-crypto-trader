#!/bin/bash
# Multi-Pair Trading Bot Daemon v2.0
# Security-hardened auto-restart with health monitoring
#
# Usage: ./multi_pair_daemon.sh {start|stop|restart|status|daemon|emergency-stop}

set -euo pipefail

# ─── Configuration ─────────────────────────────────────────────
BOT_NAME="multi_pair_bot_clean.py"
BOT_PATH="/root/$BOT_NAME"
LOG_FILE="/root/multi_pair_bot.log"
ERROR_LOG="/root/multi_pair_bot_errors.log"
PID_FILE="/root/multi_pair_bot.pid"
STATE_FILE="/root/multi_pair_portfolio_state.json"
SECURITY_LOG="/root/bot_security.log"
EMERGENCY_STOP_FILE="/root/.bot_emergency_stop"
MAX_RESTARTS=5
RESTART_WINDOW=300  # 5 minutes
DAEMON_CHECK_INTERVAL=30  # seconds

# Colors for terminal output (if TTY)
if [[ -t 1 ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m' # No Color
else
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    NC=''
fi

# ─── Logging Functions ────────────────────────────────────────
log_info() {
    echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} ℹ️  $1"
    echo "[$(date '+%H:%M:%S')] [INFO] $1" >> "$LOG_FILE"
}

log_warn() {
    echo -e "${YELLOW}[$(date '+%H:%M:%S')]${NC} ⚠️  $1"
    echo "[$(date '+%H:%M:%S')] [WARN] $1" >> "$LOG_FILE"
}

log_error() {
    echo -e "${RED}[$(date '+%H:%M:%S')]${NC} ❌ $1"
    echo "[$(date '+%H:%M:%S')] [ERROR] $1" >> "$ERROR_LOG"
}

log_success() {
    echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} ✅ $1"
    echo "[$(date '+%H:%M:%S')] [SUCCESS] $1" >> "$LOG_FILE"
}

# ─── Helper Functions ────────────────────────────────────────
check_bot() {
    pgrep -f "python3.*$BOT_NAME" > /dev/null 2>&1
}

get_pid() {
    pgrep -f "python3.*$BOT_NAME" | head -1
}

check_emergency_stop() {
    [[ -f "$EMERGENCY_STOP_FILE" ]]
}

clear_emergency_stop() {
    if [[ -f "$EMERGENCY_STOP_FILE" ]]; then
        rm -f "$EMERGENCY_STOP_FILE"
        log_info "Emergency stop cleared"
    fi
}

trigger_emergency_stop() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Manual emergency stop triggered" > "$EMERGENCY_STOP_FILE"
    log_error "Emergency stop triggered!"
}

# ─── Pre-flight Checks ───────────────────────────────────────
preflight_checks() {
    log_info "Running pre-flight checks..."
    
    # Check bot file exists
    if [[ ! -f "$BOT_PATH" ]]; then
        log_error "Bot file not found: $BOT_PATH"
        exit 1
    fi
    
    # Check Python syntax
    if ! python3 -m py_compile "$BOT_PATH" 2>/dev/null; then
        log_error "Bot has syntax errors!"
        exit 1
    fi
    
    # Check .env exists
    if [[ ! -f "/root/.env" ]]; then
        log_warn ".env file not found"
    fi
    
    # Check credential files are secure
    if [[ -f "/root/.env" ]]; then
        local perms
        perms=$(stat -c %a "/root/.env")
        if [[ "$perms" != "600" ]]; then
            chmod 600 "/root/.env"
            log_warn "Fixed .env permissions to 600"
        fi
    fi
    
    # Check for emergency stop
    if check_emergency_stop; then
        log_error "Emergency stop is active! Clear with: $0 emergency-clear"
        exit 1
    fi
    
    # Check disk space
    local disk_usage
    disk_usage=$(df /root | awk 'NR==2 {print $5}' | tr -d '%')
    if [[ "$disk_usage" -gt 90 ]]; then
        log_error "Disk usage is ${disk_usage}%, bot may fail"
    fi
    
    log_success "Pre-flight checks passed"
}

# ─── Bot Control ─────────────────────────────────────────────
start_bot() {
    if check_bot; then
        log_warn "Bot is already running"
        return 0
    fi
    
    log_info "Starting Multi-Pair Bot (mode: ${1:-production})..."
    
    # Clear any stale PID
    rm -f "$PID_FILE"
    
    # Build command
    local mode_arg=""
    if [[ "${1:-}" == "dry-run" ]]; then
        mode_arg="--dry-run"
    fi
    
    # Rotate logs if too big (>10MB)
    if [[ -f "$LOG_FILE" ]] && [[ $(stat -c%s "$LOG_FILE") -gt 10485760 ]]; then
        mv "$LOG_FILE" "${LOG_FILE}.old"
        touch "$LOG_FILE"
    fi
    
    # Start bot with proper environment
    cd /root
    nohup python3 -u "$BOT_PATH" $mode_arg >> "$LOG_FILE" 2>> "$ERROR_LOG" &
    local pid=$!
    
    # Wait for startup
    sleep 3
    
    if check_bot; then
        echo $pid > "$PID_FILE"
        log_success "Bot started successfully (PID: $(get_pid))"
        
        # Telegram notification (if token available)
        if [[ -f "/root/.env" ]]; then
            local token
            token=$(grep "TELEGRAM_TOKEN=" "/root/.env" | cut -d'=' -f2 | head -1)
            if [[ -n "$token" ]] && command -v curl &>/dev/null; then
                local chat_id
                chat_id=$(grep "TELEGRAM_CHAT_ID=" "/root/.env" | cut -d'=' -f2 | head -1)
                curl -s -X POST "https://api.telegram.org/bot${token}/sendMessage" \
                    -d "chat_id=${chat_id}" \
                    -d "text=🚀 Multi-Pair Bot STARTED at $(date)" \
                    >/dev/null 2>&1 || true
            fi
        fi
        return 0
    else
        log_error "Failed to start bot"
        return 1
    fi
}

stop_bot() {
    log_info "Stopping bot..."
    
    if ! check_bot; then
        log_warn "Bot not running"
        rm -f "$PID_FILE"
        return 0
    fi
    
    local pid
    pid=$(get_pid)
    
    # Send graceful shutdown signal
    kill -TERM "$pid" 2>/dev/null || true
    
    # Wait for shutdown
    local count=0
    while check_bot && [[ $count -lt 10 ]]; do
        sleep 1
        ((count++))
    done
    
    # Force kill if still running
    if check_bot; then
        log_warn "Force stopping bot..."
        kill -9 "$pid" 2>/dev/null || true
        sleep 1
    fi
    
    rm -f "$PID_FILE"
    
    if ! check_bot; then
        log_success "Bot stopped"
    else
        log_error "Failed to stop bot"
        return 1
    fi
}

restart_bot() {
    log_info "Restarting bot..."
    stop_bot
    sleep 2
    start_bot "$@"
}

status_bot() {
    if check_bot; then
        local pid uptime_secs
        pid=$(get_pid)
        uptime_secs=$(ps -o etimes= -p "$pid" 2>/dev/null | tr -d ' ' || echo "0")
        
        local uptime_str
        if [[ "$uptime_secs" -gt 3600 ]]; then
            uptime_str="$(($uptime_secs / 3600))h $((($uptime_secs % 3600) / 60))m"
        elif [[ "$uptime_secs" -gt 60 ]]; then
            uptime_str="$(($uptime_secs / 60))m $(($uptime_secs % 60))s"
        else
            uptime_str="${uptime_secs}s"
        fi
        
        echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} ✅ Bot is ${GREEN}RUNNING${NC}"
        echo "   PID: $pid"
        echo "   Uptime: $uptime_str"
        
        # Show last log line
        if [[ -f "$LOG_FILE" ]]; then
            local last_line
            last_line=$(tail -1 "$LOG_FILE" 2>/dev/null | cut -c1-70)
            echo "   Last log: $last_line..."
        fi
        
        # Show position count if state exists
        if [[ -f "$STATE_FILE" ]]; then
            local pos_count
            pos_count=$(python3 -c "import json; d=json.load(open('$STATE_FILE')); print(len(d.get('active_positions', {})))" 2>/dev/null || echo "?")
            echo "   Active positions: $pos_count"
        fi
        
        return 0
    else
        echo -e "${YELLOW}[$(date '+%H:%M:%S')]${NC} ⚠️  Bot is ${YELLOW}STOPPED${NC}"
        
        if check_emergency_stop; then
            echo -e "   ${RED}⚠️ Emergency stop is ACTIVE${NC}"
            cat "$EMERGENCY_STOP_FILE"
        fi
        
        return 1
    fi
}

# ─── Daemon Mode ───────────────────────────────────────────────
daemon_mode() {
    log_info "Starting Watchdog Daemon v2.0..."
    log_info "Monitor interval: ${DAEMON_CHECK_INTERVAL}s"
    log_info "Max restarts: $MAX_RESTARTS per ${RESTART_WINDOW}s"
    
    local restart_count=0
    local window_start=$(date +%s)
    
    while true; do
        # Check emergency stop
        if check_emergency_stop; then
            log_error "Emergency stop active - daemon pausing"
            while check_emergency_stop; do
                sleep 5
            done
            log_info "Emergency stop cleared - resuming"
        fi
        
        # Reset restart counter if window passed
        local now=$(date +%s)
        if [[ $((now - window_start)) -gt $RESTART_WINDOW ]]; then
            restart_count=0
            window_start=$now
        fi
        
        # Check if bot is running
        if ! check_bot; then
            log_warn "Bot not running!"
            
            if [[ $restart_count -ge $MAX_RESTARTS ]]; then
                log_error "Too many restarts! Manual intervention required."
                trigger_emergency_stop
                exit 1
            fi
            
            log_info "Restart attempt $((restart_count + 1))/$MAX_RESTARTS"
            if start_bot; then
                ((restart_count++))
            fi
        fi
        
        sleep $DAEMON_CHECK_INTERVAL
    done
}

# ─── Command Dispatch ────────────────────────────────────────
case "${1:-}" in
    start)
        preflight_checks
        start_bot "${2:-}"
        ;;
    stop)
        stop_bot
        ;;
    restart)
        restart_bot
        ;;
    status)
        status_bot
        ;;
    daemon)
        preflight_checks
        daemon_mode
        ;;
    dry-run)
        preflight_checks
        start_bot "dry-run"
        ;;
    emergency-stop)
        trigger_emergency_stop
        stop_bot
        ;;
    emergency-clear)
        clear_emergency_stop
        ;;
    logs)
        if [[ -f "$LOG_FILE" ]]; then
            tail -100 "$LOG_FILE"
        else
            echo "No log file found"
        fi
        ;;
    errors)
        if [[ -f "$ERROR_LOG" ]]; then
            tail -50 "$ERROR_LOG"
        else
            echo "No error log found"
        fi
        ;;
    security)
        if [[ -f "$SECURITY_LOG" ]]; then
            tail -50 "$SECURITY_LOG"
        else
            echo "No security log found"
        fi
        ;;
    *)
        echo "Multi-Pair Trading Bot Daemon v2.0"
        echo ""
        echo "Usage: $0 {start|stop|restart|status|daemon|dry-run|emergency-stop|emergency-clear|logs|errors|security}"
        echo ""
        echo "Commands:"
        echo "  start           Start the bot in production mode"
        echo "  stop            Stop the bot"
        echo "  restart         Restart the bot"
        echo "  status          Show bot status and health"
        echo "  daemon          Run watchdog (auto-restart on crash)"
        echo "  dry-run         Start in simulation mode"
        echo "  emergency-stop  Trigger emergency stop (kills bot)"
        echo "  emergency-clear Clear emergency stop state"
        echo "  logs            Show last 100 log lines"
        echo "  errors          Show last 50 error lines"
        echo "  security        Show security log"
        exit 1
        ;;
esac
