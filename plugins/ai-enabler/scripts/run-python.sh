#!/usr/bin/env bash
# Keep identical in both independently installable plugins (tested by test_python_launcher.py).
# Only the probe is isolated: plugin scripts legitimately import sibling modules.
# Startup errors exit 1: guards use onFailure:block; passive metrics stay nonblocking.
if [[ $# -eq 0 || ( "$1" != --check && ! -f "$1" ) ]]; then
    printf '%s\n' 'Python launcher: pass an existing Python script path and its arguments, or --check.' >&2
    exit 1
fi

probe='import sys; sys.exit(1) if sys.version_info < (3, 8) or sys.version_info.major != 3 else None; print(sys.executable + "\t" + sys.version.split()[0])'
# GNU timeout is available with Git Bash and most Linux distributions; macOS
# can use gtimeout if installed. Otherwise Claude Code bounds the whole hook.
limiter=()
for timer in /usr/bin/timeout gtimeout timeout; do
    timer_path=$(type -P "$timer") || continue
    case "$timer_path" in
        *[Ss][Yy][Ss][Tt][Ee][Mm]32/*) continue ;; # Windows timeout is not GNU timeout.
    esac
    limiter=("$timer_path" -k 1 2)
    break
done

for name in python3 python py; do
    interpreter=$(type -P "$name") || continue
    # Do not activate Microsoft Store App Execution Aliases (including popups).
    case "$interpreter" in
        *[Ww][Ii][Nn][Dd][Oo][Ww][Ss][Aa][Pp][Pp][Ss]/*) continue ;;
    esac
    candidate=("$interpreter")
    [[ "$name" == py ]] && candidate+=(-3)
    # -c and /dev/null leave the hook's JSON stdin untouched, even on a bad candidate.
    if details=$("${limiter[@]}" "${candidate[@]}" -I -S -c "$probe" </dev/null 2>/dev/null); then
        if [[ "$1" == --check ]]; then
            printf '%s\n' "$details"
            exit 0
        fi
        script=$1
        shift
        case "$OSTYPE" in
            msys*|cygwin*)
                # Convert only the script path, not arbitrary arguments such as /api
                # or semicolon-delimited strings. Use native paths for path arguments.
                script=$(/usr/bin/cygpath -m -- "$script") || exit 1
                export MSYS2_ARG_CONV_EXCL='*'
                ;;
        esac
        # Never retry after the target starts: exit 2 is a security guard denial.
        exec "${candidate[@]}" "$script" "$@"
    fi
done

printf '%s\n' 'Python launcher: no working Python 3.8+ interpreter found (tried python3, python, py -3; Windows Store aliases are skipped). Install Python 3 and make it available to the shell running Claude Code, then restart Claude Code and rerun delivery-doctor or metrics-usage-init --status. Windows also requires Git Bash.' >&2
exit 1
