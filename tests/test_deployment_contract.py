from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_root_wrapper_uses_only_root_owned_runtime_for_release_steps():
    wrapper = (REPO_ROOT / "ops" / "codesense-github-deploy.sh").read_text(
        encoding="utf-8"
    )
    runtime = (REPO_ROOT / "ops" / "codesense-deploy-runtime.sh").read_text(
        encoding="utf-8"
    )

    assert '[[ "$EUID" -eq 0 ]]' in wrapper
    assert 'source "$runtime_lib"' in wrapper
    assert "codesense_deploy_runtime" in wrapper
    assert '"$runuser_bin" -u "$deploy_user"' in runtime
    assert '"$runuser_bin" -u "$app_user"' in runtime
    assert '"$systemctl_bin" restart codesense' in runtime
    assert '"$curl_bin" --fail' in runtime
    assert "/usr/sbin/runuser -u \"$app_user\"" not in wrapper


def test_deploy_uid_smoke_test_runs_the_shared_runtime_as_root():
    workflow = (REPO_ROOT / ".github" / "workflows" / "test-codesense.yml").read_text(
        encoding="utf-8"
    )
    smoke_test = REPO_ROOT / "ops" / "codesense-deployment-uid-smoke-test.sh"

    assert smoke_test.exists()
    assert "sudo -n bash ops/codesense-deployment-uid-smoke-test.sh" in workflow
