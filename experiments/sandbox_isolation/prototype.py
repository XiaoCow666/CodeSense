"""A safe, OS-API-free isolation lifecycle prototype.

The prototype models the sequencing and fail-closed contract required before a
real Job Object/cgroup adapter is approved. It deliberately does not create OS
process groups, call Job Object/cgroup APIs, change permissions, or connect to
the application sandbox.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional


class BoundaryError(RuntimeError):
    """Raised when the isolation lifecycle cannot proceed safely."""


@dataclass(frozen=True)
class IsolationPolicy:
    """The boundary contract that a future platform adapter must implement."""

    network: str = "deny-all"
    filesystem: str = "private-workdir-only"
    permissions: str = "low-privilege-no-secrets"
    pid_limit: int = 8
    output_limit: int = 4096


@dataclass(frozen=True)
class Scenario:
    """A deterministic scenario used by the lifecycle regression tests."""

    stdout_chunks: tuple[bytes, ...] = (b"42\n",)
    stderr_chunks: tuple[bytes, ...] = ()
    exit_code: int = 0
    descendant: bool = True
    descendant_holds_stdout: bool = False
    descendant_holds_stderr: bool = False


@dataclass(frozen=True)
class Capture:
    data: bytes
    truncated: bool
    complete: bool
    bounded: bool = True


@dataclass(frozen=True)
class RunResult:
    status: str
    started: bool
    launched: bool
    stdout: Capture
    stderr: Capture
    cleanup_verified: bool
    events: tuple[str, ...]
    error: str = ""


def bounded_capture(
    chunks: Iterable[bytes], limit: int, *, eof: bool
) -> Capture:
    """Capture at most ``limit`` bytes without waiting for an inherited handle.

    ``complete`` is false when a descendant retains the pipe handle. A real
    runner must then return a non-pass result after its bounded observation
    window; it must not wait forever for EOF.
    """

    if limit <= 0:
        raise ValueError("limit must be positive")

    captured = bytearray()
    truncated = False
    for chunk in chunks:
        remaining = limit - len(captured)
        if remaining <= 0:
            truncated = True
            break
        if len(chunk) > remaining:
            captured.extend(chunk[:remaining])
            truncated = True
            break
        captured.extend(chunk)

    return Capture(
        data=bytes(captured),
        truncated=truncated,
        complete=eof,
    )


@dataclass
class _Process:
    process_id: str
    parent_id: Optional[str] = None
    enrolled: bool = False
    launched: bool = False
    alive: bool = True


@dataclass
class RecordingIsolationBackend:
    """In-memory stand-in for a future Windows/Linux isolation adapter."""

    policy: IsolationPolicy = field(default_factory=IsolationPolicy)
    fail_stage: Optional[str] = None
    events: list[str] = field(default_factory=list)
    boundary_ready: bool = False
    processes: dict[str, _Process] = field(default_factory=dict)
    open_pipes: set[str] = field(default_factory=set)
    _next_id: int = 0

    def _fail_if_requested(self, stage: str) -> None:
        if self.fail_stage == stage:
            raise BoundaryError(f"forced failure at {stage}")

    def prepare(self) -> None:
        self._fail_if_requested("prepare")
        self.boundary_ready = True
        self.events.append("prepare-boundary")

    def create_suspended(self) -> str:
        if not self.boundary_ready:
            raise BoundaryError("process creation attempted before boundary setup")
        self._next_id += 1
        process_id = f"p{self._next_id}"
        self.processes[process_id] = _Process(process_id=process_id)
        self.events.append(f"create-suspended:{process_id}")
        return process_id

    def enroll(self, process_id: str) -> None:
        self._fail_if_requested("enroll")
        process = self.processes[process_id]
        if not self.boundary_ready:
            raise BoundaryError("enrollment attempted before boundary setup")
        process.enrolled = True
        self.events.append(f"enroll:{process_id}")

    def launch(self, process_id: str) -> None:
        self._fail_if_requested("launch")
        process = self.processes[process_id]
        if not process.enrolled:
            raise BoundaryError("launch attempted before enrollment")
        process.launched = True
        self.events.append(f"resume:{process_id}")

    def spawn_descendant(self, parent_id: str) -> str:
        parent = self.processes[parent_id]
        if not parent.launched:
            raise BoundaryError("descendant created before parent launch")
        self._next_id += 1
        child_id = f"p{self._next_id}"
        self.processes[child_id] = _Process(
            process_id=child_id,
            parent_id=parent_id,
            enrolled=True,
            launched=True,
        )
        self.events.append(f"inherit-boundary:{child_id}")
        return child_id

    def hold_pipe(self, process_id: str, stream: str) -> None:
        if process_id not in self.processes:
            raise BoundaryError(f"unknown process {process_id}")
        self.open_pipes.add(f"{process_id}:{stream}")
        self.events.append(f"hold-pipe:{process_id}:{stream}")

    def cleanup(self) -> None:
        self._fail_if_requested("cleanup")
        self.events.append("terminate-isolation-unit")
        for process in self.processes.values():
            process.alive = False
        self.events.append("close-output-handles")
        self.open_pipes.clear()
        self.processes.clear()
        self.boundary_ready = False
        self.events.append("verify-empty")

    def is_empty(self) -> bool:
        return not self.processes and not self.open_pipes and not self.boundary_ready


ScenarioHook = Callable[[RecordingIsolationBackend, str], None]


class LifecycleRunner:
    """Runs the lifecycle contract and always attempts unit cleanup."""

    def __init__(self, backend: RecordingIsolationBackend):
        self.backend = backend

    def execute(self, scenario: Scenario, hook: Optional[ScenarioHook] = None) -> RunResult:
        stdout = bounded_capture((), self.backend.policy.output_limit, eof=True)
        stderr = bounded_capture((), self.backend.policy.output_limit, eof=True)
        started = False
        launched = False
        process_id: Optional[str] = None
        status = "failed"
        error = ""

        try:
            self.backend.prepare()
            process_id = self.backend.create_suspended()
            self.backend.enroll(process_id)
            self.backend.launch(process_id)
            started = True
            launched = True

            if scenario.descendant:
                descendant_id = self.backend.spawn_descendant(process_id)
                if scenario.descendant_holds_stdout:
                    self.backend.hold_pipe(descendant_id, "stdout")
                if scenario.descendant_holds_stderr:
                    self.backend.hold_pipe(descendant_id, "stderr")

            if hook is not None:
                hook(self.backend, process_id)

            stdout = bounded_capture(
                scenario.stdout_chunks,
                self.backend.policy.output_limit,
                eof=not scenario.descendant_holds_stdout,
            )
            stderr = bounded_capture(
                scenario.stderr_chunks,
                self.backend.policy.output_limit,
                eof=not scenario.descendant_holds_stderr,
            )
            expected = stdout.data.rstrip().decode("utf-8", errors="replace") == "42"
            if scenario.exit_code != 0:
                status = "runtime_error"
            elif stdout.truncated or stderr.truncated:
                status = "output_limit_exceeded"
            elif not stdout.complete or not stderr.complete:
                status = "output_collection_incomplete"
            elif expected:
                status = "passed"
            else:
                status = "wrong_output"
        except BoundaryError as exc:
            status = "isolation_setup_failed"
            error = str(exc)
        finally:
            try:
                self.backend.cleanup()
            except BoundaryError as exc:
                status = "cleanup_failed"
                error = str(exc)

        cleanup_verified = self.backend.is_empty()
        if not cleanup_verified and status != "cleanup_failed":
            status = "cleanup_failed"
            error = "isolation unit is not empty after cleanup"

        return RunResult(
            status=status,
            started=started,
            launched=launched,
            stdout=stdout,
            stderr=stderr,
            cleanup_verified=cleanup_verified,
            events=tuple(self.backend.events),
            error=error,
        )


@dataclass(frozen=True)
class Worker:
    name: str
    isolation_verified: bool
    available: bool = True


@dataclass(frozen=True)
class RouteDecision:
    status: str
    worker: Optional[str]


def choose_rollback_worker(preferred: Worker, fallback: Optional[Worker]) -> RouteDecision:
    """Fail closed when no verified isolated rollback target exists."""

    for candidate in (preferred, fallback):
        if candidate is not None and candidate.available and candidate.isolation_verified:
            return RouteDecision(status="routed", worker=candidate.name)
    return RouteDecision(status="paused_no_safe_rollback", worker=None)
