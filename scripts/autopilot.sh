#!/usr/bin/env bash
# Reuse pinned model runners without the Alpha Sentry phase driver.
set -u
set -o pipefail
umask 077
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
STATE="$ROOT/.autopilot"
SESSION=btc5m-autopilot
SOURCE="${AUTOPILOT_HOME:-$HOME/projects/autopilot}"
PIN="${AUTOPILOT_RUNTIME_PIN:-9118335e9781548121e9baca9b32effa951f5dfe}"
BRANCH=chore/btc-autopilot
BASE=main
export GH_REPO=viliusjask/5min-btc-polymarket
export PATH="$HOME/.local/bin:$PATH"
export AUTOPILOT_VERIFY_DIR="$HOME/projects/autopilot/state/verification"
export AUTOPILOT_VERIFY_SLOTS=2
export AUTOPILOT_STOP_FILE="$STATE/STOP"
COMMAND=${1:-status}

preflight() {
  local item
  for item in bash python3 git gh codex claude tmux flock timeout uv; do
    command -v "$item" >/dev/null || { echo "Missing executable: $item" >&2; return 1; }
  done
  python3 -c 'import sys; assert sys.version_info >= (3, 10)' || return 1
  for item in lib.sh scripts/codex_events.py scripts/claude_events.py scripts/verify.sh scripts/wip_preflight.py scripts/author_session.py scripts/claude_budget.py scripts/headroom_proxy.py scripts/codex_usage.py scripts/headroom_codex.py; do
    git -C "$SOURCE" cat-file -e "$PIN:$item" || return 1
  done
  git -C "$ROOT" rev-parse --verify "fork/$BASE" >/dev/null || return 1
  [ "$(git -C "$ROOT" remote get-url fork)" = "https://github.com/$GH_REPO.git" ] \
    || { echo 'Unexpected repository fork' >&2; return 1; }
  timeout 30 gh repo view "$GH_REPO" --json nameWithOwner >/dev/null \
    || { echo 'Cannot access the fork repository' >&2; return 1; }
  [ -s "$HOME/.codex/hooks.json" ] || { echo 'Missing existing Codex hook dispatcher' >&2; return 1; }
  echo "Prerequisites available; runner $PIN; repository $GH_REPO."
}

case "$COMMAND" in
  preflight) preflight; exit $? ;;
  status)
    tmux has-session -t "=$SESSION" 2>/dev/null && echo 'Service is running.' || echo 'Service is stopped.'
    for item in status mode stage; do
      [ ! -f "$STATE/$item" ] || { printf '%s: ' "$item"; cat "$STATE/$item"; }
    done
    [ ! -f "$STATE/STOP" ] || echo 'Stop requested.'
    [ ! -f "$STATE/console.log" ] || tail -n 8 "$STATE/console.log"
    exit 0 ;;
  stop)
    mkdir -p "$STATE"; touch "$STATE/STOP"
    echo 'Stop requested after the current model call.'; exit 0 ;;
  halt)
    mkdir -p "$STATE"; touch "$STATE/STOP"
    if [ -f "$STATE/pid" ]; then
      read -r service_pid < "$STATE/pid"
      if [[ "$service_pid" =~ ^[0-9]+$ ]] && kill -0 "$service_pid" 2>/dev/null; then
        # Match the command before trusting a stale PID file.
        if python3 - "$service_pid" "$ROOT/scripts/autopilot.sh" <<'PY'
import pathlib, sys
parts = pathlib.Path('/proc', sys.argv[1], 'cmdline').read_bytes().split(b'\0')
raise SystemExit(0 if sys.argv[2].encode() in parts and b'run' in parts else 1)
PY
        then kill -TERM "$service_pid"; fi
      fi
    fi
    echo 'Stop requested; a matching active runner was signalled.'; exit 0 ;;
  resume)
    mkdir -p "$STATE"; touch "$STATE/RESUME"
    echo 'Resume requested. If stopped, use start.'; exit 0 ;;
  start)
    tmux has-session -t "=$SESSION" 2>/dev/null && { echo 'Already running.'; exit 0; }
    preflight || exit 1
    [ -s "$STATE/INBOX.md" ] || { echo "Write the authorized objective to $STATE/INBOX.md first." >&2; exit 1; }
    [ "$(git -C "$ROOT" branch --show-current)" = "$BRANCH" ] \
      || { echo "Start from the assigned $BRANCH branch." >&2; exit 1; }
    mkdir -p "$STATE"
    rm -f "$STATE/STOP"
    printf -v launch 'exec bash %q run' "$ROOT/scripts/autopilot.sh"
    tmux new-session -d -s "$SESSION" -c "$ROOT" "$launch" || exit 1
    echo "Started tmux session $SESSION."; exit 0 ;;
  run) ;;
  *) echo 'Usage: autopilot.sh {preflight|start|status|stop|halt|resume|run}' >&2; exit 2 ;;
esac

mkdir -p "$STATE"/{logs,prompts,briefing,runtime/prompts,runtime/scripts}
exec 9>"$STATE/runner.lock"
flock -n 9 || { echo 'Another runner owns this project state.' >&2; exit 1; }
printf '%s\n' "$$" > "$STATE/pid"
for item in lib.sh scripts/codex_events.py scripts/claude_events.py scripts/verify.sh scripts/wip_preflight.py scripts/author_session.py scripts/claude_budget.py scripts/headroom_proxy.py scripts/codex_usage.py scripts/headroom_codex.py; do
  git -C "$SOURCE" show "$PIN:$item" > "$STATE/runtime/$item.tmp" \
    && mv "$STATE/runtime/$item.tmp" "$STATE/runtime/$item" || exit 1
done
cp "$ROOT/docs/autopilot-prompts/operator.md" "$STATE/runtime/prompts/codex-rules.md" || exit 1
cp "$ROOT/docs/autopilot.md" "$STATE/runtime/prompts/operator-notes.md" || exit 1
DIR="$STATE/runtime"
REPO="$ROOT"
CONSOLE="$STATE/console.log"
P=0
CODEX_MODEL=gpt-6-astra
CODEX_EFFORT=high
FABLE_MODEL=claude-fable-5-1
OPUS_MODEL=claude-opus-4-8
SESSION_TIMEOUT="${SESSION_TIMEOUT:-4h}"
BRIEF="$STATE/BRIEFING.md"
child=''
# Only runner/event helpers are called. No phase, merge, DB or Alpha prompts are used.
source "$DIR/lib.sh"
CLAUDE_RULES_FILE="$DIR/prompts/codex-rules.md"
cleanup() {
  trap - EXIT TERM INT HUP
  [ -z "$child" ] || { kill_tree "$child"; wait "$child" 2>/dev/null || true; }
  printf '%s\n' stopped > "$STATE/status"
  rm -f "$STATE/pid"
}
trap 'cleanup; exit 0' TERM INT HUP
trap cleanup EXIT
pause() {
  local remaining=$1
  while (( remaining > 0 )); do
    [ ! -f "$STATE/STOP" ] || return 1
    sleep 5; remaining=$((remaining - 5))
  done
}
idle() {
  printf '%s\n' "$1" > "$STATE/status"
  log "$1; waiting for RESUME or STOP without model calls"
  while [ ! -f "$STATE/RESUME" ]; do pause 5 || return 1; done
  rm -f "$STATE/RESUME"
}
return_author() {
  printf '%s\n' author > "$STATE/stage"
}
[ -f "$STATE/mode" ] || printf '%s\n' PLAN > "$STATE/mode"
[ -f "$STATE/stage" ] || return_author
[ -f "$STATE/reviewed-head" ] || git -C "$ROOT" rev-parse HEAD > "$STATE/reviewed-head"
# Every process start reconciles the whole local repository, not only fork/main.
# A recovery author may merge relevant existing branches into this assigned branch.
# Its dispositions are bound to the final snapshot; previous plan approval cannot
# authorize implementation against a newly discovered code baseline.
source "$ROOT/scripts/autopilot-wip.sh"
btc_wip_startup || exit $?
failures=0
stalled=0
while [ ! -f "$STATE/STOP" ]; do
  branch=$(git -C "$ROOT" branch --show-current)
  [ "$branch" = "$BRANCH" ] || { log "Refusing unexpected branch $branch"; break; }
  [ -s "$STATE/INBOX.md" ] || { idle "missing authorized objective in INBOX.md" || break; continue; }
  read -r mode < "$STATE/mode"
  read -r stage < "$STATE/stage"
  [[ "$mode" =~ ^(PLAN|BUILD|INTEGRATION)$ && "$stage" =~ ^(author|reviewer)$ ]] \
    || { log 'Invalid durable stage state'; break; }
  timeout 60 git -C "$ROOT" fetch -q fork "$BASE" || { idle "fork fetch failed; check network/authentication" || break; continue; }
  head=$(git -C "$ROOT" rev-parse HEAD)
  base=$(git -C "$ROOT" rev-parse "fork/$BASE")
  if [ "$stage" = reviewer ] && ! git -C "$ROOT" merge-base --is-ancestor "$base" "$head"; then
    log 'Branch does not contain current fork/main; return to author to integrate it'
    return_author
    continue
  fi
  wip_review_snapshot=''
  if [ "$mode" = PLAN ] && [ "$stage" = reviewer ] && [ -f "$STATE/wip-dispositions.json" ]; then
    if ! btc_wip_check; then
      wip_recovery=1
      return_author
      continue
    fi
    wip_review_snapshot=$(btc_wip_digest) || break
  fi
  if [ "$stage" = reviewer ]; then
    git -C "$ROOT" diff --no-ext-diff "$base...$head" > "$STATE/review.diff" || break
    git -C "$ROOT" log --format='%h %s' "$base..$head" > "$STATE/review-commits.txt" || break
    if ! timeout 30 gh pr view "$BRANCH" --repo "$GH_REPO" --json body,comments,reviews > "$STATE/pr-review-context.json.tmp" 2>/dev/null; then
      printf '%s\n' '{"note":"No accessible PR context; evaluate local committed evidence."}' > "$STATE/pr-review-context.json.tmp"
    fi
    mv "$STATE/pr-review-context.json.tmp" "$STATE/pr-review-context.json"
  fi
  name="$(date +%Y%m%d-%H%M%S-%N)-$mode-$stage"
  result="$STATE/logs/$name.json"
  output="$STATE/logs/$name.last.txt"
  prompt=$(cat "$ROOT/docs/autopilot-prompts/$stage.md")
  prompt+=$'\n'"Mode: $mode. Assigned branch: $BRANCH. Base branch: $BASE."
  if [ "$wip_recovery" = 1 ]; then
    prompt+=$'\n'"LOCAL WORK RECOVERY REQUIRED. Read $STATE/wip-inventory.json. Reconcile every outstanding local branch and dirty worktree under the author recovery rules. Use python3 $DIR/scripts/wip_preflight.py scan/check/record; target HEAD, manifest $STATE/wip-dispositions.json. After your final commit and push, scan a fresh inventory and record exact dispositions. Reassess the research plan against the recovered implementation. The wrapper will not advance to review until check passes."
  fi
  prompt+=$'\n'"reviewed_head=$head reviewed_base=$base"
  prompt+=$'\n'"Local work inventory and author dispositions: $STATE/wip-inventory.json, $STATE/wip-dispositions.json. Independently verify inclusion and any deferrals during PLAN review."
  prompt+=$'\n'"Prior review if present: $STATE/review.json. Wrapper snapshots of exact commits: $STATE/review.diff, $STATE/review-commits.txt, $STATE/pr-review-context.json. Output artifact: $result."
  printf '%s\n' "running $mode $stage" > "$STATE/status"
  prompt+=$'\n'"Objective: $STATE/INBOX.md. Verification feedback if present: $STATE/gate-failure.log. Briefing: $STATE/BRIEFING.md."
  STAGE_SANDBOX=danger-full-access
  [ "$stage" != reviewer ] || STAGE_SANDBOX=read-only
  runner=run_codex
  CODEX_EFFORT=high
  STAGE_READ_ONLY=0
  [ "$stage" != reviewer ] || STAGE_READ_ONLY=1
  if [ "$mode" = PLAN ] && [ "$stage" = author ]; then
    runner=run_claude; CLAUDE_MODEL="$FABLE_MODEL"; CLAUDE_EFFORT=medium
  elif [ "$mode" = BUILD ] && [ "$stage" = author ]; then
    runner=run_claude; CLAUDE_MODEL="$OPUS_MODEL"; CLAUDE_EFFORT=medium
  elif [ "$mode" = INTEGRATION ] && [ "$stage" = reviewer ] && [ "$(cat "$STATE/integration-reviewer" 2>/dev/null || echo fable)" = fable ]; then
    runner=run_claude; CLAUDE_MODEL="$FABLE_MODEL"; CLAUDE_EFFORT=high
  fi
  AUTHOR_SESSION_KEY=''
  AUTHOR_CORRECTION_PROMPT=''
  if [ "$stage" = author ]; then
    AUTHOR_SESSION_KEY=$(python3 "$ROOT/scripts/autopilot_result.py" author-key \
      "$STATE/author-session-stage.json" "$mode") || break
    AUTHOR_CORRECTION_PROMPT="Continue the same $mode author stage on $BRANCH. Current head=$head, base=$base. Preserve interrupted edits. Address the current independent findings and verification feedback; inspect affected code and changed sections. Do not repeat completed research or reread unchanged photos. Update evidence/briefing, verify the affected work, commit and push before handoff. Delegation to bounded subagents remains allowed; retain independent author/reviewer roles."
    [ ! -s "$STATE/review.json" ] || AUTHOR_CORRECTION_PROMPT+=$'\n'"Latest review (check its head/stage before treating it as current): $(cat "$STATE/review.json")"
    AUTHOR_CORRECTION_PROMPT+=$'\n'"Current task/authority: $STATE/INBOX.md. Gate feedback: $STATE/gate-failure.log. Briefing: $BRIEF. Return the current structured result contract; reviewed_head=$head reviewed_base=$base."
    if [ "$wip_recovery" = 1 ]; then
      AUTHOR_CORRECTION_PROMPT+=$'\n'"Startup recovery is active: inspect $STATE/wip-inventory.json; reconcile new items, preserve known prior dispositions, then refresh and record exact dispositions after your final commit/push using $DIR/scripts/wip_preflight.py. Do not redo unchanged completed recovery work."
    fi
  fi
  routed_model="$CODEX_MODEL/$CODEX_EFFORT"
  [ "$runner" != run_claude ] || routed_model="$CLAUDE_MODEL/$CLAUDE_EFFORT"
  log "Starting $mode $stage at $head ($routed_model; $runner)"
  "$runner" "$ROOT" "$name" "$output" "$prompt" "$ROOT/scripts/autopilot-stage.schema.json" "$result" &
  child=$!
  wait "$child"; rc=$?
  child=''
  log "$mode $stage exited $rc"
  status=''
  if [ "$rc" = 0 ]; then
    status=$(python3 "$ROOT/scripts/autopilot_result.py" result "$result" "$stage" "$head" "$base") || rc=1
  fi
  if [ "$rc" != 0 ]; then
    [ ! -f "$STATE/STOP" ] || break
    classifier=codex_events.py
    [ "$runner" != run_claude ] || classifier=claude_events.py
    failure_kind=$(python3 "$DIR/scripts/$classifier" --failure-kind "$output")
    if [ "$failure_kind" = quota ]; then
      log 'Assigned model quota unavailable; retrying in 10 minutes without fallback'; pause 600 || break; continue
    fi
    if [ "$failure_kind" = auth ]; then
      idle 'authentication required' || break; continue
    fi
    failures=$((failures + 1))
    if (( failures >= 3 )); then
      idle 'stage repeatedly failed; see logs' || break; failures=0
    else pause 30 || break; fi
    continue
  fi
  if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
    log 'Stage left uncommitted changes; return to author to preserve and checkpoint them'
    return_author
    failures=$((failures + 1))
    if (( failures >= 3 )); then idle 'repeatedly uncommitted stage output' || break; failures=0; fi
    pause 30 || break; continue
  fi
  if [ "$wip_recovery" = 1 ]; then
    if ! btc_wip_check; then
      log 'Local work remains unreconciled; repeat PLAN recovery with refreshed inventory'
      return_author
      pause 30 || break
      continue
    fi
    wip_recovery=0
    log 'Local work inventory reconciled; independent plan review is still required'
  fi
  current=$(git -C "$ROOT" rev-parse HEAD)
  if [ "$stage" = author ] && [ "$status" = waiting ] && [ "$current" = "$head" ]; then
    cp "$result" "$STATE/author.json"
    idle 'author waiting; see local briefing and author result' || break
    failures=0; stalled=0
    continue
  fi
  if [ "$stage" = author ] && [ "$current" = "$head" ]; then
    stalled=$((stalled + 1))
    if (( stalled >= 3 )); then
      idle 'author repeatedly reported continuation without a checkpoint' || break
      stalled=0
      continue
    elif [ "$status" = continue ] || [ "$mode" = PLAN ]; then
      log 'Author made no checkpoint; retrying the same author stage'
      pause 30 || break
      continue
    fi
  elif [ "$stage" = author ]; then
    stalled=0
  fi
  if [ -n "$wip_review_snapshot" ]; then
    if ! btc_wip_check || [ "$(btc_wip_digest)" != "$wip_review_snapshot" ]; then
      log 'Local work or dispositions changed during PLAN review; approval invalidated'
      wip_recovery=1
      return_author
      continue
    fi
  fi
  if [ "$stage" = reviewer ] && [ "$current" != "$head" ]; then
    idle 'reviewer changed HEAD; review evidence invalid' || break; continue
  fi
  timeout 60 git -C "$ROOT" fetch -q fork "$BASE" || { idle "fork fetch failed; check network/authentication" || break; continue; }
  if [ "$stage" = reviewer ] && [ "$(git -C "$ROOT" rev-parse "fork/$BASE")" != "$base" ]; then
    log 'Base changed during review; author must integrate current fork/main before rereview'
    return_author
    continue
  fi
  remote=$(timeout 60 git -C "$ROOT" ls-remote --heads fork "$BRANCH") || { idle 'cannot read fork branch; check network/authentication' || break; continue; }
  if [ "${remote%%[[:space:]]*}" != "$current" ]; then
    log 'Branch is not pushed; returning to author'
    return_author
    failures=$((failures + 1))
    if (( failures >= 3 )); then idle 'branch repeatedly not pushed' || break; failures=0; fi
    pause 30 || break; continue
  fi
  failures=0
  if [ "$stage" = author ]; then
    cp "$result" "$STATE/author.json"
    printf '%s\n' reviewer > "$STATE/stage"
  else
    cp "$result" "$STATE/review.json"
    # Only accepted current-revision evidence completes the initial Fable review.
    [ "$mode" != INTEGRATION ] || printf '%s\n' astra > "$STATE/integration-reviewer"
    printf '%s\n' "$head" > "$STATE/reviewed-head"
    return_author
    if [ "$status" = approved ] && [ "$mode" != PLAN ]; then
      gate_log="$STATE/logs/$name.gate.log"
      log "Running mandatory BTC verification for reviewed HEAD $head"
      (cd "$ROOT" && timeout 90m bash "$DIR/scripts/verify.sh" bash "$ROOT/scripts/autopilot-gate.sh") > "$gate_log" 2>&1 &
      child=$!
      wait "$child"; gate_rc=$?
      child=''
      [ ! -f "$STATE/STOP" ] || break
      if [ "$gate_rc" != 0 ]; then
        cp "$gate_log" "$STATE/gate-failure.log"
        log "Verification failed; author will receive $STATE/gate-failure.log"
        failed_revision="$head $base"
        if [ -f "$STATE/failed-gate-revision" ] && [ "$(cat "$STATE/failed-gate-revision")" = "$failed_revision" ]; then
          idle 'verification failed again on identical commits; see gate-failure.log' || break
        fi
        printf '%s\n' "$failed_revision" > "$STATE/failed-gate-revision"
        continue
      fi
      timeout 60 git -C "$ROOT" fetch -q fork "$BASE" || { idle 'fetch failed after verification' || break; continue; }
      remote=$(timeout 60 git -C "$ROOT" ls-remote --heads fork "$BRANCH") || { idle 'cannot verify pushed branch' || break; continue; }
      if ! git -C "$ROOT" merge-base --is-ancestor "$base" "$head" || [ "$(git -C "$ROOT" rev-parse HEAD)" != "$head" ] || [ "$(git -C "$ROOT" rev-parse "fork/$BASE")" != "$base" ] || [ "${remote%%[[:space:]]*}" != "$head" ] || [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
        log 'Revision or cleanliness changed during verification; repeat author/review'
        continue
      fi
      rm -f "$STATE/gate-failure.log" "$STATE/failed-gate-revision"
      printf '%s %s %s\n' "$head" "$base" "$gate_log" > "$STATE/verified"
    fi
    if [ "$status" = approved ]; then
      if [ "$mode" = PLAN ]; then
        printf '%s\n' BUILD > "$STATE/mode"
      elif [ "$mode" = BUILD ]; then
        author_status=$(python3 "$ROOT/scripts/autopilot_result.py" result "$STATE/author.json" author '' '') || break
        if [ "$author_status" = complete ]; then
          printf '%s\n' INTEGRATION > "$STATE/mode"
          printf '%s\n' fable > "$STATE/integration-reviewer"
          printf '%s\n' reviewer > "$STATE/stage"
        elif [ "$author_status" = waiting ]; then
          idle 'waiting after fresh BUILD review; see the local briefing' || break
        fi
      else
        cp "$STATE/verified" "$STATE/integration-verified"
        # Resume begins new planning; do not invent further work while idle.
        printf '%s\n' PLAN > "$STATE/mode"
        printf '%s\n' author > "$STATE/stage"
        idle 'complete after independent integration review and verification; see local briefing' || break
      fi
    fi
  fi
done
