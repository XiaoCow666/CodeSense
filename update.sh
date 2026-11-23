#!/usr/bin/env bash
set -Eeuo pipefail

readonly app_dir="/var/www/codesense"
readonly runtime_python="/opt/codesense/venv/bin/python"
readonly app_user="codesense"

fail() {
    printf 'CodeSense update failed: %s\n' "$1" >&2
    exit 1
}

[[ "$#" -eq 1 ]] || fail "expected the tested main commit SHA"
readonly expected_sha="$1"
[[ "$expected_sha" =~ ^[0-9a-f]{40}$ ]] || fail "invalid commit SHA"
[[ "${CODESENSE_RQ_ENABLED:-}" == "0" || "${CODESENSE_RQ_ENABLED:-}" == "1" ]] || fail "missing queue configuration"
[[ -x "$runtime_python" ]] || fail "missing $runtime_python"

cd "$app_dir"
[[ "$(git branch --show-current)" == "main" ]] || fail "server checkout is not on main"
[[ "$(git rev-parse HEAD)" == "$expected_sha" ]] || fail "server checkout does not match the tested commit"
[[ -z "$(git status --porcelain)" ]] || fail "server checkout has local changes"

printf 'Installing Python dependencies for %s\n' "$expected_sha"
"$runtime_python" -m pip install --disable-pip-version-check --no-cache-dir -r requirements.txt

printf 'Running database maintenance\n'
/usr/sbin/runuser -u "$app_user" -- "$runtime_python" "$app_dir/database_maintenance.py"

printf 'Restarting CodeSense services\n'
/usr/bin/sudo -n /usr/bin/systemctl restart codesense
if [[ "$CODESENSE_RQ_ENABLED" == "1" ]]; then
    /usr/bin/sudo -n /usr/bin/systemctl restart codesense-ability-worker codesense-submission-worker
else
    /usr/bin/sudo -n /usr/bin/systemctl stop codesense-ability-worker codesense-submission-worker
fi

for endpoint in healthz readyz; do
    healthy=0
    for attempt in {1..18}; do
        if /usr/bin/curl --fail --silent --show-error --max-time 5 --output /dev/null "http://127.0.0.1:8000/$endpoint"; then
            healthy=1
            break
        fi
        sleep 5
    done
    [[ "$healthy" == "1" ]] || fail "$endpoint did not become healthy"
done

printf 'CodeSense is healthy at %s\n' "$expected_sha"
