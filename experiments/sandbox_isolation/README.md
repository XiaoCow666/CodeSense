# Sandbox isolation lifecycle prototype

## Scope

This is an experiment-only prototype derived from PR #15. It is not imported by
the Flask application, `utils.sandbox_runner`, the online evaluation queue, or
any deployment entry point. It does not change production configuration and
contains no credentials.

The current target platform is Windows 11 with Python 3.10+ (validated with the
workspace Python 3.12 runtime). The prototype intentionally uses an in-memory
backend instead of Job Object/cgroup APIs. It verifies the lifecycle contract
that a real adapter must satisfy before untrusted code can run:

1. prepare the isolation boundary;
2. create the process in a non-running state;
3. enroll and verify it;
4. launch only after enrollment succeeds;
5. collect stdout/stderr with a hard byte bound and bounded EOF waiting;
6. clean the whole isolation unit on every terminal path;
7. refuse an unsafe rollback target.

This is a contract and failure-mode prototype, not proof of OS containment.
The real Windows Job Object and Linux cgroup v2 adapters require a separate
implementation PR, platform-specific security review, and responsible-owner
approval before merge or deployment.

## Reproducible commands

From the repository root:

```powershell
python -m unittest discover -s experiments -t . -p "test_*.py" -v
python -m experiments.sandbox_isolation.test_prototype
python -m compileall -q experiments/sandbox_isolation
```

No `pytest`, compiler, database, network service, or application startup is
required. The tests use only Python's standard library and write no persistent
state.

Observed on the Windows workspace with the bundled Python 3.12 runtime:

```text
python -m unittest discover -s experiments -t . -p "test_*.py" -v
Ran 9 tests in 0.000s
OK

python -m experiments.sandbox_isolation.test_prototype
Ran 9 tests in 0.000s
OK

python -m compileall -q experiments/sandbox_isolation
exit code 0
```

The first exploratory command without `-t .` was intentionally corrected after
Python reported `ImportError: attempted relative import with no known parent
package`; the package-aware commands above are the reproducible commands.

## Boundary record

| Boundary | Prototype behavior | Evidence | Not proven |
| --- | --- | --- | --- |
| Target platform | Windows 11 + Python 3.12 | standard-library unittest run | Linux runtime behavior |
| Process/PID | in-memory parent/descendant records; descendants inherit the modeled boundary | `inherit-boundary`, `terminate-isolation-unit`, `verify-empty` events | real PID/job membership |
| CPU/memory/disk | policy fields only; no quota enforcement | explicit policy object | OS quota enforcement |
| Output | stdout/stderr capped at 4096 bytes by default; retained handles produce bounded non-pass | output-limit and retained-handle tests | OS pipe behavior under real descendants |
| Network | policy records `deny-all`; no socket is opened | no network dependency in tests | firewall/namespace/egress enforcement |
| Filesystem | policy records private workdir only; no files are created | tests leave no persistent state | ACL/mount/namespace enforcement |
| Permissions | policy records low privilege/no secrets | no credential access | token/capability/ACL enforcement |
| Rollback | only a verified isolated worker may be selected; otherwise queue is paused | safe/unsafe rollback tests | real queue routing |

## Regression evidence

The tests cover:

- enrollment before launch;
- enrollment failure with no launch and cleanup attempted;
- a normal parent result with a surviving descendant;
- descendants retaining stdout or stderr handles;
- bounded output overflow as an explicit failure;
- safe rollback only to a verified worker, and fail-closed pause otherwise.

The `RecordingIsolationBackend` is deliberately observable so a future native
adapter can reuse the same lifecycle assertions without importing it into the
production path.

## Risks and unverified items

- The prototype does not create or kill real processes and cannot prove that a
  real child cannot escape a Job Object/cgroup.
- It does not enforce CPU, memory, PID, disk, filesystem, network, or Windows
  permission boundaries.
- It does not test Windows `CREATE_SUSPENDED`/`AssignProcessToJobObject` or
  Linux cgroup v2 membership and migration permissions.
- It does not validate descendants that keep native pipe handles open across a
  real process exit; the handle behavior is modeled deterministically.
- It does not change or exercise the online evaluation chain.

Any native OS isolation implementation, production integration, or deployment
must be proposed in a separate PR and approved by the responsible owner first.
