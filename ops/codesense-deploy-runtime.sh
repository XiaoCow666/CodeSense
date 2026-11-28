#!/usr/bin/env bash

# Sourced only by the root-owned fixed deployment wrapper. All paths and
# identities are supplied by that wrapper; the helper is also exercised by
# the UID smoke test with temporary users and stub executables.
codesense_deploy_runtime() {
    [[ "$EUID" -eq 0 ]] || {
        printf 'CodeSense deployment runtime must run as root\n' >&2
        return 1
    }
    [[ "$#" -eq 9 ]] || {
        printf 'CodeSense deployment runtime received invalid arguments\n' >&2
        return 1
    }

    local app_dir="$1"
    local runtime_python="$2"
    local deploy_user="$3"
    local app_user="$4"
    local rq_enabled="$5"
    local runuser_bin="$6"
    local systemctl_bin="$7"
    local curl_bin="$8"
    local base_url="${9%/}"

    [[ "$rq_enabled" == "0" || "$rq_enabled" == "1" ]] || {
        printf 'CodeSense deployment runtime received invalid queue configuration\n' >&2
        return 1
    }
    [[ -x "$runtime_python" ]] || {
        printf 'CodeSense deployment runtime cannot execute %s\n' "$runtime_python" >&2
        return 1
    }

    printf 'Installing Python dependencies as %s\n' "$deploy_user"
    "$runuser_bin" -u "$deploy_user" -- \
        "$runtime_python" -m pip install --disable-pip-version-check --no-cache-dir -r "$app_dir/requirements.txt"

    printf 'Running database maintenance as %s\n' "$app_user"
    "$runuser_bin" -u "$app_user" -- \
        "$runtime_python" "$app_dir/database_maintenance.py"

    printf 'Restarting CodeSense services\n'
    "$systemctl_bin" restart codesense
    if [[ "$rq_enabled" == "1" ]]; then
        "$systemctl_bin" restart codesense-ability-worker codesense-submission-worker
    else
        "$systemctl_bin" stop codesense-ability-worker codesense-submission-worker
    fi

    local endpoint healthy attempt
    for endpoint in healthz readyz; do
        healthy=0
        for attempt in {1..18}; do
            if "$curl_bin" --fail --silent --show-error --max-time 5 --output /dev/null "$base_url/$endpoint"; then
                healthy=1
                break
            fi
            sleep 5
        done
        [[ "$healthy" == "1" ]] || {
            printf 'CodeSense deployment failed: %s did not become healthy\n' "$endpoint" >&2
            return 1
        }
    done

    printf 'CodeSense is healthy at %s\n' "$(git -C "$app_dir" rev-parse HEAD 2>/dev/null || printf 'tested commit')"
}
