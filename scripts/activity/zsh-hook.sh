# >>> devtrail activity >>>
# Appends one JSONL line per command to ~/.devtrail/activity/<date>.jsonl.
# ASCII only, and every failure is swallowed -- collection must never break the shell.
# preexec captures the command text, precmd writes it with the exit status.
__devtrail_preexec() {
    # A leading space keeps a command out of the log (same idea as HIST_IGNORE_SPACE).
    case "$1" in
        ' '*) __DEVTRAIL_CMD='' ;;
        *) __DEVTRAIL_CMD="$1" ;;
    esac
}
__devtrail_precmd() {
    local __dt_exit=$?
    {
        setopt localoptions extendedglob noshwordsplit
        local cmd="$__DEVTRAIL_CMD" dir cwd ts file
        __DEVTRAIL_CMD=''
        [[ -z "$cmd" ]] && return 0
        cmd=${cmd//(ghp_|github_pat_|sk-|AIza|xoxb-|Bearer[[:space:]]##)[^[:space:]]##/***}
        cmd=${cmd//(#b)((#i)(token|secret|password|passwd|api(_|)key))[[:space:]]#[=:][[:space:]]#[^[:space:]]##/${match[1]}=***}
        cmd=${cmd//\\/\\\\}
        cmd=${cmd//\"/\\\"}
        cmd=${cmd//[[:cntrl:]]/ }
        cwd=${PWD//\\/\\\\}
        cwd=${cwd//\"/\\\"}
        dir="$HOME/.devtrail/activity"
        ts=${(%):-'%D{%Y-%m-%dT%H:%M:%S}'}
        mkdir -p "$dir" || return 0
        file="$dir/${ts[1,10]}.jsonl"
        print -r -- "{\"ts\":\"$ts\",\"host\":\"${HOST:-unknown}\",\"shell\":\"zsh\",\"cwd\":\"$cwd\",\"cmd\":\"$cmd\",\"exit\":$__dt_exit}" >>"$file"
    } 2>/dev/null
    return 0
}
autoload -Uz add-zsh-hook 2>/dev/null && {
    add-zsh-hook preexec __devtrail_preexec
    add-zsh-hook precmd __devtrail_precmd
}
# <<< devtrail activity <<<
