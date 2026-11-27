(function () {
    'use strict';

    const HEARTBEAT_MS = 12000;
    const IDLE_MS = 60000;

    function requestId() {
        return window.crypto?.randomUUID?.() ||
            Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
    }

    async function post(path, body) {
        const response = await fetch('/learning/' + path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
            keepalive: true,
        });
        const data = await response.json();
        if (!response.ok) {
            const error = new Error(data.error || '保存学习记录失败');
            error.status = response.status;
            throw error;
        }
        return data;
    }

    function create(assignmentId) {
        let attemptId = null;
        let stage = null;
        let interval = null;
        let lastActivity = Date.now();
        let ensuring = null;
        let stale = false;
        let stopped = false;
        let restartRequest = null;

        function intervalEvent(item, event, endReason) {
            return post('intervals', {
                assignment_id: assignmentId,
                attempt_id: item.attemptId,
                stage: item.stage,
                event,
                interval_key: item.key,
                end_reason: endReason,
            });
        }

        function endInterval(reason) {
            const current = interval;
            interval = null;
            if (!current) return;
            const close = () => intervalEvent(current, 'end', reason).catch(() => {});
            if (reason === 'leave') close();
            else if (current.pending) current.pending.then(close);
            else close();
        }

        function sync() {
            if (stopped || stale || !attemptId || !stage || document.visibilityState !== 'visible') return;
            if (Date.now() - lastActivity >= IDLE_MS) {
                endInterval('idle');
                return;
            }
            if (!interval) interval = { key: requestId(), stage, attemptId, started: false, pending: null };
            const current = interval;
            if (current.pending) return;
            current.pending = intervalEvent(current, current.started ? 'heartbeat' : 'start')
                .then(data => {
                    if (data.active === false) {
                        if (interval === current) interval = null;
                        return;
                    }
                    current.started = true;
                })
                .catch(error => {
                    if (error.status === 409 && attemptId === current.attemptId) {
                        stale = true;
                        if (interval === current) interval = null;
                    }
                })
                .finally(() => { current.pending = null; });
        }

        function markActivity() {
            lastActivity = Date.now();
            if (!interval) sync();
        }

        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') markActivity();
            else endInterval('hidden');
        });
        window.addEventListener('pagehide', () => endInterval('leave'));
        window.addEventListener('pageshow', markActivity);
        for (const event of ['pointerdown', 'keydown', 'input', 'scroll']) {
            document.addEventListener(event, markActivity, { capture: true, passive: true });
        }
        window.setInterval(sync, HEARTBEAT_MS);

        function bindAttempt(value) {
            if (!value || value === attemptId) return;
            endInterval('stage_changed');
            attemptId = value;
            stale = false;
            markActivity();
        }

        function ensureAttempt() {
            if (attemptId) return Promise.resolve(attemptId);
            if (!ensuring) {
                ensuring = post('attempts/ensure', { assignment_id: assignmentId })
                    .then(data => {
                        bindAttempt(data.attempt_id);
                        return attemptId;
                    })
                    .finally(() => { ensuring = null; });
            }
            return ensuring;
        }

        function setStage(value) {
            if (stage !== value) {
                endInterval('stage_changed');
                stage = value;
            }
            stopped = false;
            markActivity();
        }

        function stop(reason) {
            stopped = true;
            endInterval(reason);
        }

        async function restart() {
            const previousAttempt = await ensureAttempt();
            restartRequest ||= requestId();
            const data = await post('attempts/restart', {
                assignment_id: assignmentId,
                attempt_id: previousAttempt,
                request_id: restartRequest,
            });
            stop('stage_changed');
            bindAttempt(data.attempt_id);
            restartRequest = null;
            return data.attempt_id;
        }

        return {
            bindAttempt, ensureAttempt, setStage, stop, restart,
            markHintShown(sessionId, hintStage, eventId) {
                if (eventId) {
                    return post('hints/shown', {
                        session_id: sessionId, stage: hintStage, hint_event_id: eventId,
                    }).catch(() => {});
                }
                return Promise.resolve();
            },
        };
    }

    window.CodeSenseLearningCapture = { create, requestId };
}());
