#!/usr/bin/env bash
set -Eeuo pipefail

readonly app_dir="/var/www/codesense"
readonly repo_url="https://github.com/XiaoCow666/CodeSense"
readonly deploy_user="codesense-deploy"
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
/usr/sbin/runuser -u "$deploy_user" -- /usr/bin/env "CODESENSE_RQ_ENABLED=$rq_enabled" /bin/bash "$app_dir/update.sh" "$target_sha"
