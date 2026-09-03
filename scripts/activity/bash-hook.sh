# >>> devtrail activity >>>
# Appends one JSONL line per command to ~/.devtrail/activity/<date>.jsonl.
# ASCII only, and every failure is swallowed -- collection must never break the shell.
__devtrail_activity() {
    local __dt_exit=$?
    {
        local dir raw num cmd ts file host bs
        dir="$HOME/.devtrail/activity"
        raw=$(HISTTIMEFORMAT='' history 1 2>/dev/null) || return 0
        num=$(printf '%s' "$raw" | awk '{print $1}')
        [ -z "$num" ] && return 0
        # First prompt of a shell replays the previous session's last command.
        if [ -z "$__DEVTRAIL_LAST_HIST" ]; then
            __DEVTRAIL_LAST_HIST="$num"
            return 0
        fi
        [ "$num" = "$__DEVTRAIL_LAST_HIST" ] && return 0
        __DEVTRAIL_LAST_HIST="$num"
        cmd=$(printf '%s' "$raw" | sed -E 's/^[[:space:]]*[0-9]+[[:space:]]+//')
        [ -z "$cmd" ] && return 0
        cmd=$(printf '%s' "$cmd" | sed -E \
            -e 's/(ghp_|github_pat_|sk-|AIza|xoxb-|Bearer[[:space:]]+)[^[:space:]]+/***/g' \
            -e 's/(token|secret|password|passwd|api_?key)[[:space:]]*[=:][[:space:]]*[^[:space:]]+/\1=***/gI')
        # JSON escaping via parameter expansion: a literal backslash only survives
        # the replacement when it comes from a variable.
        bs='\'
        cmd=${cmd//"$bs"/"$bs$bs"}
        cmd=${cmd//'"'/"$bs\""}
        cmd=${cmd//$'\t'/ }
        ts=$(date '+%Y-%m-%dT%H:%M:%S')
        host=$(hostname 2>/dev/null || printf 'unknown')
        mkdir -p "$dir" || return 0
        file="$dir/$(date '+%Y-%m-%d').jsonl"
        printf '{"ts":"%s","host":"%s","shell":"bash","cwd":"%s","cmd":"%s","exit":%s}\n' \
            "$ts" "$host" "$PWD" "$cmd" "$__dt_exit" >>"$file"
    } 2>/dev/null
    return 0
}
case ":$PROMPT_COMMAND:" in
    *:__devtrail_activity:*) ;;
    *) PROMPT_COMMAND="__devtrail_activity${PROMPT_COMMAND:+;$PROMPT_COMMAND}" ;;
esac
# <<< devtrail activity <<<
