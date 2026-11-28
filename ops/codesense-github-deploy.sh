#!/usr/bin/env bash
set -Eeuo pipefail

readonly app_dir="/var/www/codesense"
readonly repo_url="https://github.com/XiaoCow666/CodeSense"
readonly deploy_user="codesense-deploy"
readonly app_user="codesense"
readonly runtime_python="/opt/codesense/venv/bin/python"
readonly runtime_lib="/usr/local/lib/codesense-deploy-runtime.sh"
readonly lock_file="/run/lock/codesense-github-deploy.lock"
readonly git_bin="/usr/bin/git"

fail() {
    printf 'CodeSense deployment refused: %s\n' "$1" >&2
    exit 1
}

[[ "$EUID" -eq 0 ]] || fail "the fixed deployment wrapper must run as root"
IFS= read -r target_sha || fail "missing tested commit SHA"
[[ "$target_sha" =~ ^[0-9a-f]{40}$ ]] || fail "invalid tested commit SHA"
if IFS= read -r extra; then
    fail "expected exactly one commit SHA"
fi

exec 9>"$lock_file"
/usr/bin/flock -n 9 || fail "another deployment is running"

[[ -d "$app_dir/.git" ]] || fail "CodeSense checkout not found"
[[ "$($git_bin -C "$app_dir" rev-parse --show-toplevel)" == "$app_dir" ]] || fail "unexpected checkout path"
[[ "$($git_bin -C "$app_dir" remote get-url origin)" == "$repo_url" ]] || fail "unexpected Git remote"
[[ "$($git_bin -C "$app_dir" branch --show-current)" == "main" ]] || fail "checkout is not on main"
[[ -z "$($git_bin -C "$app_dir" status --porcelain)" ]] || fail "checkout has local changes"

if "$git_bin" -C "$app_dir" ls-files --error-unmatch .env >/dev/null 2>&1; then
    fail ".env must not be tracked by Git"
fi
[[ -f "$app_dir/.env" && ! -L "$app_dir/.env" ]] || fail "server .env file is missing or is a symlink"

current_sha="$($git_bin -C "$app_dir" rev-parse HEAD)"
"$git_bin" -C "$app_dir" -c core.hooksPath=/dev/null fetch --no-tags --prune origin main
remote_sha="$($git_bin -C "$app_dir" rev-parse refs/remotes/origin/main)"
[[ "$remote_sha" == "$target_sha" ]] || fail "tested commit is no longer the current main commit"
"$git_bin" -C "$app_dir" merge-base --is-ancestor "$current_sha" "$target_sha" || fail "deployment is not a fast-forward"

if [[ "$current_sha" != "$target_sha" ]]; then
    "$git_bin" -C "$app_dir" -c core.hooksPath=/dev/null merge --ff-only "$target_sha"
fi
[[ "$($git_bin -C "$app_dir" rev-parse HEAD)" == "$target_sha" ]] || fail "checkout did not reach the tested commit"
[[ -z "$($git_bin -C "$app_dir" status --porcelain)" ]] || fail "checkout is not clean after update"

rq_enabled=0
if /usr/bin/grep -q '^ABILITY_ANALYSIS_QUEUE_BACKEND=rq$' "$app_dir/.env" \
    && /usr/bin/grep -q '^SUBMISSION_EVALUATION_QUEUE_BACKEND=rq$' "$app_dir/.env"; then
    rq_enabled=1
fi

printf 'Deploying tested main commit %s\n' "$target_sha"
[[ -f "$runtime_lib" && ! -L "$runtime_lib" ]] || fail "root-owned deployment runtime is missing"
[[ "$(/usr/bin/stat -c '%u:%a' "$runtime_lib")" == "0:644" ]] || fail "deployment runtime must be root-owned and read-only to non-root users"
# This helper is installed root-owned outside the Git checkout. Never source a
# helper from the repository while running as root.
# shellcheck source=/dev/null
source "$runtime_lib"
codesense_deploy_runtime \
    "$app_dir" \
    "$runtime_python" \
    "$deploy_user" \
    "$app_user" \
    "$rq_enabled" \
    "/usr/sbin/runuser" \
    "/usr/bin/systemctl" \
    "/usr/bin/curl" \
    "http://127.0.0.1:8000"
