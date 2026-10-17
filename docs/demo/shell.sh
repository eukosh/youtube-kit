# Sourced inside the terminal VHS records: a plain prompt and a clean environment for one demo.
# Usage: source shell.sh agent|commands|login

DEMO=$PWD
REPO=$(git -C "$DEMO" rev-parse --show-toplevel)
export BASH_SILENCE_DEPRECATION_WARNING=1
export PS1='\[\e[38;5;245m\]~\[\e[0m\] \$ '

case $1 in
  agent)
    # Run from inside another Claude Code session, the recorded one would inherit its session and permission mode.
    for v in $(env | grep -oE '^(CLAUDE[A-Z_]*|MCP_[A-Z_]*)' | grep -vE '^CLAUDE_CODE_(OAUTH_SCOPES|SDK_HAS_HOST_AUTH_REFRESH|ORGANIZATION_UUID|ACCOUNT_UUID)$'); do
      unset "$v"
    done
    mkdir -p /tmp/my-channel && cd /tmp/my-channel
    export PS1='\[\e[38;5;245m\]~/my-channel\[\e[0m\] \$ '
    alias claude="claude --permission-mode default --plugin-dir '$REPO' --allowedTools 'Bash(ytk:*)' 'Bash(jq:*)' 'Bash(xargs ytk:*)'"
    ;;
  commands)
    cd /tmp
    ;;
  login)
    DEMO_HOME=$(mktemp -d)
    export DEMO_HOME
    ytk() { "$REPO/.venv/bin/python" "$DEMO/login_demo.py" "$@"; }
    ;;
esac
clear
