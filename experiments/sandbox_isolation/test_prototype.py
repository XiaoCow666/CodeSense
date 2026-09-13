import unittest

try:
    from .prototype import (
        bounded_capture,
        IsolationPolicy,
        LifecycleRunner,
        RecordingIsolationBackend,
        Scenario,
        Worker,
        choose_rollback_worker,
    )
except ImportError:  # pragma: no cover - supports direct file execution
    from prototype import (  # type: ignore
        bounded_capture,
        IsolationPolicy,
        LifecycleRunner,
        RecordingIsolationBackend,
        Scenario,
        Worker,
        choose_rollback_worker,
    )


class IsolationLifecycleTests(unittest.TestCase):
    def test_enrollment_precedes_launch(self):
        backend = RecordingIsolationBackend()
        result = LifecycleRunner(backend).execute(Scenario(descendant=False))

        self.assertEqual(result.status, "passed")
        self.assertLess(result.events.index("enroll:p1"), result.events.index("resume:p1"))
        self.assertTrue(result.cleanup_verified)

    def test_enrollment_failure_is_fail_closed(self):
        backend = RecordingIsolationBackend(fail_stage="enroll")
        result = LifecycleRunner(backend).execute(Scenario(descendant=False))

        self.assertEqual(result.status, "isolation_setup_failed")
        self.assertFalse(result.started)
        self.assertFalse(any(event.startswith("resume:") for event in result.events))
        self.assertTrue(result.cleanup_verified)

    def test_descendant_is_cleaned_after_normal_parent_exit(self):
        backend = RecordingIsolationBackend()
        result = LifecycleRunner(backend).execute(Scenario())

        self.assertEqual(result.status, "passed")
        self.assertIn("inherit-boundary:p2", result.events)
        self.assertIn("terminate-isolation-unit", result.events)
        self.assertTrue(result.cleanup_verified)

    def test_retained_stdout_handle_is_bounded_and_non_pass(self):
        backend = RecordingIsolationBackend()
        result = LifecycleRunner(backend).execute(
            Scenario(descendant_holds_stdout=True)
        )

        self.assertEqual(result.status, "output_collection_incomplete")
        self.assertTrue(result.stdout.bounded)
        self.assertFalse(result.stdout.complete)
        self.assertTrue(result.cleanup_verified)

    def test_retained_stderr_handle_is_bounded_and_non_pass(self):
        backend = RecordingIsolationBackend()
        result = LifecycleRunner(backend).execute(
            Scenario(stderr_chunks=(b"diagnostic\n",), descendant_holds_stderr=True)
        )

        self.assertEqual(result.status, "output_collection_incomplete")
        self.assertTrue(result.stderr.bounded)
        self.assertFalse(result.stderr.complete)
        self.assertTrue(result.cleanup_verified)

    def test_output_limit_is_explicit_failure(self):
        backend = RecordingIsolationBackend(policy=IsolationPolicy(output_limit=4))
        result = LifecycleRunner(backend).execute(
            Scenario(stdout_chunks=(b"123456789",), descendant=False)
        )

        self.assertEqual(result.status, "output_limit_exceeded")
        self.assertTrue(result.stdout.truncated)
        self.assertTrue(result.cleanup_verified)

    def test_bounded_capture_does_not_consume_after_limit(self):
        consumed = []

        def chunks():
            consumed.append("first")
            yield b"12"
            consumed.append("second")
            yield b"3456"
            consumed.append("must-not-be-read")
            yield b"7890"

        capture = bounded_capture(chunks(), 4, eof=True)

        self.assertEqual(capture.data, b"1234")
        self.assertTrue(capture.truncated)
        self.assertEqual(consumed, ["first", "second"])

    def test_unsafe_rollback_is_paused(self):
        decision = choose_rollback_worker(
            Worker("new-worker", isolation_verified=False),
            Worker("old-worker", isolation_verified=False),
        )

        self.assertEqual(decision.status, "paused_no_safe_rollback")
        self.assertIsNone(decision.worker)

    def test_rollback_can_use_only_verified_worker(self):
        decision = choose_rollback_worker(
            Worker("new-worker", isolation_verified=False),
            Worker("verified-old-worker", isolation_verified=True),
        )

        self.assertEqual(decision.status, "routed")
        self.assertEqual(decision.worker, "verified-old-worker")


if __name__ == "__main__":
    unittest.main()
