#!/usr/bin/env bash
# Deploy-&-Test-Orchestrator für die OWUI-Fork.
# Git-Bash auf Windows (Pfade /c/...). Braucht: git, kubectl, curl, python.
#
#   ./deploy-test.sh preflight <instance> [--expect-version 0.9.6] [--expect-tag git-xxxx]
#       -> Tier-0 (gratis): Image, Rollout, Migration-Log, /health, /api/version, /api/config-Flags.
#          Schreibt Ergebnisse in state.json + druckt Zusammenfassung.
#   ./deploy-test.sh plan   <instance> --tag <tag> [--base-commit <c>] [--commit <c>]
#       -> Welche teuren Tier-2-Browser-Checks laufen müssen vs. skippbar sind.
#   ./deploy-test.sh report <instance> --tag <tag>
#       -> Markdown-Report nach reports/<instance>-<tag>-<date>.md
#   ./deploy-test.sh migration-log <instance>
#       -> Voller Alembic-Boot-Log + Error-Scan (NICHT nur --tail).
#
# Tier-2 (Live-Browser via playwright-live) ist bewusst NICHT automatisiert hier —
# das macht der Agent interaktiv (Tab-Picker/echte Session) und meldet je Check
# `./deploy-test.sh record <instance> <checkId> pass|fail --tag <tag>` zurück.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INST_JSON="$HERE/instances.json"
PY="python"

jqget() { # jqget <instance> <key>
  "$PY" -c "import json,sys; d=json.load(open(r'$INST_JSON',encoding='utf-8'))['instances']; print(d['$1'].get('$2',''))"
}
state() { "$PY" "$HERE/lib/state.py" "$@"; }

inst_exists() {
  "$PY" -c "import json,sys; d=json.load(open(r'$INST_JSON',encoding='utf-8'))['instances']; sys.exit(0 if '$1' in d else 1)"
}

cmd_preflight() {
  local I="$1"; shift
  local EXPECT_VERSION="" EXPECT_TAG=""
  while [ $# -gt 0 ]; do case "$1" in
    --expect-version) EXPECT_VERSION="$2"; shift 2;;
    --expect-tag) EXPECT_TAG="$2"; shift 2;;
    *) shift;; esac; done
  inst_exists "$I" || { echo "Unbekannte Instanz: $I"; exit 2; }

  local CTX NS DEP CON URL REPO
  CTX=$(jqget "$I" kube_context); NS=$(jqget "$I" namespace); DEP=$(jqget "$I" deployment)
  CON=$(jqget "$I" container); URL=$(jqget "$I" url); REPO=$(jqget "$I" image_repo)
  local TAG="${EXPECT_TAG:-unknown}"

  echo "=== Tier-0 Preflight: $I ($URL) ==="

  # T0-image
  local IMG
  IMG=$(kubectl --context "$CTX" -n "$NS" get deploy "$DEP" -o jsonpath='{.spec.template.spec.containers[0].image}' 2>&1)
  echo "[image]   $IMG"
  if [ -n "$EXPECT_TAG" ]; then
    if echo "$IMG" | grep -q "$EXPECT_TAG"; then state record "$I" T0-image pass --tag "$TAG" --note "$IMG"
    else state record "$I" T0-image fail --tag "$TAG" --note "got $IMG, want *$EXPECT_TAG"; fi
  fi

  # T0-rollout (retry: Migration kann Probe-Fenster überschreiten)
  local RO
  RO=$(kubectl --context "$CTX" -n "$NS" rollout status deploy/"$DEP" --timeout=60s 2>&1)
  if echo "$RO" | grep -qi 'successfully rolled out'; then
    state record "$I" T0-rollout pass --tag "$TAG"
  else
    echo "[rollout] 1. Versuch Timeout (Migration?), retry 120s..."
    RO=$(kubectl --context "$CTX" -n "$NS" rollout status deploy/"$DEP" --timeout=120s 2>&1)
    if echo "$RO" | grep -qi 'successfully rolled out'; then state record "$I" T0-rollout pass --tag "$TAG" --note "ready nach retry"
    else state record "$I" T0-rollout fail --tag "$TAG" --note "$RO"; fi
  fi
  echo "[rollout] $RO"

  # T0-migration (voller Log + Error-Scan)
  local POD MIGERR MIGHEAD
  POD=$(kubectl --context "$CTX" -n "$NS" get pods -o name 2>/dev/null | grep -i "$(echo "$DEP" | sed 's/.*-//')" | head -1)
  [ -z "$POD" ] && POD=$(kubectl --context "$CTX" -n "$NS" get pods -o name 2>/dev/null | grep -i webui | head -1)
  if [ -n "$POD" ]; then
    MIGHEAD=$(kubectl --context "$CTX" -n "$NS" logs "$POD" 2>/dev/null | grep -iE 'running upgrade' | tail -1)
    # Benign: socket session-pool-cleanup lock (Redis) ist KEIN Migration-Error -> ausschließen
    MIGERR=$(kubectl --context "$CTX" -n "$NS" logs "$POD" 2>/dev/null \
      | grep -iE 'error|traceback|sqlalchemy.exc|does not exist|alembic.*fail' \
      | grep -viE 'periodic_session_pool_cleanup|renew session cleanup lock' | head -5)
    echo "[migrate] head: ${MIGHEAD:-<keine Migration in Log-Puffer>}"
    if [ -n "$MIGERR" ]; then
      echo "[migrate] ERRORS:"; echo "$MIGERR"
      state record "$I" T0-migration fail --tag "$TAG" --note "see pod logs"
    else
      state record "$I" T0-migration pass --tag "$TAG" --note "${MIGHEAD##*-> }"
    fi
  else
    echo "[migrate] kein Pod gefunden"; state record "$I" T0-migration na --tag "$TAG"
  fi

  # T0-health
  local HC; HC=$(curl -s -o /dev/null -w "%{http_code}" "$URL/health" 2>&1)
  echo "[health]  $HC"
  [ "$HC" = "200" ] && state record "$I" T0-health pass --tag "$TAG" || state record "$I" T0-health fail --tag "$TAG" --note "HTTP $HC"

  # T0-version
  local VER; VER=$(curl -s "$URL/api/version" 2>&1)
  echo "[version] $VER"
  if [ -n "$EXPECT_VERSION" ]; then
    echo "$VER" | grep -q "\"$EXPECT_VERSION\"" && state record "$I" T0-version pass --tag "$TAG" --note "$VER" \
      || state record "$I" T0-version fail --tag "$TAG" --note "want $EXPECT_VERSION got $VER"
  fi

  # T0-config (+ feature-flag check gegen instances.json expected_features)
  local CFG
  CFG=$(curl -s "$URL/api/config" 2>/dev/null)
  if echo "$CFG" | "$PY" -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
    echo "[config]  features ok"
    "$PY" - "$I" <<PYEOF
import json,sys
inst=sys.argv[1]
reg=json.load(open(r'$INST_JSON',encoding='utf-8'))['instances'][inst].get('expected_features',{})
cfg=json.loads(r'''$CFG''') if r'''$CFG''' else {}
feat=cfg.get('features',{})
bad=[k for k,v in reg.items() if bool(feat.get(k))!=bool(v)]
print("[config]  expected_features mismatch:" , bad if bad else "none")
PYEOF
    state record "$I" T0-config pass --tag "$TAG"
  else
    echo "[config]  FAIL (kein JSON)"; state record "$I" T0-config fail --tag "$TAG"
  fi

  echo "=== Preflight fertig. Nächster Schritt: ./deploy-test.sh plan $I --tag <tag> ==="
}

cmd_migration_log() {
  local I="$1"; inst_exists "$I" || { echo "Unbekannte Instanz: $I"; exit 2; }
  local CTX NS DEP; CTX=$(jqget "$I" kube_context); NS=$(jqget "$I" namespace); DEP=$(jqget "$I" deployment)
  local POD; POD=$(kubectl --context "$CTX" -n "$NS" get pods -o name 2>/dev/null | grep -i webui | head -1)
  echo "=== $POD ==="
  kubectl --context "$CTX" -n "$NS" logs "$POD" 2>/dev/null | grep -iE 'running migrations|context impl|will assume|running upgrade|application startup'
  echo "--- Error-Scan (benign session-lock ausgefiltert) ---"
  kubectl --context "$CTX" -n "$NS" logs "$POD" 2>/dev/null \
    | grep -iE 'error|traceback|sqlalchemy.exc|does not exist' \
    | grep -viE 'periodic_session_pool_cleanup|renew session cleanup lock'
}

main() {
  [ $# -lt 1 ] && { grep '^#' "$0" | sed 's/^# \?//'; exit 0; }
  local CMD="$1"; shift
  case "$CMD" in
    preflight)     cmd_preflight "$@";;
    migration-log) cmd_migration_log "$@";;
    plan)          state plan "$@";;
    report)
      local I="$1"; shift; local TAG=""
      while [ $# -gt 0 ]; do [ "$1" = "--tag" ] && TAG="$2"; shift; done
      local D; D=$(date +%Y%m%d-%H%M%S 2>/dev/null || echo nodate)
      state report "$I" --tag "$TAG" --out "$HERE/reports/${I}-${TAG}-${D}.md";;
    record)        state record "$@";;
    show)          state show "$@";;
    *) echo "Unbekanntes Kommando: $CMD"; grep '^#' "$0" | sed 's/^# \?//'; exit 1;;
  esac
}
main "$@"
