#!/usr/bin/env bash
# Sourced by the BTC runner; no model calls or source mutations during inventory.
btc_wip_check() {
  python3 "$DIR/scripts/wip_preflight.py" check --repo "$ROOT" --target HEAD \
    --manifest "$STATE/wip-dispositions.json" --output "$STATE/wip-inventory.json"
}

btc_wip_startup() {
  local rc=0
  wip_recovery=0
  btc_wip_check || rc=$?
  if [ "$rc" = 3 ]; then
    wip_recovery=1
    printf '%s\n' PLAN > "$STATE/mode"
    printf '%s\n' author > "$STATE/stage"
    log 'Local work requires reconciliation; reopen PLAN author before implementation'
  elif [ "$rc" != 0 ]; then
    log 'Cannot inventory local work safely; startup stopped before model calls'
    return "$rc"
  fi
}

btc_wip_digest() {
  python3 "$DIR/scripts/wip_preflight.py" digest --inventory "$STATE/wip-inventory.json" \
    --manifest "$STATE/wip-dispositions.json"
}
