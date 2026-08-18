#!/usr/bin/env bash
# Dev helper: run a throw-away Home Assistant in Docker with this integration
# mounted, and obtain a *fresh* access token every time (HA access tokens
# expire after 30 min, so never reuse one from a previous run).
#
# Usage:
#   source scripts/ha_test.sh          # start HA + export TOKEN / hass_api helper
#   hass_api GET  /api/states
#   hass_api POST /api/config/config_entries/flow '{"handler":"ivago"}'
#   ha_stop                             # remove the container
#
# Or run directly for a smoke test:  bash scripts/ha_test.sh --smoke
#
# Requirements: Docker Desktop running, curl, python (py launcher on Windows).

set -u

HA_IMAGE="${HA_IMAGE:-ghcr.io/home-assistant/home-assistant:stable}"
HA_NAME="${HA_NAME:-hatest}"
HA_PORT="${HA_PORT:-8123}"
HA_URL="http://localhost:${HA_PORT}"
HA_CLIENT_ID="${HA_URL}/"
HA_USER="${HA_USER:-test}"
HA_PASS="${HA_PASS:-testtest123}"

_repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
_repo_dir_win="$(cd "$_repo_dir" && pwd -W 2>/dev/null || echo "$_repo_dir")"
HA_CONFIG_DIR="${HA_CONFIG_DIR:-${TMPDIR:-/tmp}/ha_ivago_test_config}"
_cfg_win="$(mkdir -p "$HA_CONFIG_DIR" && cd "$HA_CONFIG_DIR" && pwd -W 2>/dev/null || echo "$HA_CONFIG_DIR")"

_py() { if command -v py >/dev/null 2>&1; then py -3 "$@"; else python3 "$@"; fi; }
_json() { _py -c "import sys,json;d=json.load(sys.stdin);print(eval(sys.argv[1]))" "$1"; }

ha_start() {
  cat > "$HA_CONFIG_DIR/configuration.yaml" <<'EOF'
homeassistant:
  name: Test
  time_zone: Europe/Brussels
  unit_system: metric
  currency: EUR
  country: BE
frontend:
api:
logger:
  default: warning
  logs:
    custom_components.ivago: debug
EOF
  docker rm -f "$HA_NAME" >/dev/null 2>&1
  MSYS_NO_PATHCONV=1 docker run -d --name "$HA_NAME" -p "${HA_PORT}:8123" \
    -v "${_cfg_win}:/config" \
    -v "${_repo_dir_win}/custom_components:/config/custom_components" \
    "$HA_IMAGE" >/dev/null
  echo "Waiting for HA at $HA_URL ..."
  # /api/onboarding -> 200 on a fresh instance, 404 once onboarding is done;
  # /api/ -> 401 (unauthorized) as soon as the API is up.
  local i code=000
  for i in $(seq 1 120); do
    code=$(curl -s -o /dev/null -w "%{http_code}" "$HA_URL/api/")
    [ "$code" = "401" ] || [ "$code" = "200" ] && break
    sleep 2
  done
  [ "$code" = "401" ] || [ "$code" = "200" ] || { echo "HA did not come up (last http $code)"; return 1; }
}

# Always obtain a *new* access token: onboarding on a fresh instance,
# otherwise the normal login flow. Exports TOKEN.
ha_login() {
  local code
  local user_done
  if [ "$(curl -s -o /dev/null -w "%{http_code}" "$HA_URL/api/onboarding")" = "200" ]; then
    user_done=$(curl -s "$HA_URL/api/onboarding" | _json "[s['done'] for s in d if s['step']=='user'][0]")
  else
    user_done=True   # onboarding endpoints gone -> instance already onboarded
  fi
  if [ "$user_done" = "False" ]; then
    code=$(curl -s -X POST "$HA_URL/api/onboarding/users" -H "Content-Type: application/json" \
      -d "{\"client_id\":\"$HA_CLIENT_ID\",\"name\":\"Test\",\"username\":\"$HA_USER\",\"password\":\"$HA_PASS\",\"language\":\"nl\"}" \
      | _json "d['auth_code']")
  else
    local fid
    fid=$(curl -s -X POST "$HA_URL/auth/login_flow" -H "Content-Type: application/json" \
      -d "{\"client_id\":\"$HA_CLIENT_ID\",\"handler\":[\"homeassistant\",null],\"redirect_uri\":\"$HA_CLIENT_ID\"}" \
      | _json "d['flow_id']")
    code=$(curl -s -X POST "$HA_URL/auth/login_flow/$fid" -H "Content-Type: application/json" \
      -d "{\"client_id\":\"$HA_CLIENT_ID\",\"username\":\"$HA_USER\",\"password\":\"$HA_PASS\"}" \
      | _json "d['result']")
  fi
  TOKEN=$(curl -s -X POST "$HA_URL/auth/token" \
    -d "grant_type=authorization_code&code=$code&client_id=$HA_CLIENT_ID" | _json "d['access_token']")
  export TOKEN
  TOKEN_TIME=$(date +%s); export TOKEN_TIME
  if [ "$user_done" = "False" ]; then
    # finish onboarding so the instance behaves like a normal one
    curl -s -X POST "$HA_URL/api/onboarding/core_config" -H "Authorization: Bearer $TOKEN" -o /dev/null
    curl -s -X POST "$HA_URL/api/onboarding/analytics"   -H "Authorization: Bearer $TOKEN" -o /dev/null
    curl -s -X POST "$HA_URL/api/onboarding/integration" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
      -d "{\"client_id\":\"$HA_CLIENT_ID\",\"redirect_uri\":\"${HA_CLIENT_ID}?auth_callback=1\"}" -o /dev/null
  fi
  echo "Logged in, token length ${#TOKEN}"
}

# hass_api METHOD PATH [JSON_BODY] — re-logs in automatically when the token
# is older than 25 minutes.
hass_api() {
  local method="$1" path="$2" body="${3:-}"
  if [ -z "${TOKEN:-}" ] || [ $(( $(date +%s) - ${TOKEN_TIME:-0} )) -gt 1500 ]; then
    ha_login >&2
  fi
  if [ -n "$body" ]; then
    curl -s -X "$method" "$HA_URL$path" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "$body"
  else
    curl -s -X "$method" "$HA_URL$path" -H "Authorization: Bearer $TOKEN"
  fi
}

ha_logs() { docker logs "$HA_NAME" 2>&1 | grep -iE "ivago|error|traceback" | grep -viE "custom integration|rich/segment"; }
ha_stop() { docker rm -f "$HA_NAME" >/dev/null 2>&1 && echo "container removed"; }

# Smoke test: add an address through the config flow and dump the ivago states.
ha_smoke() {
  local street="${1:-Kortrijksesteenweg (GENT)}" number="${2:-10}"
  local fid res
  fid=$(hass_api POST /api/config/config_entries/flow '{"handler":"ivago"}' | _json "d['flow_id']")
  res=$(hass_api POST "/api/config/config_entries/flow/$fid" "{\"street_query\":\"$street\",\"number\":\"$number\"}")
  echo "$res" | _json "(d['type'], d.get('step_id'), d.get('errors'), d.get('reason'), d.get('title'))"
  sleep 3
  hass_api GET /api/states | _py -c "
import sys,json
for s in json.load(sys.stdin):
    if 'ivago' in s['entity_id']:
        print(s['entity_id'], '=>', s['state'])"
}

if [ "${1:-}" = "--smoke" ]; then
  ha_start && ha_login && ha_smoke && ha_logs; ha_stop
fi
