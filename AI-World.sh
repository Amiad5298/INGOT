#!/usr/bin/env bash

################################################################################
# AI Workflow Script
# Version: 2.0.0
# Description: Standardized script for AI-assisted development workflows
# Author: Development Team
# Dependencies: bash 4.3+, Node.js 22+, npm, git, Auggie CLI
################################################################################

################################################################################
# Bash Version Check (must run before set -u to avoid issues)
################################################################################
# Requires Bash 4.3+ for nameref (local -n) and associative array features
# macOS ships with Bash 3.2; users must install modern Bash via Homebrew
REQUIRED_BASH_MAJOR=4
REQUIRED_BASH_MINOR=3

if [[ -z "${BASH_VERSINFO[0]:-}" ]] || \
   [[ "${BASH_VERSINFO[0]}" -lt "$REQUIRED_BASH_MAJOR" ]] || \
   [[ "${BASH_VERSINFO[0]}" -eq "$REQUIRED_BASH_MAJOR" && "${BASH_VERSINFO[1]}" -lt "$REQUIRED_BASH_MINOR" ]]; then
    echo "ERROR: This script requires Bash ${REQUIRED_BASH_MAJOR}.${REQUIRED_BASH_MINOR} or later." >&2
    echo "Current Bash version: ${BASH_VERSION:-unknown}" >&2
    echo "" >&2
    echo "On macOS, install modern Bash via Homebrew:" >&2
    echo "  brew install bash" >&2
    echo "" >&2
    echo "Then run this script with the new Bash:" >&2
    echo "  /opt/homebrew/bin/bash $0" >&2
    echo "  # or on Intel Macs:" >&2
    echo "  /usr/local/bin/bash $0" >&2
    echo "" >&2
    echo "Alternatively, add Homebrew's Bash to your PATH before /bin/bash." >&2
    exit 1
fi

set -e  # Exit on error
set -u  # Exit on undefined variable
set -o pipefail  # Exit on pipe failure

################################################################################
# Script Metadata
################################################################################
SCRIPT_VERSION="2.0.0"
SCRIPT_NAME="AI Workflow Script"
REQUIRED_AUGGIE_VERSION="0.12.0"
REQUIRED_NODE_VERSION="22"

# Logging configuration
LOG_ENABLED="${AI_WORKFLOW_LOG:-false}"
LOG_FILE="${AI_WORKFLOW_LOG_FILE:-${HOME}/.ai-workflow.log}"

# Configuration file
CONFIG_FILE="${HOME}/.ai-workflow-config"

# CLI Flags
NO_OPEN=false
SKIP_CLARIFICATION=false
FORCE_JIRA_CHECK=false
PRESET_TICKET=""
PRESET_BRANCH=""
PRESET_MODEL=""

# Task List State
TASK_LIST_FILE=""
TASK_LIST_ARRAY=()
CURRENT_TASK_INDEX=0
TOTAL_TASKS=0

################################################################################
# Color Output Utilities
################################################################################
# Check if terminal supports colors
if [[ -t 1 ]] && command -v tput &> /dev/null && tput colors &> /dev/null; then
    COLORS=$(tput colors)
    if [[ $COLORS -ge 8 ]]; then
        COLOR_RESET="\033[0m"
        COLOR_RED="\033[0;31m"
        COLOR_GREEN="\033[0;32m"
        COLOR_YELLOW="\033[0;33m"
        COLOR_BLUE="\033[0;34m"
        COLOR_MAGENTA="\033[0;35m"
        COLOR_CYAN="\033[0;36m"
        COLOR_WHITE="\033[0;37m"
        COLOR_BOLD="\033[1m"
    else
        COLOR_RESET=""
        COLOR_RED=""
        COLOR_GREEN=""
        COLOR_YELLOW=""
        COLOR_BLUE=""
        COLOR_MAGENTA=""
        COLOR_CYAN=""
        COLOR_WHITE=""
        COLOR_BOLD=""
    fi
else
    COLOR_RESET=""
    COLOR_RED=""
    COLOR_GREEN=""
    COLOR_YELLOW=""
    COLOR_BLUE=""
    COLOR_MAGENTA=""
    COLOR_CYAN=""
    COLOR_WHITE=""
    COLOR_BOLD=""
fi

################################################################################
# Configuration Functions
################################################################################

# Associative array to hold loaded config values (populated by load_config)
declare -A CONFIG_VALUES=()

# Load configuration from file
# SECURITY: Uses safe line-by-line parsing instead of source to prevent RCE
# Only reads KEY=VALUE or KEY="VALUE" pairs; ignores malformed lines
load_config() {
    CONFIG_VALUES=()

    if [[ ! -f "$CONFIG_FILE" ]]; then
        log_message "No configuration file found at ${CONFIG_FILE}"
        return 0
    fi

    log_message "Loading configuration from ${CONFIG_FILE}"

    while IFS= read -r line || [[ -n "$line" ]]; do
        # Skip empty lines and comments
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue

        # Match KEY=VALUE or KEY="VALUE" patterns
        # Key must be alphanumeric with underscores, starting with letter or underscore
        if [[ "$line" =~ ^([a-zA-Z_][a-zA-Z0-9_]*)=(.*)$ ]]; then
            local key="${BASH_REMATCH[1]}"
            local value="${BASH_REMATCH[2]}"

            # Remove surrounding quotes if present
            if [[ "$value" =~ ^\"(.*)\"$ ]]; then
                value="${BASH_REMATCH[1]}"
            elif [[ "$value" =~ ^\'(.*)\'$ ]]; then
                value="${BASH_REMATCH[1]}"
            fi

            CONFIG_VALUES["$key"]="$value"
        fi
    done < "$CONFIG_FILE"

    log_message "Configuration loaded successfully (${#CONFIG_VALUES[@]} keys)"
}

# Save configuration to file
# SECURITY: Uses line-by-line rewrite instead of sed to avoid injection issues
# Properly quotes values to handle spaces and special characters
save_config() {
    local key="$1"
    local value="$2"

    # Validate key name (alphanumeric and underscore only)
    if [[ ! "$key" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]]; then
        print_error "Invalid config key: ${key}"
        return 1
    fi

    # Update in-memory config
    CONFIG_VALUES["$key"]="$value"

    # Create config file if it doesn't exist
    if [[ ! -f "$CONFIG_FILE" ]]; then
        touch "$CONFIG_FILE"
        chmod 600 "$CONFIG_FILE"  # Secure the config file
    fi

    # Rewrite entire config file (safe approach - no sed injection)
    local temp_file
    temp_file=$(mktemp)

    # Track which keys we've written
    declare -A written_keys=()

    # Read existing file and update/preserve entries
    if [[ -f "$CONFIG_FILE" ]]; then
        while IFS= read -r line || [[ -n "$line" ]]; do
            # Preserve comments and empty lines
            if [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]]; then
                echo "$line" >> "$temp_file"
                continue
            fi

            # Check if this is a key we're updating
            if [[ "$line" =~ ^([a-zA-Z_][a-zA-Z0-9_]*)= ]]; then
                local existing_key="${BASH_REMATCH[1]}"
                if [[ -n "${CONFIG_VALUES[$existing_key]+x}" ]]; then
                    # Write the updated value
                    echo "${existing_key}=\"${CONFIG_VALUES[$existing_key]}\"" >> "$temp_file"
                    written_keys["$existing_key"]=1
                else
                    # Preserve unknown keys
                    echo "$line" >> "$temp_file"
                fi
            else
                # Preserve malformed lines
                echo "$line" >> "$temp_file"
            fi
        done < "$CONFIG_FILE"
    fi

    # Add any new keys that weren't in the file
    for k in "${!CONFIG_VALUES[@]}"; do
        if [[ -z "${written_keys[$k]+x}" ]]; then
            echo "${k}=\"${CONFIG_VALUES[$k]}\"" >> "$temp_file"
        fi
    done

    # Atomically replace config file
    mv "$temp_file" "$CONFIG_FILE"
    chmod 600 "$CONFIG_FILE"

    log_message "Configuration saved: ${key}=${value}"
}

# Get configuration value
# Returns default value if key not found (safe under set -e)
get_config() {
    local key="$1"
    local default_value="${2:-}"

    # First check in-memory config (faster, always up-to-date)
    # Use ${var+x} pattern to check if key exists in associative array
    if [[ -n "${CONFIG_VALUES[$key]+x}" ]]; then
        echo "${CONFIG_VALUES[$key]}"
        return 0
    fi

    # Fall back to reading from file if not in memory
    if [[ -f "$CONFIG_FILE" ]]; then
        local value=""
        while IFS= read -r line || [[ -n "$line" ]]; do
            if [[ "$line" =~ ^${key}=(.*)$ ]]; then
                value="${BASH_REMATCH[1]}"
                # Remove surrounding quotes
                if [[ "$value" =~ ^\"(.*)\"$ ]]; then
                    value="${BASH_REMATCH[1]}"
                elif [[ "$value" =~ ^\'(.*)\'$ ]]; then
                    value="${BASH_REMATCH[1]}"
                fi
                echo "$value"
                return 0
            fi
        done < "$CONFIG_FILE"
    fi

    echo "$default_value"
}

# Show current configuration
show_config() {
    print_header "Current Configuration"

    if [[ ! -f "$CONFIG_FILE" ]]; then
        print_info "No configuration file found at: ${CONFIG_FILE}"
        print_info "Configuration will be created when you save settings."
        return 0
    fi

    print_info "Configuration file: ${CONFIG_FILE}"
    echo ""

    local default_model
    local planning_model
    local implementation_model
    local default_jira_project
    local auto_open_files
    local preferred_editor
    local skip_clarification
    local squash_at_end

    default_model=$(get_config "DEFAULT_MODEL" "")
    planning_model=$(get_config "PLANNING_MODEL" "")
    implementation_model=$(get_config "IMPLEMENTATION_MODEL" "")
    default_jira_project=$(get_config "DEFAULT_JIRA_PROJECT" "")
    auto_open_files=$(get_config "AUTO_OPEN_FILES" "true")
    preferred_editor=$(get_config "PREFERRED_EDITOR" "")
    skip_clarification=$(get_config "SKIP_CLARIFICATION" "false")
    squash_at_end=$(get_config "SQUASH_AT_END" "true")

    if [[ -n "$default_model" ]]; then
        echo "  Default Model (Legacy): ${default_model}"
    else
        echo "  Default Model (Legacy): (not set)"
    fi

    if [[ -n "$planning_model" ]]; then
        echo "  Planning Model: ${planning_model}"
    else
        echo "  Planning Model: (not set)"
    fi

    if [[ -n "$implementation_model" ]]; then
        echo "  Implementation Model: ${implementation_model}"
    else
        echo "  Implementation Model: (not set)"
    fi

    if [[ -n "$default_jira_project" ]]; then
        echo "  Default Jira Project: ${default_jira_project}"
    else
        echo "  Default Jira Project: (not set)"
    fi

    echo "  Auto-open Files: ${auto_open_files}"

    if [[ -n "$preferred_editor" ]]; then
        echo "  Preferred Editor: ${preferred_editor}"
    else
        echo "  Preferred Editor: (auto-detect)"
    fi

    echo "  Skip Clarification: ${skip_clarification}"
    echo "  Squash Commits at End: ${squash_at_end}"

    echo ""
}

# Configure settings interactively
configure_settings() {
    print_header "Configuration Settings"

    show_config

    if prompt_confirm "Would you like to update configuration?"; then
        # Configure default model (legacy)
        if prompt_confirm "Set default AI model (legacy - applies to both planning and implementation)?"; then
            local model_name
            prompt_input "Enter default model name (or press Enter to clear)" model_name ""
            if [[ -n "$model_name" ]]; then
                save_config "DEFAULT_MODEL" "$model_name"
                print_success "Default model set to: ${model_name}"
            else
                save_config "DEFAULT_MODEL" ""
                print_info "Default model cleared"
            fi
        fi

        # Configure planning model
        if prompt_confirm "Set planning model (for Steps 1-2: Discovery & Planning)?"; then
            local model_name
            prompt_input "Enter planning model name (or press Enter to clear)" model_name ""
            if [[ -n "$model_name" ]]; then
                save_config "PLANNING_MODEL" "$model_name"
                print_success "Planning model set to: ${model_name}"
            else
                save_config "PLANNING_MODEL" ""
                print_info "Planning model cleared"
            fi
        fi

        # Configure implementation model
        if prompt_confirm "Set implementation model (for Step 3: Execution)?"; then
            local model_name
            prompt_input "Enter implementation model name (or press Enter to clear)" model_name ""
            if [[ -n "$model_name" ]]; then
                save_config "IMPLEMENTATION_MODEL" "$model_name"
                print_success "Implementation model set to: ${model_name}"
            else
                save_config "IMPLEMENTATION_MODEL" ""
                print_info "Implementation model cleared"
            fi
        fi

        # Configure default Jira project
        if prompt_confirm "Set default Jira project?"; then
            local project_key
            prompt_input "Enter default Jira project key (or press Enter to clear)" project_key ""
            if [[ -n "$project_key" ]]; then
                save_config "DEFAULT_JIRA_PROJECT" "$project_key"
                print_success "Default Jira project set to: ${project_key}"
            else
                save_config "DEFAULT_JIRA_PROJECT" ""
                print_info "Default Jira project cleared"
            fi
        fi

        # Configure auto-open files
        if prompt_confirm "Configure auto-open files setting?"; then
            local auto_open
            prompt_input "Auto-open files in editor? (true/false)" auto_open "true"
            save_config "AUTO_OPEN_FILES" "$auto_open"
            print_success "Auto-open files set to: ${auto_open}"
        fi

        # Configure preferred editor
        if prompt_confirm "Set preferred editor?"; then
            local editor
            prompt_input "Enter preferred editor command (or press Enter to auto-detect)" editor ""
            if [[ -n "$editor" ]]; then
                save_config "PREFERRED_EDITOR" "$editor"
                print_success "Preferred editor set to: ${editor}"
            else
                save_config "PREFERRED_EDITOR" ""
                print_info "Preferred editor cleared (will auto-detect)"
            fi
        fi

        # Configure skip clarification
        if prompt_confirm "Configure skip clarification setting?"; then
            local skip_clarif
            prompt_input "Skip clarification step by default? (true/false)" skip_clarif "false"
            save_config "SKIP_CLARIFICATION" "$skip_clarif"
            print_success "Skip clarification set to: ${skip_clarif}"
        fi

        # Configure squash at end
        if prompt_confirm "Configure squash commits at end setting?"; then
            local squash_setting
            prompt_input "Squash checkpoint commits at end? (true/false)" squash_setting "true"
            save_config "SQUASH_AT_END" "$squash_setting"
            print_success "Squash at end set to: ${squash_setting}"
        fi

        echo ""
        show_config
    fi
}

################################################################################
# Logging Functions
################################################################################

# Log a message to the log file
log_message() {
    if [[ "$LOG_ENABLED" == "true" ]]; then
        local timestamp
        timestamp=$(date '+%Y-%m-%d %H:%M:%S')
        echo "[${timestamp}] $*" >> "$LOG_FILE"
    fi
}

# Log command execution
log_command() {
    local command="$1"
    local exit_code="${2:-0}"
    log_message "COMMAND: ${command} | EXIT_CODE: ${exit_code}"
}

################################################################################
# Utility Functions
################################################################################

# Print colored messages
print_error() {
    echo -e "${COLOR_RED}${COLOR_BOLD}[ERROR]${COLOR_RESET} ${COLOR_RED}$1${COLOR_RESET}" >&2
    log_message "ERROR: $1"
}

print_success() {
    echo -e "${COLOR_GREEN}${COLOR_BOLD}[SUCCESS]${COLOR_RESET} ${COLOR_GREEN}$1${COLOR_RESET}"
    log_message "SUCCESS: $1"
}

print_warning() {
    echo -e "${COLOR_YELLOW}${COLOR_BOLD}[WARNING]${COLOR_RESET} ${COLOR_YELLOW}$1${COLOR_RESET}"
    log_message "WARNING: $1"
}

print_info() {
    echo -e "${COLOR_BLUE}${COLOR_BOLD}[INFO]${COLOR_RESET} ${COLOR_CYAN}$1${COLOR_RESET}"
    log_message "INFO: $1"
}

print_header() {
    echo -e "\n${COLOR_MAGENTA}${COLOR_BOLD}=== $1 ===${COLOR_RESET}\n"
}

print_step() {
    echo -e "${COLOR_CYAN}${COLOR_BOLD}➜${COLOR_RESET} $1"
}

# Prompt user for yes/no confirmation
prompt_confirm() {
    local prompt_message="$1"
    local response

    while true; do
        echo -e -n "${COLOR_YELLOW}${prompt_message} [y/n]: ${COLOR_RESET}"
        read -r response
        case "$response" in
            [yY]|[yY][eE][sS])
                return 0
                ;;
            [nN]|[nN][oO])
                return 1
                ;;
            *)
                print_warning "Please answer yes (y) or no (n)."
                ;;
        esac
    done
}

# Prompt user to press Enter to continue (no y/n semantics)
# Use this for "Press Enter to return" style prompts
prompt_enter() {
    local prompt_message="${1:-Press Enter to continue}"
    echo -e -n "${COLOR_CYAN}${prompt_message}... ${COLOR_RESET}"
    read -r
}

# Prompt user for input
# SECURITY: Uses printf -v instead of eval to avoid RCE risk from user input
# The variable name is validated to contain only safe characters
prompt_input() {
    local prompt_message="$1"
    local input_var="$2"
    local default_value="${3:-}"

    # Validate variable name to prevent injection (only allow alphanumeric and underscore)
    if [[ ! "$input_var" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]]; then
        print_error "Invalid variable name: ${input_var}"
        return 1
    fi

    if [[ -n "$default_value" ]]; then
        echo -e -n "${COLOR_CYAN}${prompt_message} [${default_value}]: ${COLOR_RESET}"
    else
        echo -e -n "${COLOR_CYAN}${prompt_message}: ${COLOR_RESET}"
    fi

    local user_input
    read -r user_input

    # Use printf -v for safe variable assignment (no eval/code execution)
    if [[ -z "$user_input" && -n "$default_value" ]]; then
        printf -v "$input_var" '%s' "$default_value"
    else
        printf -v "$input_var" '%s' "$user_input"
    fi
}

################################################################################
# Error Handling & Cleanup
################################################################################

# Array to track background process PIDs for cleanup
declare -a BACKGROUND_PIDS=()

# Register a background PID for cleanup tracking
register_background_pid() {
    local pid="$1"
    BACKGROUND_PIDS+=("$pid")
}

# Unregister a background PID (when process completes normally)
unregister_background_pid() {
    local pid="$1"
    local new_pids=()
    for p in "${BACKGROUND_PIDS[@]:-}"; do
        if [[ "$p" != "$pid" ]]; then
            new_pids+=("$p")
        fi
    done
    BACKGROUND_PIDS=("${new_pids[@]:-}")
}

# Central cleanup function - kills all tracked background processes
# Called on script exit, error, or interrupt
cleanup() {
    local exit_code="${1:-0}"

    # Kill all tracked background processes
    for pid in "${BACKGROUND_PIDS[@]:-}"; do
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi
    done
    BACKGROUND_PIDS=()

    # Restore terminal settings if needed (e.g., if echo was disabled)
    stty echo 2>/dev/null || true

    # Clear any progress line artifacts
    echo -ne "\r\033[K" 2>/dev/null || true
}

# Trap handler for errors
error_handler() {
    local line_number=$1
    local exit_code=$?

    # Run cleanup first
    cleanup "$exit_code"

    print_error "Script failed at line ${line_number} with exit code ${exit_code}"

    # Provide context-specific recovery suggestions
    case $exit_code in
        2)
            print_info "Recovery: Install Auggie CLI and try again"
            ;;
        3)
            print_info "Recovery: Configure Jira integration in Auggie"
            ;;
        5)
            print_info "Recovery: Check git status and resolve any conflicts"
            ;;
        *)
            print_info "Recovery: Check the error message above and try again"
            ;;
    esac

    exit 1
}

# Trap handler for interrupts
interrupt_handler() {
    # Run cleanup first
    cleanup 4

    print_warning "\nScript interrupted by user"

    # Check for uncommitted changes
    if git rev-parse --git-dir > /dev/null 2>&1; then
        if ! git diff --quiet 2>/dev/null; then
            print_warning "You have uncommitted changes"
            print_info "Run 'git status' to see changes"
            print_info "Run 'git restore .' to discard changes"
        fi
    fi

    exit 4
}

# Exit handler - ensures cleanup runs on normal exit
exit_handler() {
    cleanup 0
}

# Set up trap handlers
# EXIT: always run cleanup on script exit (normal or abnormal)
# ERR: handle errors with context-specific messages
# INT/TERM: handle user interrupts gracefully
trap exit_handler EXIT
trap 'error_handler ${LINENO}' ERR
trap interrupt_handler INT TERM

################################################################################
# Auggie CLI Functions
################################################################################

# Portable semver comparison function
# Returns 0 if version1 >= version2, 1 otherwise
# Handles versions like "1.2.3", "1.2", "1"
# Does not rely on sort -V which is not available on macOS
version_gte() {
    local version1="$1"
    local version2="$2"

    # Split versions into arrays
    local IFS='.'
    read -ra v1_parts <<< "$version1"
    read -ra v2_parts <<< "$version2"

    # Pad arrays to same length with zeros
    local max_len=${#v1_parts[@]}
    [[ ${#v2_parts[@]} -gt $max_len ]] && max_len=${#v2_parts[@]}

    for ((i=0; i<max_len; i++)); do
        local p1="${v1_parts[i]:-0}"
        local p2="${v2_parts[i]:-0}"

        # Remove any non-numeric suffix (e.g., "1.2.3-beta" -> "1.2.3")
        p1="${p1%%[^0-9]*}"
        p2="${p2%%[^0-9]*}"

        # Default to 0 if empty
        p1="${p1:-0}"
        p2="${p2:-0}"

        if [[ $p1 -gt $p2 ]]; then
            return 0  # version1 > version2
        elif [[ $p1 -lt $p2 ]]; then
            return 1  # version1 < version2
        fi
    done

    return 0  # versions are equal
}

# Check if Auggie CLI is installed and meets version requirements
check_auggie_installed() {
    print_step "Checking for Auggie CLI installation..."

    # Check if auggie command exists
    if ! command -v auggie &> /dev/null; then
        print_warning "Auggie CLI is not installed"
        return 1
    fi

    # Check version
    local auggie_version
    auggie_version=$(auggie --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "0.0.0")

    print_info "Found Auggie CLI version: ${auggie_version}"

    # Portable version comparison (does not use sort -V)
    local required_version="${REQUIRED_AUGGIE_VERSION}"
    if ! version_gte "$auggie_version" "$required_version"; then
        print_warning "Auggie CLI version ${auggie_version} is older than required version ${required_version}"
        return 2
    fi

    print_success "Auggie CLI is installed and meets version requirements"
    return 0
}

# Install Auggie CLI
install_auggie() {
    print_header "Installing Auggie CLI"

    # Check Node.js version
    print_step "Checking Node.js version..."
    if ! command -v node &> /dev/null; then
        print_error "Node.js is not installed. Please install Node.js ${REQUIRED_NODE_VERSION}+ first."
        print_info "Visit: https://nodejs.org/"
        return 1
    fi

    local node_version
    node_version=$(node --version | grep -oE '[0-9]+' | head -1)

    if [[ $node_version -lt $REQUIRED_NODE_VERSION ]]; then
        print_error "Node.js version ${node_version} is too old. Required: ${REQUIRED_NODE_VERSION}+"
        print_info "Please upgrade Node.js: https://nodejs.org/"
        return 1
    fi

    print_success "Node.js version ${node_version} meets requirements"

    # Install Auggie CLI
    print_step "Installing Auggie CLI via npm..."
    if ! npm install -g @augmentcode/auggie; then
        print_error "Failed to install Auggie CLI"
        return 1
    fi

    print_success "Auggie CLI installed successfully"

    # Guide user through login
    print_header "Auggie CLI Login"
    print_info "You need to log in to Auggie CLI to use this script."
    print_info "This will open a browser window for authentication."

    if prompt_confirm "Would you like to log in now?"; then
        print_step "Running 'auggie login'..."
        if ! auggie login; then
            print_error "Failed to log in to Auggie CLI"
            return 1
        fi
        print_success "Successfully logged in to Auggie CLI"
    else
        print_warning "Skipping login. You can run 'auggie login' manually later."
        return 0
    fi

    # Verify installation
    print_step "Verifying installation..."
    if check_auggie_installed; then
        print_success "Auggie CLI is ready to use!"
        return 0
    else
        print_error "Installation verification failed"
        return 1
    fi
}

################################################################################
# Jira Integration Functions
################################################################################

# Check if Jira integration is configured in Auggie
check_jira_integration() {
    print_step "Checking Jira integration..."
    log_message "Jira integration check started"

    # Initialize current_time at the start - used for cache timestamp in all code paths
    local current_time
    current_time=$(date +%s)

    # Check if we have a cached result (unless force check is requested)
    if [[ "$FORCE_JIRA_CHECK" != "true" ]]; then
        local jira_check_timestamp
        jira_check_timestamp=$(get_config "JIRA_CHECK_TIMESTAMP" "0")
        local cache_duration=$((24 * 60 * 60))  # 24 hours in seconds

        # If we have a recent successful check, skip the verification
        if [[ $((current_time - jira_check_timestamp)) -lt $cache_duration ]]; then
            local jira_status
            jira_status=$(get_config "JIRA_INTEGRATION_STATUS" "")
            if [[ "$jira_status" == "working" ]]; then
                print_success "Jira integration is configured (cached - checked $(((current_time - jira_check_timestamp) / 3600)) hours ago)"
                log_message "Jira integration: using cached result (working)"
                return 0
            fi
        fi
    else
        print_info "Forcing fresh Jira integration check..."
        log_message "Jira integration: forcing fresh check"
    fi

    # Perform actual check (simplified and faster)
    print_info "Verifying Jira integration (this may take a moment)..."

    # Create a temporary file for the test output
    local temp_output
    temp_output=$(mktemp)

    # Try a simpler check - just verify Jira tool is available
    # This is much faster than listing all issues
    if auggie --print --quiet "Check if Jira integration is available. Respond with 'YES' if you can access Jira, 'NO' otherwise." > "$temp_output" 2>&1; then
        local output_content
        output_content=$(cat "$temp_output")

        # Check if the output contains error messages indicating Jira is not configured
        if echo "$output_content" | grep -qi "jira.*not.*configured\|jira.*not.*available\|cannot.*access.*jira\|jira.*integration.*failed"; then
            rm -f "$temp_output"
            save_config "JIRA_INTEGRATION_STATUS" "not_configured"
            save_config "JIRA_CHECK_TIMESTAMP" "$current_time"
            print_warning "Jira integration is not configured"
            log_message "Jira integration: not configured"
            return 1
        fi

        # Check if we got a positive response
        if echo "$output_content" | grep -qiE "yes|available|configured|working"; then
            rm -f "$temp_output"
            save_config "JIRA_INTEGRATION_STATUS" "working"
            save_config "JIRA_CHECK_TIMESTAMP" "$current_time"
            print_success "Jira integration is configured and working"
            log_message "Jira integration: working"
            return 0
        fi
    fi

    rm -f "$temp_output"
    save_config "JIRA_INTEGRATION_STATUS" "unknown"
    save_config "JIRA_CHECK_TIMESTAMP" "$current_time"
    print_warning "Unable to verify Jira integration"
    log_message "Jira integration: unknown/failed"
    return 1
}

# Provide instructions for setting up Jira integration
show_jira_setup_instructions() {
    print_header "Jira Integration Setup"
    print_info "To use Jira-dependent features, you need to configure Jira integration in Auggie."
    echo ""
    print_step "Setup Instructions:"
    echo "  1. Ensure you have Jira MCP server configured"
    echo "  2. Check your Auggie configuration for Jira settings"
    echo "  3. Verify your Jira API token is set correctly"
    echo "  4. Test the connection by running: auggie --print 'List my Jira issues'"
    echo ""
    print_info "For more information, visit: https://docs.augmentcode.com/"
}

################################################################################
# Model Selection Functions
################################################################################

# Global variables to store selected models
SELECTED_MODEL=""
PLANNING_MODEL=""
IMPLEMENTATION_MODEL=""

# Select model for a specific phase (planning or implementation)
# SECURITY: Uses printf -v instead of eval to avoid RCE risk
select_model_for_phase() {
    local phase="$1"  # "planning" or "implementation"
    local model_var="$2"  # Variable name to store result
    local phase_display="$3"  # Display name for the phase

    # Validate variable name to prevent injection
    if [[ ! "$model_var" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]]; then
        print_error "Invalid variable name: ${model_var}"
        return 1
    fi

    print_step "Selecting AI model for ${phase_display}..."

    # Check for preset model from CLI flag
    if [[ -n "$PRESET_MODEL" ]]; then
        printf -v "$model_var" '%s' "$PRESET_MODEL"
        print_info "Using preset model from CLI flag: ${PRESET_MODEL}"
        return 0
    fi

    # Check for phase-specific model in config
    local config_key="$(echo "${phase}" | tr '[:lower:]' '[:upper:]')_MODEL"  # Convert to uppercase
    local phase_model
    phase_model=$(get_config "$config_key" "")

    if [[ -n "$phase_model" ]]; then
        print_info "${phase_display} model from config: ${phase_model}"
        if prompt_confirm "Use ${phase_display} model from config?"; then
            printf -v "$model_var" '%s' "$phase_model"
            print_success "Using model: ${phase_model}"
            return 0
        fi
    fi

    # Fall back to default model in config
    local default_model
    default_model=$(get_config "DEFAULT_MODEL" "")

    if [[ -n "$default_model" ]]; then
        print_info "Default model from config: ${default_model}"
        if prompt_confirm "Use default model from config?"; then
            printf -v "$model_var" '%s' "$default_model"
            print_success "Using model: ${default_model}"
            return 0
        fi
    fi

    # Try to get model list from Auggie (try both 'models list' and 'model list')
    local models_output
    if models_output=$(auggie models list 2>&1); then
        :  # Command succeeded
    elif models_output=$(auggie model list 2>&1); then
        :  # Fallback command succeeded
    else
        print_warning "Could not retrieve model list from Auggie CLI"
        print_info "You can still proceed with the default model."
        return 0
    fi

    print_info "Available models:"
    echo "$models_output"
    echo ""

    # Ask user if they want to select a specific model
    if prompt_confirm "Would you like to select a specific model for ${phase_display}?"; then
        # Parse models into arrays
        local -a model_names=()
        local -a model_ids=()
        local -a model_descriptions=()

        # Parse the model list output - more robust regex
        while IFS= read -r line; do
            # Skip empty lines
            [[ -z "$line" ]] && continue

            # Match lines like: " - Haiku 4.5 [haiku4.5]" or "- Model Name [model-id]"
            if [[ "$line" =~ ^[[:space:]]*[-*][[:space:]]+(.+)[[:space:]]+\[([^\]]+)\][[:space:]]*$ ]]; then
                model_names+=("${BASH_REMATCH[1]}")
                model_ids+=("${BASH_REMATCH[2]}")
                # Try to get description from next line
                read -r desc_line
                if [[ "$desc_line" =~ ^[[:space:]]+(.+)$ ]]; then
                    model_descriptions+=("${BASH_REMATCH[1]}")
                else
                    model_descriptions+=("")
                fi
            fi
        done <<< "$models_output"

        # Display numbered menu or fallback to manual entry
        if [[ ${#model_names[@]} -gt 0 ]]; then
                echo ""
                echo "Select a model for ${phase_display}:"
                echo ""
                for i in "${!model_names[@]}"; do
                    local num=$((i + 1))
                    echo -e "  ${COLOR_BOLD}${num}.${COLOR_RESET} ${model_names[$i]} [${model_ids[$i]}]"
                    if [[ -n "${model_descriptions[$i]}" ]]; then
                        echo "     ${model_descriptions[$i]}"
                    fi
                done
                echo -e "  ${COLOR_BOLD}$((${#model_names[@]} + 1)).${COLOR_RESET} Use default model"
                echo ""

                local choice
                prompt_input "Enter your choice (1-$((${#model_names[@]} + 1)))" choice ""

                if [[ "$choice" =~ ^[0-9]+$ ]] && [[ $choice -ge 1 ]] && [[ $choice -le ${#model_names[@]} ]]; then
                    local selected_index=$((choice - 1))
                    local selected_model="${model_ids[$selected_index]}"
                    printf -v "$model_var" '%s' "$selected_model"
                    print_success "Selected model: ${model_names[$selected_index]} [${selected_model}]"

                    # Ask if they want to save as default for this phase
                    if prompt_confirm "Save this as default ${phase_display} model?"; then
                        save_config "$config_key" "$selected_model"
                        print_success "Saved as default ${phase_display} model"
                    fi
                elif [[ "$choice" == "$((${#model_names[@]} + 1))" ]]; then
                    print_info "Using default model"
                else
                    print_warning "Invalid choice. Using default model."
                fi
        else
            print_warning "Could not parse model list"
            # Fallback: offer manual entry
            if prompt_confirm "Enter model name manually?"; then
                local manual_model
                prompt_input "Model name" manual_model ""
                if [[ -n "$manual_model" ]]; then
                    printf -v "$model_var" '%s' "$manual_model"
                    print_success "Using model: ${manual_model}"

                    # Ask if they want to save as default for this phase
                    if prompt_confirm "Save this as default ${phase_display} model?"; then
                        save_config "$config_key" "$manual_model"
                        print_success "Saved as default ${phase_display} model"
                    fi
                else
                    print_info "No model specified. Using default model."
                fi
            else
                print_info "Using default model"
            fi
        fi
    else
        print_info "Using default model"
    fi
}

# Get model flag for Auggie commands
get_model_flag() {
    if [[ -n "$SELECTED_MODEL" ]]; then
        echo "--model ${SELECTED_MODEL}"
    else
        echo ""
    fi
}

# Run auggie command with proper model handling
# Usage: run_auggie [--dont-save-session] [--phase planning|implementation] <auggie args...>
run_auggie() {
    local -a args=()
    local model_to_use=""
    local dont_save_session=false

    # Parse our custom flags (order-independent)
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dont-save-session)
                dont_save_session=true
                shift
                ;;
            --phase)
                local phase="$2"
                shift 2
                # Select model based on phase
                if [[ "$phase" == "planning" ]]; then
                    model_to_use="$PLANNING_MODEL"
                elif [[ "$phase" == "implementation" ]]; then
                    model_to_use="$IMPLEMENTATION_MODEL"
                fi
                ;;
            *)
                # Remaining args are passed to auggie
                break
                ;;
        esac
    done

    # Fall back to SELECTED_MODEL if no phase-specific model
    if [[ -z "$model_to_use" ]]; then
        model_to_use="$SELECTED_MODEL"
    fi

    # Build args array with remaining arguments
    args=("$@")

    # Build the auggie command
    local -a auggie_cmd=(auggie)

    if [[ -n "$model_to_use" ]]; then
        auggie_cmd+=(--model "${model_to_use}")
    fi

    if [[ "$dont_save_session" == "true" ]]; then
        auggie_cmd+=(--dont-save-session)
    fi

    # Execute auggie with all arguments
    "${auggie_cmd[@]}" "${args[@]}"
}

################################################################################
# Menu Functions
################################################################################

# Display ASCII banner
show_banner() {
    echo -e "${COLOR_MAGENTA}${COLOR_BOLD}"
    cat << "EOF"
    ___    ____   _       __           __   ______
   /   |  /  _/  | |     / /___  _____/ /__/ __/ /___ _      __
  / /| |  / /    | | /| / / __ \/ ___/ //_/ /_/ / __ \ | /| / /
 / ___ |_/ /     | |/ |/ / /_/ / /  / ,< / __/ / /_/ / |/ |/ /
/_/  |_/___/     |__/|__/\____/_/  /_/|_/_/ /_/\____/|__/|__/

EOF
    echo -e "${COLOR_RESET}"
    echo -e "${COLOR_CYAN}${COLOR_BOLD}AI-Assisted Development Workflow${COLOR_RESET}"
    echo -e "${COLOR_WHITE}Version ${SCRIPT_VERSION}${COLOR_RESET}"
    echo ""
}

# Show main menu and get user selection
show_main_menu() {
    while true; do
        print_header "Main Menu"
        echo "Please select an action:"
        echo ""
        echo -e "  ${COLOR_BOLD}1.${COLOR_RESET} Automated code review on PRs ${COLOR_YELLOW}[Coming Soon]${COLOR_RESET}"
        echo -e "  ${COLOR_BOLD}2.${COLOR_RESET} Develop new branch via Jira ticket (Spec-Driven Development)"
        echo -e "  ${COLOR_BOLD}3.${COLOR_RESET} Configuration Settings"
        echo -e "  ${COLOR_BOLD}4.${COLOR_RESET} Exit"
        echo ""

        local choice
        prompt_input "Enter your choice (1-4)" choice ""

        case "$choice" in
            1)
                action_code_review
                ;;
            2)
                action_spec_driven_dev
                return 0
                ;;
            3)
                configure_settings
                ;;
            4)
                print_info "Exiting..."
                exit 0
                ;;
            *)
                print_error "Invalid choice. Please enter 1, 2, 3, or 4."
                echo ""
                ;;
        esac
    done
}

################################################################################
# Action Functions
################################################################################

# Action 1: Code Review (placeholder)
action_code_review() {
    print_header "Automated Code Review"
    print_warning "This feature is coming soon!"
    print_info "This will analyze PRs and provide automated code review feedback."
    echo ""
    prompt_enter "Press Enter to return to main menu"
}

# Action 2: Spec-Driven Development
action_spec_driven_dev() {
    print_header "Spec-Driven Development Workflow"
    print_info "This workflow will help you develop a new feature from a Jira ticket."
    print_info "It follows a 3-step process:"
    echo -e "  ${COLOR_BOLD}Step 1:${COLOR_RESET} Create implementation plan (Discovery)"
    echo -e "  ${COLOR_BOLD}Step 2:${COLOR_RESET} Convert plan to task list (Planning)"
    echo -e "  ${COLOR_BOLD}Step 3:${COLOR_RESET} Execute tasks with clean context (Execution)"
    echo ""

    # Check Jira integration
    if ! check_jira_integration; then
        show_jira_setup_instructions
        if ! prompt_confirm "Do you want to continue anyway?"; then
            print_info "Returning to main menu..."
            return 0
        fi
    fi

    # Offer model selection for planning and implementation
    if [[ -z "$PRESET_MODEL" ]]; then
        if prompt_confirm "Would you like to select AI models for this workflow?"; then
            echo ""
            print_info "You can select different models for planning and implementation phases."
            echo ""

            # Select planning model
            if prompt_confirm "Select model for Planning (Steps 1-2: Discovery & Planning)?"; then
                select_model_for_phase "planning" "PLANNING_MODEL" "Planning"
            fi

            echo ""

            # Select implementation model
            if prompt_confirm "Select model for Implementation (Step 3: Execution)?"; then
                select_model_for_phase "implementation" "IMPLEMENTATION_MODEL" "Implementation"
            fi

            echo ""
        fi
    elif [[ -n "$PRESET_MODEL" ]]; then
        # Use preset model for both phases
        PLANNING_MODEL="$PRESET_MODEL"
        IMPLEMENTATION_MODEL="$PRESET_MODEL"
        print_info "Using preset model for all phases: ${PRESET_MODEL}"
    fi

    # Execute the 3-step workflow
    step_1_create_plan
    step_2_create_tasklist
    step_3_execute_clean_loop

    print_success "Spec-Driven Development workflow completed!"
}

################################################################################
# Enhanced Workflow Helper Functions
################################################################################

# Open file in user's preferred editor
open_file_in_editor() {
    local file_path="$1"

    # Check if auto-open is disabled
    if [[ "$NO_OPEN" == "true" ]]; then
        print_info "Auto-open disabled. File location: ${file_path}"
        return 0
    fi

    # Check config for auto-open setting
    local auto_open_files
    auto_open_files=$(get_config "AUTO_OPEN_FILES" "true")
    if [[ "$auto_open_files" == "false" ]]; then
        print_info "Auto-open disabled in config. File location: ${file_path}"
        return 0
    fi

    # Determine editor
    local editor=""
    local preferred_editor
    preferred_editor=$(get_config "PREFERRED_EDITOR" "")

    if [[ -n "${EDITOR:-}" ]]; then
        editor="$EDITOR"
    elif [[ -n "${VISUAL:-}" ]]; then
        editor="$VISUAL"
    elif [[ -n "$preferred_editor" ]]; then
        editor="$preferred_editor"
    elif command -v idea &> /dev/null; then
        editor="idea"
    elif command -v open &> /dev/null && [[ "$OSTYPE" == "darwin"* ]]; then
        # On macOS, use 'open' which will use the default app (TextEdit for .md files)
        editor="open"
    elif command -v code &> /dev/null; then
        editor="code"
    elif command -v vim &> /dev/null; then
        editor="vim"
    elif command -v nano &> /dev/null; then
        editor="nano"
    elif command -v less &> /dev/null; then
        editor="less"
    else
        editor="cat"
    fi

    print_info "Opening file in ${editor}..."

    # Open file (non-blocking for GUI editors)
    if [[ "$editor" == "code" || "$editor" == "idea" || "$editor" == "open" ]]; then
        "$editor" "$file_path" &
    elif [[ "$editor" == "cat" ]]; then
        cat "$file_path"
    else
        "$editor" "$file_path" || true
    fi

    return 0
}

# Show progress spinner for long operations
show_progress_spinner() {
    local message="$1"
    local pid="$2"  # PID of background process to monitor

    local spinner_chars="⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    local start_time=$(date +%s)

    while kill -0 "$pid" 2>/dev/null; do
        for (( i=0; i<${#spinner_chars}; i++ )); do
            if ! kill -0 "$pid" 2>/dev/null; then
                break
            fi

            local char="${spinner_chars:$i:1}"
            local elapsed=$(($(date +%s) - start_time))

            if [[ $elapsed -gt 10 ]]; then
                echo -ne "\r${char} ${message} (${elapsed}s elapsed)  "
            else
                echo -ne "\r${char} ${message}  "
            fi

            sleep 0.1
        done
    done

    echo -ne "\r✓ ${message} - Complete!          \n"
}

# Parse task list from markdown file
# Supports flexible markdown checkbox formats:
#   - [ ] Task (dash with space checkbox)
#   * [ ] Task (asterisk with space checkbox)
#   - [x] Task (completed with lowercase x)
#   - [X] Task (completed with uppercase X)
#   Flexible whitespace between bullet and checkbox
parse_task_list() {
    local task_list_file="$1"
    local -n task_array="$2"  # nameref to output array

    if [[ ! -f "$task_list_file" ]]; then
        return 1
    fi

    # Extract lines with markdown checkbox format
    # Pattern: optional leading whitespace, bullet (- or *), whitespace, checkbox, whitespace, task text
    while IFS= read -r line; do
        # Match: [whitespace][-|*][whitespace][[space|x|X]][whitespace][task text]
        if [[ "$line" =~ ^[[:space:]]*[-\*][[:space:]]+\[([[:space:]]|[xX])\][[:space:]]+(.+)$ ]]; then
            local status="${BASH_REMATCH[1]}"
            local task_name="${BASH_REMATCH[2]}"

            # Skip completed tasks (x or X)
            if [[ "$status" != "x" && "$status" != "X" ]]; then
                task_array+=("$task_name")
            fi
        fi
    done < "$task_list_file"

    return 0
}

# Mark task as complete in task list file
# Uses portable line-by-line approach instead of GNU sed extensions
mark_task_complete() {
    local task_list_file="$1"
    local task_name="$2"

    if [[ ! -f "$task_list_file" ]]; then
        return 1
    fi

    local temp_file
    temp_file=$(mktemp)
    local found=false

    # Read file line by line and update first matching unchecked task
    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$found" == "false" ]]; then
            # Check if this line is an unchecked task matching our task name
            # Support both - and * bullets, and flexible whitespace around checkbox
            if [[ "$line" =~ ^([[:space:]]*[-*][[:space:]]+)\[[[:space:]]*\]([[:space:]]+)(.+)$ ]]; then
                local prefix="${BASH_REMATCH[1]}"
                local spacing="${BASH_REMATCH[2]}"
                local line_task_name="${BASH_REMATCH[3]}"

                # Compare task names (exact match)
                if [[ "$line_task_name" == "$task_name" ]]; then
                    # Mark as complete
                    echo "${prefix}[x]${spacing}${line_task_name}" >> "$temp_file"
                    found=true
                    continue
                fi
            fi
        fi
        # Write line unchanged
        echo "$line" >> "$temp_file"
    done < "$task_list_file"

    # Replace original file atomically
    mv "$temp_file" "$task_list_file"

    if [[ "$found" == "true" ]]; then
        return 0
    else
        return 1
    fi
}

# Clarification phase - ask AI to review plan and ask questions
# It is ONLY skipped by explicit controls: --skip-clarification flag or SKIP_CLARIFICATION=true in config.
step_1_5_clarification_phase() {
    local plan_file="$1"

    # Check if clarification should be skipped via CLI flag
    if [[ "$SKIP_CLARIFICATION" == "true" ]]; then
        print_info "Clarification step skipped (--skip-clarification flag)"
        return 0
    fi

    # Check config for skip clarification setting
    local skip_clarification_config
    skip_clarification_config=$(get_config "SKIP_CLARIFICATION" "false")
    if [[ "$skip_clarification_config" == "true" ]]; then
        print_info "Clarification step skipped (config setting)"
        return 0
    fi

    print_header "Step 1.5: Clarification Phase (Optional)"
    print_info "The AI can review the plan and ask clarification questions about:"
    echo "  - Ambiguous requirements"
    echo "  - Missing technical details"
    echo "  - Unclear dependencies or integration points"
    echo "  - Edge cases not covered"
    echo ""

    if ! prompt_confirm "Would you like the AI to review the plan and ask clarification questions?"; then
        print_info "Skipping clarification phase"
        return 0
    fi

    print_step "Starting interactive clarification phase..."
    echo ""
    print_info "${COLOR_BOLD}INSTRUCTIONS:${COLOR_RESET}"
    echo "  1. The AI will review the plan and ask clarification questions"
    echo "  2. Answer each question in the chat"
    echo "  3. The AI will update the plan file with a '## Clarification Q&A' section"
    echo "  4. Type 'done' or press Ctrl+D when you're finished with clarifications"
    echo ""

    local prompt="Review the implementation plan at @${plan_file}.

As an AI assistant, please analyze this plan and identify any:
1. Ambiguous requirements that need clarification
2. Missing technical details or specifications
3. Unclear dependencies or integration points
4. Edge cases or error scenarios not covered
5. Potential risks or challenges

If you find areas needing clarification:
- Ask me clarification questions ONE AT A TIME
- Wait for my answer before asking the next question
- After I've answered all questions, update the plan file with a new section called '## Clarification Q&A' containing our full discussion
- Format the Q&A section clearly with each question and answer pair

If the plan is complete and clear, simply respond with 'No clarifications needed - plan is comprehensive.' and do not modify the file."

    print_step "Running: auggie (interactive mode)"
    if [[ -n "$PLANNING_MODEL" ]]; then
        print_info "Using planning model: ${PLANNING_MODEL}"
    fi
    echo ""
    print_warning "You are now entering an interactive session with the AI."
    print_info "The AI will ask questions and wait for your answers."
    echo ""

    if run_auggie --phase planning "${prompt}"; then
        echo ""
        print_success "Clarification phase completed!"
        echo ""
        print_info "The plan file has been updated with clarification Q&A (if any questions were asked)"
    else
        echo ""
        print_warning "Clarification phase encountered an issue, but continuing..."
    fi

    return 0
}

################################################################################
# Workflow Step Functions
################################################################################

# Global variables for workflow state
TICKET_ID=""
TICKET_URL=""
TICKET_SUMMARY=""
TICKET_FULL_INFO=""
PLAN_FILE=""

# Add file to .gitignore if not already present
add_to_gitignore() {
    local file_pattern="$1"
    local gitignore_file=".gitignore"

    # Create .gitignore if it doesn't exist
    if [[ ! -f "$gitignore_file" ]]; then
        print_step "Creating .gitignore file..."
        touch "$gitignore_file"
    fi

    # Check if pattern already exists in .gitignore
    if grep -qxF "$file_pattern" "$gitignore_file" 2>/dev/null; then
        log_message "Pattern already in .gitignore: ${file_pattern}"
        return 0
    fi

    # Add pattern to .gitignore
    echo "$file_pattern" >> "$gitignore_file"
    print_success "Added to .gitignore: ${file_pattern}"
    log_message "Added to .gitignore: ${file_pattern}"

    return 0
}

# Validate and parse Jira ticket input
# Supports:
#   - Full URLs (https://jira.example.com/browse/PROJECT-123)
#   - Ticket IDs with uppercase/lowercase project keys (PROJECT-123, project-123, Project2-456)
#   - Numeric-only input when DEFAULT_JIRA_PROJECT is configured (123 -> PROJECT-123)
# All project keys are normalized to uppercase
parse_jira_ticket() {
    local input="$1"

    # Check if input is a URL
    if [[ "$input" =~ ^https?:// ]]; then
        TICKET_URL="$input"
        # Extract ticket ID from URL - support alphanumeric project keys (case-insensitive)
        if [[ "$input" =~ ([a-zA-Z][a-zA-Z0-9]*-[0-9]+) ]]; then
            # Normalize to uppercase
            TICKET_ID=$(echo "${BASH_REMATCH[1]}" | tr '[:lower:]' '[:upper:]')
        else
            print_error "Could not extract ticket ID from URL"
            return 1
        fi
    # Check if input is just a number (use DEFAULT_JIRA_PROJECT)
    elif [[ "$input" =~ ^[0-9]+$ ]]; then
        local default_project
        default_project=$(get_config "DEFAULT_JIRA_PROJECT" "")
        if [[ -z "$default_project" ]]; then
            print_error "Numeric ticket ID requires DEFAULT_JIRA_PROJECT to be configured"
            print_info "Configure it via: Configuration Settings > Set default Jira project"
            return 1
        fi
        # Normalize project key to uppercase
        default_project=$(echo "$default_project" | tr '[:lower:]' '[:upper:]')
        TICKET_ID="${default_project}-${input}"
        TICKET_URL="$TICKET_ID"
        print_info "Using default project: ${default_project}"
    # Check if input is a ticket ID (e.g., PROJECT-123, project2-456)
    # Project key: starts with letter, followed by letters/digits
    elif [[ "$input" =~ ^[a-zA-Z][a-zA-Z0-9]*-[0-9]+$ ]]; then
        # Normalize to uppercase
        TICKET_ID=$(echo "$input" | tr '[:lower:]' '[:upper:]')
        TICKET_URL="$TICKET_ID"  # Auggie can handle ticket IDs directly
    else
        print_error "Invalid ticket format. Expected: PROJECT-123, 123 (with DEFAULT_JIRA_PROJECT), or full Jira URL"
        return 1
    fi

    print_success "Ticket ID: ${TICKET_ID}"
    return 0
}

# Fetch and cache ticket information from Jira
fetch_ticket_info() {
    print_step "Fetching ticket information from Jira..."

    # Create a temporary file for the ticket info
    local temp_output
    temp_output=$(mktemp)

    # Fetch comprehensive ticket information in one call
    local info_prompt="Read Jira ticket ${TICKET_URL} and provide:
1. A short 3-5 word summary suitable for a git branch name (lowercase with hyphens, e.g., 'add-user-authentication')
2. The full ticket title
3. A brief description (2-3 sentences)

Format your response as:
BRANCH_SUMMARY: <summary>
TITLE: <title>
DESCRIPTION: <description>"

    if run_auggie --phase planning --print --quiet "${info_prompt}" > "$temp_output" 2>&1; then
        local output_content
        output_content=$(cat "$temp_output")

        # Parse the response
        TICKET_SUMMARY=$(echo "$output_content" | grep "^BRANCH_SUMMARY:" | sed 's/^BRANCH_SUMMARY:[[:space:]]*//' | tr -d '\n' | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g' | sed 's/--*/-/g' | sed 's/^-//;s/-$//')

        # Store the full info for later use
        TICKET_FULL_INFO="$output_content"

        rm -f "$temp_output"

        # Validate we got a summary
        if [[ -z "$TICKET_SUMMARY" || ${#TICKET_SUMMARY} -gt 50 ]]; then
            TICKET_SUMMARY="feature"
            print_warning "Could not generate branch name from ticket, using default"
        else
            print_success "Ticket information fetched successfully"
        fi

        return 0
    else
        rm -f "$temp_output"
        TICKET_SUMMARY="feature"
        print_warning "Failed to fetch ticket information, using defaults"
        return 1
    fi
}

# Check for uncommitted changes and offer options to handle them
# Returns 0 if safe to proceed, 1 if user aborted
# Options: stash, commit, abort
check_git_dirty_state() {
    local context="${1:-operation}"  # Description of what we're about to do

    # Check if we're in a git repository
    if ! git rev-parse --git-dir > /dev/null 2>&1; then
        # Not in a git repo, nothing to check
        return 0
    fi

    # Check for uncommitted changes (both staged and unstaged)
    if git diff --quiet 2>/dev/null && git diff --cached --quiet 2>/dev/null; then
        # Working directory is clean
        return 0
    fi

    print_warning "You have uncommitted changes"
    echo ""
    git --no-pager status --short
    echo ""

    print_info "Before ${context}, you should handle these changes."
    echo ""
    echo "  ${COLOR_BOLD}1)${COLOR_RESET} Stash changes (save for later)"
    echo "  ${COLOR_BOLD}2)${COLOR_RESET} Commit changes now"
    echo "  ${COLOR_BOLD}3)${COLOR_RESET} Discard changes (WARNING: cannot be undone)"
    echo "  ${COLOR_BOLD}4)${COLOR_RESET} Continue anyway (not recommended)"
    echo "  ${COLOR_BOLD}5)${COLOR_RESET} Abort"
    echo ""

    local choice
    while true; do
        echo -e -n "${COLOR_YELLOW}Select option [1-5]: ${COLOR_RESET}"
        read -r choice

        case "$choice" in
            1)
                # Stash changes
                local stash_msg="ai-workflow: auto-stash before ${context}"
                if git stash push -m "$stash_msg"; then
                    print_success "Changes stashed successfully"
                    print_info "To restore later: git stash pop"
                    return 0
                else
                    print_error "Failed to stash changes"
                    return 1
                fi
                ;;
            2)
                # Commit changes
                local commit_msg
                prompt_input "Enter commit message" commit_msg "WIP: work in progress"
                if git add -A && git commit -m "$commit_msg"; then
                    print_success "Changes committed successfully"
                    return 0
                else
                    print_error "Failed to commit changes"
                    return 1
                fi
                ;;
            3)
                # Discard changes
                if prompt_confirm "Are you sure you want to discard ALL uncommitted changes?"; then
                    if git restore . && git clean -fd; then
                        print_success "Changes discarded"
                        return 0
                    else
                        print_error "Failed to discard changes"
                        return 1
                    fi
                fi
                ;;
            4)
                # Continue anyway
                print_warning "Continuing with uncommitted changes (not recommended)"
                return 0
                ;;
            5)
                # Abort
                print_info "Aborting ${context}"
                return 1
                ;;
            *)
                print_warning "Invalid option. Please select 1-5."
                ;;
        esac
    done
}

# Create a new git branch based on ticket
create_branch_for_ticket() {
    print_header "Branch Creation"
    print_info "Creating a new branch for ticket: ${TICKET_ID}"
    echo ""

    # Check if we're in a git repository
    if ! git rev-parse --git-dir > /dev/null 2>&1; then
        print_error "Not in a git repository"
        return 1
    fi

    # Check for uncommitted changes before switching branches
    if ! check_git_dirty_state "creating a new branch"; then
        return 1
    fi

    # Use cached ticket summary if available, otherwise fetch it
    if [[ -z "$TICKET_SUMMARY" ]]; then
        fetch_ticket_info
    else
        print_info "Using cached ticket information"
    fi

    # Construct branch name
    local branch_name="${TICKET_ID}-${TICKET_SUMMARY}"

    print_info "Suggested branch name: ${COLOR_BOLD}${branch_name}${COLOR_RESET}"
    echo ""

    # Ask user if they want to use this name or customize
    if prompt_confirm "Create branch with this name?"; then
        # Check if branch already exists
        if git show-ref --verify --quiet "refs/heads/${branch_name}"; then
            print_warning "Branch '${branch_name}' already exists"
            if prompt_confirm "Switch to existing branch?"; then
                if git checkout "${branch_name}"; then
                    print_success "Switched to existing branch: ${branch_name}"
                    return 0
                else
                    print_error "Failed to switch to branch"
                    return 1
                fi
            else
                return 1
            fi
        fi

        # Create and checkout new branch
        if git checkout -b "${branch_name}"; then
            print_success "Created and switched to new branch: ${branch_name}"
            log_message "Created branch: ${branch_name}"
            return 0
        else
            print_error "Failed to create branch"
            return 1
        fi
    else
        # Allow user to customize branch name
        local custom_branch
        prompt_input "Enter custom branch name (or press Enter to skip branch creation)" custom_branch ""

        if [[ -n "$custom_branch" ]]; then
            if git checkout -b "${custom_branch}"; then
                print_success "Created and switched to new branch: ${custom_branch}"
                log_message "Created branch: ${custom_branch}"
                return 0
            else
                print_error "Failed to create branch"
                return 1
            fi
        else
            print_info "Skipping branch creation"
            return 0
        fi
    fi
}

# Step 1: Create implementation plan from Jira ticket
# Streamlined UX: single ticket prompt, auto branch creation, minimal prompts
step_1_create_plan() {
    print_header "Step 1: Create Implementation Plan (Discovery)"
    print_info "This step will analyze the Jira ticket and create a comprehensive implementation plan."
    echo ""

    # Prompt for Jira ticket (or use preset)
    local ticket_input
    if [[ -n "$PRESET_TICKET" ]]; then
        ticket_input="$PRESET_TICKET"
        print_info "Using preset ticket: ${ticket_input}"
    else
        prompt_input "Enter Jira ticket ID (e.g., PROJECT-123, 123) or URL" ticket_input ""
    fi

    if [[ -z "$ticket_input" ]]; then
        print_error "Ticket ID/URL is required"
        return 1
    fi

    # Validate and parse ticket
    if ! parse_jira_ticket "$ticket_input"; then
        return 1
    fi

    # Fetch ticket information once (will be cached and reused)
    print_step "Fetching ticket information..."
    if ! fetch_ticket_info; then
        print_warning "Failed to fetch ticket info, but continuing..."
    fi
    echo ""

    # Auto branch creation (streamlined UX)
    # Priority: preset branch > auto-create based on ticket
    if [[ -n "$PRESET_BRANCH" ]]; then
        # Use preset branch
        print_info "Using preset branch: ${PRESET_BRANCH}"
        if ! check_git_dirty_state "switching to preset branch"; then
            return 1
        fi
        if git show-ref --verify --quiet "refs/heads/${PRESET_BRANCH}"; then
            if git checkout "${PRESET_BRANCH}"; then
                print_success "Switched to preset branch: ${PRESET_BRANCH}"
            else
                print_error "Failed to switch to preset branch"
                return 1
            fi
        else
            if git checkout -b "${PRESET_BRANCH}"; then
                print_success "Created and switched to preset branch: ${PRESET_BRANCH}"
            else
                print_error "Failed to create preset branch"
                return 1
            fi
        fi
    else
        # Auto-create branch based on ticket (streamlined UX)
        # Only prompt if user explicitly wants to skip
        local current_branch
        current_branch=$(git branch --show-current 2>/dev/null || echo "")
        local expected_branch="${TICKET_ID}-${TICKET_SUMMARY}"

        # Check if already on a ticket-related branch
        if [[ "$current_branch" == *"${TICKET_ID}"* ]]; then
            print_info "Already on ticket branch: ${current_branch}"
        else
            print_info "Will create branch: ${expected_branch}"
            if ! create_branch_for_ticket; then
                print_warning "Branch creation failed, continuing on: ${current_branch:-unknown}"
            fi
        fi
    fi
    echo ""

    # Set plan file path (deterministic)
    PLAN_FILE="specs/${TICKET_ID}-plan.md"

    # Create specs directory if it doesn't exist
    if [[ ! -d "specs" ]]; then
        print_step "Creating specs directory..."
        mkdir -p specs
    fi

    # Check if plan file already exists (streamlined: auto-overwrite with warning)
    if [[ -f "$PLAN_FILE" ]]; then
        print_warning "Plan file already exists: ${PLAN_FILE}"
        if ! prompt_confirm "Overwrite existing plan?"; then
            print_info "Using existing plan file"
            return 0
        fi
        print_info "Will overwrite existing plan"
    fi

    # Construct the prompt for Auggie
    print_step "Creating implementation plan..."
    print_info "This may take a few minutes as the AI analyzes the ticket and codebase..."
    echo ""

    # Build prompt with cached ticket info if available
    local prompt
    local plan_template='Use this exact structure for the plan:

```markdown
# Implementation Plan: <TICKET_ID>

## Summary
<One paragraph describing what this ticket accomplishes>

## User Story & Acceptance Criteria
- As a <role>, I want <feature> so that <benefit>
- Acceptance Criteria:
  - [ ] <criterion 1>
  - [ ] <criterion 2>

## Files to Create/Modify
| File | Action | Purpose |
|------|--------|---------|
| path/to/file.ts | Create/Modify | Brief description |

## Implementation Tasks
### Phase 1: <Phase Name>
1. <Task 1 description>
2. <Task 2 description>

### Phase 2: <Phase Name>
1. <Task 1 description>

## Technical Considerations
- **Architecture**: <decisions about structure, patterns>
- **Dependencies**: <new packages, imports needed>
- **Error Handling**: <how errors should be handled>
- **Performance**: <any performance considerations>

## Testing Strategy
- **Unit Tests**: <what to test, which files>
- **Integration Tests**: <if applicable>
- **Test Commands**: <exact commands to run tests, e.g., npm test, pytest>
```'

    if [[ -n "$TICKET_FULL_INFO" ]]; then
        prompt="I am working on ticket ${TICKET_ID}. Here is the ticket information I already fetched:

${TICKET_FULL_INFO}

Please search the codebase for relevant files and create a comprehensive implementation plan in a new file named ${PLAN_FILE}.

IMPORTANT INSTRUCTIONS:
- Create the ENTIRE plan file in ONE operation using the save-file tool
- Do NOT make multiple sequential edits to the same file
- Generate the complete plan in a single operation
- Make the plan comprehensive and complete on the first attempt

${plan_template}

Do not write any code yet. You don't need to fetch the ticket again - use the information provided above."
    else
        prompt="I am working on ticket ${TICKET_URL}. Please read the ticket and search the codebase for relevant files. Create a comprehensive implementation plan in a new file named ${PLAN_FILE}.

IMPORTANT INSTRUCTIONS:
- Create the ENTIRE plan file in ONE operation using the save-file tool
- Do NOT make multiple sequential edits to the same file
- Generate the complete plan in a single operation
- Make the plan comprehensive and complete on the first attempt

${plan_template}

Do not write any code yet."
    fi

    # Execute in ASK mode with planning model
    print_step "Running: auggie --print"
    if [[ -n "$PLANNING_MODEL" ]]; then
        print_info "Using planning model: ${PLANNING_MODEL}"
    fi
    echo ""
    print_info "Creating comprehensive implementation plan..."

    # Start progress indicator in background
    (
        local dots=0
        local messages=(
            "Analyzing ticket requirements"
            "Searching codebase for relevant files"
            "Identifying dependencies and patterns"
            "Structuring implementation approach"
            "Finalizing plan details"
        )
        local msg_index=0
        local cycle_count=0

        while true; do
            # Cycle through messages every 10 seconds
            if [[ $cycle_count -ge 50 ]]; then  # 50 * 0.2s = 10s
                msg_index=$(( (msg_index + 1) % ${#messages[@]} ))
                cycle_count=0
            fi

            # Show progress with dots
            local dot_display=""
            for ((i=0; i<dots; i++)); do
                dot_display="${dot_display}."
            done

            echo -ne "\r${COLOR_CYAN}⏳ ${messages[$msg_index]}${dot_display}${COLOR_RESET}   "

            dots=$(( (dots + 1) % 4 ))
            cycle_count=$((cycle_count + 1))
            sleep 0.2
        done
    ) &
    local progress_pid=$!
    register_background_pid "$progress_pid"

    # Run the actual command
    local auggie_result=0
    if ! run_auggie --phase planning --print "${prompt}"; then
        auggie_result=1
    fi

    # Stop progress indicator (guarded with || true to avoid set -e issues)
    kill "$progress_pid" 2>/dev/null || true
    wait "$progress_pid" 2>/dev/null || true
    unregister_background_pid "$progress_pid"
    echo -ne "\r\033[K"  # Clear the progress line

    # Check result
    if [[ $auggie_result -eq 0 ]]; then
        print_success "Implementation plan created successfully!"
    else
        print_error "Failed to create implementation plan"
        return 1
    fi

    # Verify plan file was created
    if [[ ! -f "$PLAN_FILE" ]]; then
        print_error "Plan file was not created: ${PLAN_FILE}"
        return 1
    fi

    # Add plan file to .gitignore
    print_step "Adding plan file to .gitignore..."
    add_to_gitignore "$PLAN_FILE"

    # Display plan file location
    echo ""
    print_success "Plan file created: ${COLOR_BOLD}${PLAN_FILE}${COLOR_RESET}"

    # Auto-open the plan file
    echo ""
    open_file_in_editor "$PLAN_FILE"
    echo ""

    print_info "Please review the plan carefully."
    print_info "${COLOR_BOLD}This spec is your contract with the AI.${COLOR_RESET}"
    echo ""

    # Run clarification phase (controlled by --skip-clarification or config)
    step_1_5_clarification_phase "$PLAN_FILE"
    echo ""

    # Streamlined UX: auto-proceed to Step 2 (user can review plan in editor)
    print_info "Plan created. Proceeding to Step 2 (Task List Creation)..."
    log_message "Step 1 completed: Plan created at ${PLAN_FILE}"

    return 0
}

step_2_create_tasklist() {
    print_header "Step 2: Create Task List (Planning)"
    print_info "This step will convert the implementation plan into an actionable task list."
    echo ""

    # Verify plan file exists
    if [[ -z "$PLAN_FILE" ]]; then
        print_error "Plan file path is not set. Please run Step 1 first."
        return 1
    fi

    if [[ ! -f "$PLAN_FILE" ]]; then
        print_error "Plan file not found: ${PLAN_FILE}"
        print_info "Please run Step 1 first to create the plan."
        return 1
    fi

    print_success "Using plan file: ${PLAN_FILE}"
    echo ""

    # Set deterministic task list path (per spec: always specs/${TICKET_ID}-tasklist.md)
    TASK_LIST_FILE="specs/${TICKET_ID}-tasklist.md"
    print_info "Task list will be written to: ${TASK_LIST_FILE}"

    # Check if task list file already exists
    local skip_creation=false
    if [[ -f "$TASK_LIST_FILE" ]]; then
        print_warning "Task list file already exists: ${TASK_LIST_FILE}"
        if ! prompt_confirm "Do you want to regenerate it?"; then
            print_info "Using existing task list file"
            skip_creation=true
        else
            print_info "Will regenerate task list"
        fi
    fi
    echo ""

    # Create initial task list (unless skipped)
    if [[ "$skip_creation" != "true" ]]; then
        # Construct the prompt for Auggie - explicitly specify output file
        print_step "Converting plan to task list..."
        print_info "The AI will analyze the plan and create a structured task list."
        echo ""

        local prompt="Review @${PLAN_FILE}. Convert the implementation steps from the plan into a task list.

Write the task list to the file: ${TASK_LIST_FILE}

Format each task as a markdown checkbox:
- [ ] Task description

Group related tasks under appropriate headings. Each task should be:
- Atomic (can be completed independently)
- Clear (specific enough to execute without ambiguity)
- Testable (has clear completion criteria)"

        # Execute in AGENT mode with planning model
        print_step "Running: auggie --print"
        if [[ -n "$PLANNING_MODEL" ]]; then
            print_info "Using planning model: ${PLANNING_MODEL}"
        fi
        if run_auggie --phase planning --print "${prompt}"; then
            print_success "Task list created successfully!"
        else
            print_error "Failed to create task list"
            return 1
        fi

        # Verify task list file was created
        if [[ ! -f "$TASK_LIST_FILE" ]]; then
            print_error "Task list file was not created: ${TASK_LIST_FILE}"
            print_info "The AI may have written to a different location."
            return 1
        fi
    fi

    # Task Approval Loop - iterative refinement until user approves
    echo ""
    print_header "Task List Review"

    local max_iterations=5
    local iteration=0

    while [[ $iteration -lt $max_iterations ]]; do
        ((++iteration))

        # Display current task list
        echo ""
        print_info "${COLOR_BOLD}Current Task List:${COLOR_RESET}"
        echo "─────────────────────────────────────────"
        cat "$TASK_LIST_FILE"
        echo "─────────────────────────────────────────"
        echo ""

        # Count tasks (using -E for extended regex for more robust whitespace handling)
        local task_count
        task_count=$(grep -Ec '^\s*[-*]\s*\[\s*\]' "$TASK_LIST_FILE" 2>/dev/null || echo "0")
        print_info "Total incomplete tasks: ${task_count}"
        echo ""

        # Ask for approval or feedback
        echo "  ${COLOR_BOLD}1)${COLOR_RESET} Approve task list and proceed to Step 3"
        echo "  ${COLOR_BOLD}2)${COLOR_RESET} Request changes (provide feedback)"
        echo "  ${COLOR_BOLD}3)${COLOR_RESET} Edit task list manually"
        echo "  ${COLOR_BOLD}4)${COLOR_RESET} Abort workflow"
        echo ""

        local choice
        echo -e -n "${COLOR_YELLOW}Select option [1-4]: ${COLOR_RESET}"
        read -r choice

        case "$choice" in
            1)
                # Approved - proceed to Step 3
                print_success "Task list approved!"
                log_message "Step 2 completed: Task list approved with ${task_count} tasks"
                break
                ;;
            2)
                # Request changes via Auggie
                echo ""
                print_info "Enter your feedback for the AI (what changes do you want?):"
                local feedback
                read -r feedback

                if [[ -z "$feedback" ]]; then
                    print_warning "No feedback provided, please try again"
                    continue
                fi

                print_step "Requesting AI to update task list..."
                local refine_prompt="Review the task list at @${TASK_LIST_FILE}.

User feedback: ${feedback}

Please update the task list based on this feedback. Maintain the same file format:
- [ ] Task description

Make the requested changes and save the updated task list to the same file."

                if run_auggie --phase planning --print "${refine_prompt}"; then
                    print_success "Task list updated!"
                else
                    print_warning "AI update failed, you may want to edit manually"
                fi
                ;;
            3)
                # Manual edit
                print_info "Opening task list for manual editing..."
                open_file_in_editor "$TASK_LIST_FILE"
                prompt_enter "Press Enter when done editing"
                ;;
            4)
                # Abort
                print_info "Workflow aborted by user"
                return 1
                ;;
            *)
                print_warning "Invalid option. Please select 1-4."
                ;;
        esac
    done

    if [[ $iteration -ge $max_iterations ]]; then
        print_warning "Maximum refinement iterations reached"
        if ! prompt_confirm "Proceed with current task list anyway?"; then
            return 1
        fi
    fi

    echo ""
    print_info "${COLOR_BOLD}Task Breakdown:${COLOR_RESET}"
    print_info "The AI has organized the work into logical tasks."
    print_info "Typical breakdown: Backend → Frontend → Tests → Documentation"
    echo ""

    print_warning "${COLOR_BOLD}Important:${COLOR_RESET} In Step 3, the AI context will be reset for each task."
    print_info "This ensures focused execution without context pollution."
    echo ""

    return 0
}

step_3_execute_clean_loop() {
    print_header "Step 3: Execute Clean Loop (Execution)"
    print_info "This step executes each task with focused context."
    print_info "Changes are committed after each successful task (checkpoint commits)."
    print_info "At the end, checkpoint commits are squashed into a single commit."
    echo ""

    # Verify plan file exists
    if [[ -z "$PLAN_FILE" || ! -f "$PLAN_FILE" ]]; then
        print_error "Plan file not found. Please run Steps 1 and 2 first."
        return 1
    fi

    # Check if we're in a git repository
    if ! git rev-parse --git-dir > /dev/null 2>&1; then
        print_error "Not in a git repository. Please initialize git first."
        return 1
    fi

    # Check for uncommitted changes before starting
    if ! check_git_dirty_state "starting task execution"; then
        return 1
    fi

    # Capture base commit for squashing later
    local BASE_COMMIT
    BASE_COMMIT=$(git rev-parse HEAD)
    print_info "Base commit: ${BASE_COMMIT:0:8}"
    echo ""

    # Array to store completed task names
    declare -a COMPLETED_TASKS=()
    declare -a FAILED_TASKS=()

    # Try to load tasks from task list file
    if [[ -z "$TASK_LIST_FILE" || ! -f "$TASK_LIST_FILE" ]]; then
        print_error "Task list file not found"
        print_info "Expected task list file: ${TASK_LIST_FILE:-<not set>}"
        print_info "Please ensure Step 2 completed successfully and created the task list."
        return 1
    fi

    print_info "Loading tasks from: ${TASK_LIST_FILE}"

    if ! parse_task_list "$TASK_LIST_FILE" TASK_LIST_ARRAY; then
        print_error "Failed to parse task list file"
        print_info "The task list file may be in an unexpected format."
        print_info "Please check the file: ${TASK_LIST_FILE}"
        return 1
    fi

    TOTAL_TASKS=${#TASK_LIST_ARRAY[@]}

    if [[ $TOTAL_TASKS -eq 0 ]]; then
        print_warning "No incomplete tasks found in task list"
        print_info "All tasks may already be completed, or the task list is empty."
        return 0
    fi

    print_success "Loaded ${TOTAL_TASKS} tasks from task list"
    CURRENT_TASK_INDEX=0

    # Initialize execution notes
    local EXECUTION_NOTES_FILE
    EXECUTION_NOTES_FILE=$(init_execution_notes "$TOTAL_TASKS")

    # Add execution notes and context snapshot to gitignore
    add_to_gitignore "specs/${TICKET_ID}-execution-notes.md"
    add_to_gitignore "specs/${TICKET_ID}-context-snapshot.md"

    print_info "Progress is tracked in: ${EXECUTION_NOTES_FILE}"
    print_info "Task list state is updated in: ${TASK_LIST_FILE}"
    echo ""

    # Configuration for automatic execution
    local max_retries=3
    local retry_count=0
    local last_failure_context=""  # Tracks failure reason for retry context

    print_info "Starting automatic task execution..."
    print_info "Tasks will be executed sequentially with up to ${max_retries} retries per task."
    log_message "Step 3 started: ${TOTAL_TASKS} tasks to execute"
    echo ""

    # Automatic execution loop - no per-task prompts
    while [[ $CURRENT_TASK_INDEX -lt $TOTAL_TASKS ]]; do
        local task_name="${TASK_LIST_ARRAY[$CURRENT_TASK_INDEX]}"
        local progress_percent=$(( (CURRENT_TASK_INDEX + 1) * 100 / TOTAL_TASKS ))

        # Progress header
        echo ""
        echo "═══════════════════════════════════════════════════════════════════════════════"
        print_info "${COLOR_BOLD}Task $((CURRENT_TASK_INDEX + 1))/${TOTAL_TASKS}${COLOR_RESET} (${progress_percent}% complete)"
        print_info "${COLOR_BOLD}Task:${COLOR_RESET} ${task_name}"
        echo "═══════════════════════════════════════════════════════════════════════════════"
        echo ""

        # Generate context snapshot before task
        local CONTEXT_SNAPSHOT_FILE
        CONTEXT_SNAPSHOT_FILE=$(generate_context_snapshot)

        # Prepare context files
        local context_files="@${PLAN_FILE} @${TASK_LIST_FILE}"

        # Add execution notes if it exists
        if [[ -f "$EXECUTION_NOTES_FILE" ]]; then
            context_files="${context_files} @${EXECUTION_NOTES_FILE}"
        fi

        # Add context snapshot
        if [[ -f "$CONTEXT_SNAPSHOT_FILE" ]]; then
            context_files="${context_files} @${CONTEXT_SNAPSHOT_FILE}"
        fi

        # Check rules context and add if legacy file exists
        local rules_path
        if rules_path=$(get_rules_context); then
            # Rules are auto-loaded, no manual injection needed
            :
        else
            # Legacy rules file exists, add it for backwards compatibility
            if [[ -n "$rules_path" ]]; then
                context_files="${context_files} @${rules_path}"
            fi
        fi

        # Generate list of files modified so far in this session (progress tracking)
        local modified_files_list=""
        local modified_files
        modified_files=$(git diff --name-only "$BASE_COMMIT" HEAD 2>/dev/null || true)
        if [[ -n "$modified_files" ]]; then
            modified_files_list="
FILES ALREADY MODIFIED IN THIS SESSION:
The following files have been modified in previous tasks of this ticket. Be aware of these changes:
${modified_files}
"
        fi

        # Build retry context if this is a retry attempt
        local retry_context=""
        if [[ $retry_count -gt 0 && -n "$last_failure_context" ]]; then
            retry_context="
⚠️ RETRY ATTEMPT ${retry_count}/${max_retries}:
This task failed in a previous attempt. Here's what went wrong:
${last_failure_context}

Please try a DIFFERENT APPROACH this time. Consider:
- If tests failed: check the test expectations and fix the implementation
- If there was a syntax/type error: review the error message carefully
- If the approach was wrong: try an alternative implementation strategy
"
        fi

        # Construct focused prompt with progress tracking
        local prompt="Referencing @${PLAN_FILE}, we are now executing it. Implement the changes required for task: \"${task_name}\" only.
${retry_context}
IMPORTANT GUIDELINES:
- Focus ONLY on this specific task - do not implement other tasks from the list
- Only modify files directly required for this task. If you need to modify shared utilities or interfaces, document why in your response.

TESTING REQUIREMENTS:
After implementation, verify your changes by running tests:
1. Check the plan file's 'Testing Strategy' section for specific test commands
2. If no specific commands are listed, use the project's standard test runner:
   - For JavaScript/TypeScript: npm test or yarn test
   - For Python: pytest or python -m pytest
   - For Go: go test ./...
3. Run tests that cover the modified files - look for test files in the same directory or with matching names (e.g., foo.test.ts for foo.ts)
4. If tests fail, fix the issues before considering the task complete
${modified_files_list}
Context files: ${context_files}"

        # Execute task with Auggie using implementation model
        print_step "Executing task..."
        if [[ -n "$IMPLEMENTATION_MODEL" ]]; then
            print_info "Using implementation model: ${IMPLEMENTATION_MODEL}"
        fi

        local task_success=false

        # Added --dont-save-session to ensure clean context for each task
        if run_auggie --dont-save-session --phase implementation --print "${prompt}"; then
            # Check if changes were made
            if ! git diff --quiet 2>/dev/null; then
                task_success=true
                print_success "Task completed with changes"

                # Show brief diff summary
                echo ""
                print_info "Changes summary:"
                git --no-pager diff --stat --color=always 2>/dev/null | head -n 10
                echo ""

                # Ask user for confirmation before committing
                if prompt_confirm "Do you want to commit these changes?"; then
                    # Create checkpoint commit
                    print_step "Creating checkpoint commit..."
                    git add . 2>/dev/null
                    local checkpoint_msg="wip(${TICKET_ID}): ${task_name}"
                    if git commit -m "$checkpoint_msg" 2>/dev/null; then
                        local commit_hash
                        commit_hash=$(git rev-parse HEAD)
                        print_success "Checkpoint commit: ${commit_hash:0:8}"

                        # Update execution notes
                        append_task_result "$EXECUTION_NOTES_FILE" "$task_name" "✅ Completed" "${commit_hash:0:8}"

                        # Mark task complete in task list
                        mark_task_complete "$TASK_LIST_FILE" "$task_name"
                        COMPLETED_TASKS+=("${task_name}")
                        log_message "Task completed: ${task_name} (commit: ${commit_hash:0:8})"
                    else
                        print_error "Failed to create checkpoint commit"
                        task_success=false
                    fi
                else
                    print_info "Commit skipped by user"
                    # Still mark task as complete but without commit
                    append_task_result "$EXECUTION_NOTES_FILE" "$task_name" "✅ Completed (not committed)" "N/A"
                    mark_task_complete "$TASK_LIST_FILE" "$task_name"
                    COMPLETED_TASKS+=("${task_name}")
                    log_message "Task completed: ${task_name} (commit skipped by user)"
                fi
            else
                print_warning "Task completed but no changes detected"
                # Still mark as complete even without changes
                append_task_result "$EXECUTION_NOTES_FILE" "$task_name" "✅ Completed (no changes)" "N/A"
                mark_task_complete "$TASK_LIST_FILE" "$task_name"
                COMPLETED_TASKS+=("${task_name}")
                log_message "Task completed: ${task_name} (no changes)"
                task_success=true
            fi
        else
            print_error "Task execution failed"
        fi

        if [[ "$task_success" == "true" ]]; then
            retry_count=0
            last_failure_context=""  # Clear failure context on success
            ((CURRENT_TASK_INDEX++))
        else
            # Capture failure context for retry
            # Include git diff to show what partial changes were made
            local partial_changes=""
            if ! git diff --quiet 2>/dev/null; then
                partial_changes=$(git diff --stat 2>/dev/null | tail -5)
            fi

            # Build failure context message
            last_failure_context="The task execution did not complete successfully."
            if [[ -n "$partial_changes" ]]; then
                last_failure_context="${last_failure_context}
Partial changes were made to these files (now reverted):
${partial_changes}"
            fi

            # Handle failure with bounded retries
            ((retry_count++))
            if [[ $retry_count -lt $max_retries ]]; then
                print_warning "Retrying task (attempt ${retry_count}/${max_retries})..."
                print_info "Failure context will be provided to the AI for the retry attempt."
                # Revert any partial changes before retry (safe because tree is clean from checkpoint)
                print_info "Reverting uncommitted changes..."
                git restore . 2>/dev/null || true
                # Removed dangerous 'git clean -fd'
            else
                print_error "Task failed after ${max_retries} attempts, skipping"
                FAILED_TASKS+=("${task_name}")
                append_task_result "$EXECUTION_NOTES_FILE" "$task_name" "❌ Failed" "N/A"
                log_message "Task failed: ${task_name}"
                # Revert any partial changes (safe because tree is clean from checkpoint)
                print_info "Reverting uncommitted changes..."
                git restore . 2>/dev/null || true
                # Removed dangerous 'git clean -fd'
                retry_count=0
                last_failure_context=""  # Clear failure context when moving to next task
                ((CURRENT_TASK_INDEX++))
            fi
        fi

        # Progress update
        local completed_count=${#COMPLETED_TASKS[@]}
        local failed_count=${#FAILED_TASKS[@]}
        print_info "Progress: ${completed_count} completed, ${failed_count} failed, $((TOTAL_TASKS - CURRENT_TASK_INDEX)) remaining"
    done

    echo ""
    print_success "Automatic task execution completed!"
    log_message "Step 3 completed: ${#COMPLETED_TASKS[@]} completed, ${#FAILED_TASKS[@]} failed"

    # Post-Execution Satisfaction Loop
    if [[ ${#COMPLETED_TASKS[@]} -gt 0 ]] && ! git diff --quiet 2>/dev/null; then
        post_execution_satisfaction_loop
    fi

    # Final summary
    print_header "Execution Summary"

    # Show completed tasks
    if [[ ${#COMPLETED_TASKS[@]} -gt 0 ]]; then
        print_success "Completed ${#COMPLETED_TASKS[@]} task(s):"
        for task in "${COMPLETED_TASKS[@]}"; do
            echo "  ✓ ${task}"
        done
        echo ""
    fi

    # Show failed tasks
    if [[ ${#FAILED_TASKS[@]} -gt 0 ]]; then
        print_warning "Failed ${#FAILED_TASKS[@]} task(s):"
        for task in "${FAILED_TASKS[@]}"; do
            echo "  ✗ ${task}"
        done
        echo ""
    fi

    if [[ ${#COMPLETED_TASKS[@]} -eq 0 ]]; then
        print_warning "No tasks were completed"
        # Revert any partial changes
        if ! git diff --quiet 2>/dev/null; then
            print_info "Reverting partial changes..."
            git restore . 2>/dev/null || true
        fi
        return 0
    fi

    # Squash checkpoint commits (if enabled)
    local squash_enabled
    squash_enabled=$(get_config "SQUASH_AT_END" "true")

    if [[ "$squash_enabled" == "true" && ${#COMPLETED_TASKS[@]} -gt 0 ]]; then
        print_step "Squashing checkpoint commits..."

        # Build final commit message
        local final_message
        if [[ ${#COMPLETED_TASKS[@]} -eq 1 ]]; then
            final_message="feat(${TICKET_ID}): ${COMPLETED_TASKS[0]}"
        else
            final_message="feat(${TICKET_ID}): implement ${#COMPLETED_TASKS[@]} tasks

Completed tasks:
$(for task in "${COMPLETED_TASKS[@]}"; do echo "- ${task}"; done)"
        fi

        # Squash commits
        if git reset --soft "$BASE_COMMIT" 2>/dev/null; then
            if git commit -m "$final_message" 2>/dev/null; then
                print_success "Checkpoint commits squashed into single commit"
                echo ""
                print_info "Final commit message:"
                echo "$final_message"
                echo ""
            else
                print_error "Failed to create final commit"
                return 1
            fi
        else
            print_error "Failed to reset to base commit"
            return 1
        fi
    else
        print_info "Keeping individual checkpoint commits (SQUASH_AT_END=false)"
    fi

    # Show final diff summary
    echo ""
    print_info "Total changes from base commit:"
    git --no-pager diff --stat "${BASE_COMMIT}" HEAD --color=always 2>/dev/null
    echo ""

    print_step "Next steps:"
    echo "  1. Review the commit: git show"
    echo "  2. Push your branch: git push origin $(git branch --show-current 2>/dev/null || echo '<branch-name>')"
    echo "  3. Create a Pull Request"
    echo ""

    return 0
}

# Post-Execution Satisfaction Loop
# Allows user to request refinements after all tasks are executed
# Features:
#   - Warning on first 'no' (are you sure?)
#   - Free-text feedback for AI refinements
#   - Automatic test re-runs after refinements
#   - Bounded iterations to prevent infinite loops
post_execution_satisfaction_loop() {
    print_header "Post-Execution Review"
    print_info "Review the changes before committing."
    echo ""

    local max_iterations=5
    local iteration=0
    local first_no=true

    while [[ $iteration -lt $max_iterations ]]; do
        ((iteration++))

        # Show current diff summary
        echo ""
        print_info "${COLOR_BOLD}Current Changes:${COLOR_RESET}"
        echo "─────────────────────────────────────────"
        git --no-pager diff --stat --color=always 2>/dev/null | head -n 20
        echo "─────────────────────────────────────────"
        echo ""

        # Ask if satisfied
        echo -e -n "${COLOR_YELLOW}Are you satisfied with the changes? [y/n]: ${COLOR_RESET}"
        local response
        read -r response

        case "$response" in
            [yY]|[yY][eE][sS])
                print_success "Changes approved!"
                log_message "Satisfaction loop: Changes approved after ${iteration} iteration(s)"
                return 0
                ;;
            [nN]|[nN][oO])
                # Warning on first 'no'
                if [[ "$first_no" == "true" ]]; then
                    first_no=false
                    print_warning "You indicated you're not satisfied with the changes."
                    print_info "You can provide feedback for the AI to make refinements."
                    echo ""
                    if ! prompt_confirm "Would you like to request refinements?"; then
                        print_info "Proceeding with current changes..."
                        return 0
                    fi
                fi

                # Get free-text feedback
                echo ""
                print_info "Enter your feedback (what needs to be changed?):"
                local feedback
                read -r feedback

                if [[ -z "$feedback" ]]; then
                    print_warning "No feedback provided. Please try again or approve the changes."
                    continue
                fi

                # Request AI refinements
                print_step "Requesting AI refinements..."
                local refine_prompt="The user has reviewed the changes and provided the following feedback:

${feedback}

Please make the requested refinements to the code. After making changes, run relevant tests to verify the changes work correctly.

Context: We are working on ticket ${TICKET_ID}. The plan is at @${PLAN_FILE}."

                if run_auggie --phase implementation --print "${refine_prompt}"; then
                    print_success "Refinements applied!"

                    # Run tests after refinements
                    print_step "Running tests to verify refinements..."
                    local test_prompt="Run the relevant tests to verify the recent changes work correctly."
                    run_auggie --phase implementation --print --quiet "${test_prompt}" || true

                    log_message "Satisfaction loop: Refinements applied (iteration ${iteration})"
                else
                    print_warning "AI refinement failed. You may want to make manual changes."
                fi
                ;;
            *)
                print_warning "Please answer yes (y) or no (n)."
                ;;
        esac
    done

    if [[ $iteration -ge $max_iterations ]]; then
        print_warning "Maximum refinement iterations (${max_iterations}) reached."
        print_info "Proceeding with current changes. You can make manual adjustments if needed."
        log_message "Satisfaction loop: Max iterations reached"
    fi

    return 0
}

# Initialize execution notes file
init_execution_notes() {
    local notes_file="specs/${TICKET_ID}-execution-notes.md"
    local base_commit
    base_commit=$(git rev-parse HEAD 2>/dev/null || echo "N/A")
    local total_tasks="${1:-0}"

    cat > "$notes_file" << EOF
# Execution Notes: ${TICKET_ID}

## Execution Started
- Date: $(date '+%Y-%m-%d %H:%M:%S')
- Base Commit: ${base_commit}
- Total Tasks: ${total_tasks}

---

## Task Log

EOF
    echo "$notes_file"
}

# Append task result to execution notes
append_task_result() {
    local notes_file="$1"
    local task_name="$2"
    local status="$3"  # completed|failed|skipped
    local commit_hash="${4:-N/A}"

    local files_changed
    files_changed=$(git diff --stat --shortstat 2>/dev/null | tail -1 || echo "N/A")

    cat >> "$notes_file" << EOF

### Task: ${task_name}
- Status: ${status}
- Timestamp: $(date '+%Y-%m-%d %H:%M:%S')
- Files Changed: ${files_changed}
- Checkpoint Commit: ${commit_hash}

EOF
}

# Generate context snapshot
generate_context_snapshot() {
    local snapshot_file="specs/${TICKET_ID}-context-snapshot.md"

    cat > "$snapshot_file" << EOF
# Context Snapshot: ${TICKET_ID}

## Git Status
\`\`\`
$(git status --short 2>/dev/null || echo "N/A")
\`\`\`

## Changes Summary
\`\`\`
$(git diff --stat 2>/dev/null || echo "N/A")
\`\`\`

## Last Updated
$(date '+%Y-%m-%d %H:%M:%S')
EOF
    echo "$snapshot_file"
}

# Check rules layout and return path for manual injection if needed
# Returns 0 if rules are auto-loaded (no manual injection needed)
# Returns 1 if legacy .augment/rules file exists (manual injection needed for backwards compatibility)
get_rules_context() {
    # Preferred: directory layout
    if [[ -d ".augment/rules" ]]; then
        print_info "Using rules from .augment/rules/ directory (auto-loaded by Auggie)" >&2
        return 0  # No manual injection needed
    fi

    # Alternative: AGENTS.md
    if [[ -f "AGENTS.md" ]]; then
        print_info "Using AGENTS.md guidelines (auto-loaded by Auggie)" >&2
        return 0
    fi

    # Legacy: single file (deprecated)
    if [[ -f ".augment/rules" ]]; then
        print_warning "DEPRECATED: .augment/rules as single file" >&2
        print_info "Migration: mkdir -p .augment/rules && mv .augment/rules .augment/rules/main.md" >&2
        # Return path for manual injection (backwards compatibility)
        echo ".augment/rules"
        return 1
    fi

    return 0
}

################################################################################
# Help and Version Functions
################################################################################

# Show help message
show_help() {
    cat << EOF
${COLOR_BOLD}${SCRIPT_NAME} v${SCRIPT_VERSION}${COLOR_RESET}

${COLOR_BOLD}DESCRIPTION:${COLOR_RESET}
    Standardized script for AI-assisted development workflows using Auggie CLI.
    Helps developers leverage AI assistance consistently across the team.

${COLOR_BOLD}USAGE:${COLOR_RESET}
    $0 [OPTIONS]

${COLOR_BOLD}OPTIONS:${COLOR_RESET}
    -h, --help                 Show this help message and exit
    -v, --version              Show version information and exit

${COLOR_BOLD}WORKFLOW OPTIONS:${COLOR_RESET}
    --ticket <TICKET_ID>       Pre-specify Jira ticket (e.g., PROJECT-123)
    --branch <BRANCH_NAME>     Pre-specify branch name
    --model <MODEL_NAME>       Pre-specify AI model

${COLOR_BOLD}AUTOMATION OPTIONS:${COLOR_RESET}
    --no-open                  Disable auto-opening files in editor
    --skip-clarification       Skip clarification step after plan generation
    --force-jira-check         Force fresh Jira integration check (ignore cache)

${COLOR_BOLD}FEATURES:${COLOR_RESET}
    1. Automated code review on PRs (Coming Soon)
    2. Spec-Driven Development workflow:
       - Step 1: Create implementation plan from Jira ticket
       - Step 1.5: Optional clarification phase for ambiguous requirements
       - Step 2: Convert plan to actionable task list
       - Step 3: Execute tasks with focused AI context and automated task selection

${COLOR_BOLD}ENVIRONMENT VARIABLES:${COLOR_RESET}
    AI_WORKFLOW_LOG          Enable logging (true/false, default: false)
    AI_WORKFLOW_LOG_FILE     Log file path (default: ~/.ai-workflow.log)

${COLOR_BOLD}REQUIREMENTS:${COLOR_RESET}
    - Bash 4.3+ (macOS users: install via 'brew install bash')
    - Node.js ${REQUIRED_NODE_VERSION}+
    - npm
    - git
    - Auggie CLI ${REQUIRED_AUGGIE_VERSION}+ (will be installed if missing)

${COLOR_BOLD}EXAMPLES:${COLOR_RESET}
    # Run the script normally (interactive mode)
    $0

    # Streamlined mode with pre-set ticket
    $0 --ticket PROJECT-123 --branch feature/new-feature

    # Fully automated mode (advanced users)
    $0 --ticket PROJECT-123 --skip-clarification

    # Disable auto-opening files
    $0 --no-open

    # Enable logging
    AI_WORKFLOW_LOG=true $0

    # Use custom log file
    AI_WORKFLOW_LOG=true AI_WORKFLOW_LOG_FILE=/tmp/workflow.log $0

${COLOR_BOLD}RULES/GUIDELINES:${COLOR_RESET}
    The script supports project rules in these locations (in order of preference):
    1. .augment/rules/  (directory of markdown files - recommended)
    2. AGENTS.md        (repository root)
    3. .augment/rules   (single file - DEPRECATED)

    Rules are auto-loaded by Auggie and should not be manually specified.

${COLOR_BOLD}CHECKPOINT COMMITS:${COLOR_RESET}
    Step 3 creates checkpoint commits after each successful task:
      wip(TICKET-123): <task name>

    At the end, these are squashed into a single commit by default.
    To keep individual commits, set SQUASH_AT_END=false in config.

${COLOR_BOLD}EXECUTION NOTES:${COLOR_RESET}
    Progress is tracked in: specs/<TICKET_ID>-execution-notes.md
    This file contains timestamps, commit hashes, and task status.

${COLOR_BOLD}CONFIGURATION:${COLOR_RESET}
    Config file: ~/.ai-workflow-config
    Use option 3 in the main menu to configure default settings.

${COLOR_BOLD}EXIT CODES:${COLOR_RESET}
    0 - Success
    1 - General error
    2 - Auggie CLI not installed
    3 - Jira not configured
    4 - User cancelled operation
    5 - Git operation failed

${COLOR_BOLD}MORE INFORMATION:${COLOR_RESET}
    Auggie Documentation: https://docs.augmentcode.com/

EOF
}

# Show version information
show_version() {
    echo "${SCRIPT_NAME} v${SCRIPT_VERSION}"
    echo ""
    echo "Requirements:"
    echo "  - Auggie CLI: >= ${REQUIRED_AUGGIE_VERSION}"
    echo "  - Node.js: >= ${REQUIRED_NODE_VERSION}"
    echo ""

    # Show installed versions if available
    if command -v auggie &> /dev/null; then
        local auggie_version
        auggie_version=$(auggie --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "unknown")
        echo "Installed Auggie CLI: ${auggie_version}"
    else
        echo "Installed Auggie CLI: not installed"
    fi

    if command -v node &> /dev/null; then
        local node_version
        node_version=$(node --version 2>/dev/null || echo "unknown")
        echo "Installed Node.js: ${node_version}"
    else
        echo "Installed Node.js: not installed"
    fi
}

################################################################################
# CLI Flag Parsing
################################################################################

# Parse CLI flags and set global variables
parse_cli_flags() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -h|--help)
                show_help
                exit 0
                ;;
            -v|--version)
                show_version
                exit 0
                ;;
            --ticket)
                if [[ -n "${2:-}" ]]; then
                    PRESET_TICKET="$2"
                    shift 2
                else
                    print_error "--ticket requires a value"
                    exit 1
                fi
                ;;
            --branch)
                if [[ -n "${2:-}" ]]; then
                    PRESET_BRANCH="$2"
                    shift 2
                else
                    print_error "--branch requires a value"
                    exit 1
                fi
                ;;
            --model)
                if [[ -n "${2:-}" ]]; then
                    PRESET_MODEL="$2"
                    shift 2
                else
                    print_error "--model requires a value"
                    exit 1
                fi
                ;;
            --no-open)
                NO_OPEN=true
                shift
                ;;
            --skip-clarification)
                SKIP_CLARIFICATION=true
                shift
                ;;
            --force-jira-check)
                FORCE_JIRA_CHECK=true
                shift
                ;;
            *)
                print_error "Unknown option: $1"
                echo "Use --help for usage information"
                exit 1
                ;;
        esac
    done
}

################################################################################
# Main Execution
################################################################################

main() {
    # Parse command line arguments
    parse_cli_flags "$@"

    show_banner
    print_info "Initializing..."

    # Log script start with environment info
    log_message "========== Script started =========="
    log_message "Version: ${SCRIPT_VERSION}"
    log_message "Bash version: ${BASH_VERSION}"
    log_message "Working directory: $(pwd)"
    log_message "User: ${USER:-unknown}"

    # Load configuration
    load_config

    # Check if Auggie is installed
    if ! check_auggie_installed; then
        print_warning "Auggie CLI needs to be installed"
        if prompt_confirm "Would you like to install Auggie CLI now?"; then
            if ! install_auggie; then
                print_error "Failed to install Auggie CLI. Exiting."
                exit 2
            fi
        else
            print_error "Auggie CLI is required to run this script. Exiting."
            exit 2
        fi
    fi

    # Show main menu
    show_main_menu

    print_success "Script completed successfully"
    log_message "========== Script completed successfully =========="
}

# Run main function
main "$@"

