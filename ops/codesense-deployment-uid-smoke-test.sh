#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "$EUID" -ne 0 ]]; then
    printf 'Run this smoke test through sudo so it can exercise real UID changes.\n' >&2
    exit 1
fi

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_dir="$(mktemp -d)"
/usr/bin/chmod 0755 "$tmp_dir"
deploy_user="cs-deploy-smoke-${BASHPID}"
app_user="cs-app-smoke-${BASHPID}"
cleanup() {
    /usr/sbin/userdel "$deploy_user" >/dev/null 2>&1 || true
    /usr/sbin/userdel "$app_user" >/dev/null 2>&1 || true
    /usr/bin/rm -rf -- "$tmp_dir"
}
trap cleanup EXIT

/usr/sbin/useradd --system --no-create-home --shell /usr/sbin/nologin "$deploy_user"
/usr/sbin/useradd --system --no-create-home --shell /usr/sbin/nologin "$app_user"

app_dir="$tmp_dir/app"
/usr/bin/install -d -o root -g root -m 0755 "$app_dir"
/usr/bin/touch "$app_dir/requirements.txt" "$app_dir/database_maintenance.py"

log_file="$tmp_dir/commands.log"
/usr/bin/install -o root -g root -m 0666 /dev/null "$log_file"
export CODESENSE_DEPLOY_SMOKE_LOG="$log_file"
runtime_python="$tmp_dir/python-smoke"
cat > "$runtime_python" <<'PYTHON'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "${1:-}" == "-m" && "${2:-}" == "pip" && "${3:-}" == "install" ]]; then
    printf 'dependencies|%s|%s\n' "$(/usr/bin/id -u)" "$*" >> "$CODESENSE_DEPLOY_SMOKE_LOG"
elif [[ "${1:-}" == *database_maintenance.py ]]; then
    printf 'maintenance|%s|%s\n' "$(/usr/bin/id -u)" "$*" >> "$CODESENSE_DEPLOY_SMOKE_LOG"
else
    printf 'unexpected-python-call|%s|%s\n' "$(/usr/bin/id -u)" "$*" >> "$CODESENSE_DEPLOY_SMOKE_LOG"
    exit 1
fi
PYTHON
/usr/bin/chmod 0755 "$runtime_python"

systemctl_mock="$tmp_dir/systemctl"
cat > "$systemctl_mock" <<'SYSTEMCTL'
#!/usr/bin/env bash
printf 'systemctl|%s|%s\n' "$(/usr/bin/id -u)" "$*" >> "$CODESENSE_DEPLOY_SMOKE_LOG"
SYSTEMCTL
/usr/bin/chmod 0755 "$systemctl_mock"

curl_mock="$tmp_dir/curl"
cat > "$curl_mock" <<'CURL'
#!/usr/bin/env bash
printf 'health|%s|%s\n' "$(/usr/bin/id -u)" "${!#}" >> "$CODESENSE_DEPLOY_SMOKE_LOG"
CURL
/usr/bin/chmod 0755 "$curl_mock"

# shellcheck source=ops/codesense-deploy-runtime.sh
source "$repo_dir/ops/codesense-deploy-runtime.sh"
codesense_deploy_runtime \
    "$app_dir" \
    "$runtime_python" \
    "$deploy_user" \
    "$app_user" \
    "1" \
    "/usr/sbin/runuser" \
    "$systemctl_mock" \
    "$curl_mock" \
    "http://127.0.0.1:8000"

deploy_uid="$(/usr/bin/id -u "$deploy_user")"
app_uid="$(/usr/bin/id -u "$app_user")"
root_uid="$(/usr/bin/id -u root)"
mapfile -t log_lines < "$log_file"
[[ "${#log_lines[@]}" -eq 6 ]] || {
    printf 'Expected six deployment commands, observed %s.\n' "${#log_lines[@]}" >&2
    exit 1
}
[[ "${log_lines[0]}" == "dependencies|$deploy_uid|"* ]] || { printf 'Dependency installation did not run as deploy UID.\n' >&2; exit 1; }
[[ "${log_lines[1]}" == "maintenance|$app_uid|"* ]] || { printf 'Database maintenance did not run as application UID.\n' >&2; exit 1; }
[[ "${log_lines[2]}" == "systemctl|$root_uid|restart codesense" ]] || { printf 'Web service restart did not run as root.\n' >&2; exit 1; }
[[ "${log_lines[3]}" == "systemctl|$root_uid|restart codesense-ability-worker codesense-submission-worker" ]] || { printf 'Worker restart did not run as root.\n' >&2; exit 1; }
[[ "${log_lines[4]}" == "health|$root_uid|http://127.0.0.1:8000/healthz" ]] || { printf '/healthz was not checked as root.\n' >&2; exit 1; }
[[ "${log_lines[5]}" == "health|$root_uid|http://127.0.0.1:8000/readyz" ]] || { printf '/readyz was not checked as root.\n' >&2; exit 1; }

printf 'Deployment UID smoke test passed: dependency install, maintenance, restart and health probes used the intended UIDs.\n'
