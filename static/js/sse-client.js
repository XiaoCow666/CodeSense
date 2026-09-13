/**
 * Shared POST/fetch SSE consumer.
 *
 * The server sends JSON in `data:` lines. Network chunks are deliberately
 * decoupled from DOM updates: model providers often emit very small chunks,
 * while reparsing Markdown for every chunk can monopolize the main thread.
 */
(function () {
    const DEFAULT_DELTA_THROTTLE_MS = 50;
    const DELTA_TYPES = new Set(['delta']);

    function now() {
        return typeof performance !== 'undefined' && performance.now
            ? performance.now()
            : Date.now();
    }

    function elapsed(start, timestamp) {
        return timestamp == null ? null : Math.max(0, Math.round(timestamp - start));
    }

    function dispatchEvent(block, handlers, queueDelta, flushDelta, metrics) {
        if (!block) return;

        const dataLines = block.split(/\r?\n/)
            .filter(line => line.startsWith('data:'))
            .map(line => line.slice(5).trimStart());
        if (!dataLines.length) return;

        let payload;
        try {
            payload = JSON.parse(dataLines.join('\n'));
        } catch (error) {
            if (handlers.onParseError) handlers.onParseError(error, dataLines.join('\n'));
            return;
        }

        if (metrics.firstEventAt == null) metrics.firstEventAt = now();

        const type = payload.type;
        if (DELTA_TYPES.has(type)) {
            if (metrics.firstDeltaAt == null) metrics.firstDeltaAt = now();
            queueDelta(payload);
        } else {
            // Lifecycle/error events must observe all preceding text first.
            flushDelta();
            if (type === 'start' && handlers.onStart) handlers.onStart(payload);
            if (type === 'status' && handlers.onStatus) handlers.onStatus(payload);
            if (type === 'data' && handlers.onData) handlers.onData(payload);
            if ((type === 'error' || payload.error) && handlers.onError) {
                handlers.onError(payload);
            }
            if (type === 'done' || payload.done === true) {
                if (handlers.onDone) handlers.onDone(payload);
            }
        }

        if (handlers.onEvent) handlers.onEvent(payload);
    }

    async function consumeSSE(url, options = {}, handlers = {}) {
        const startedAt = now();
        const metrics = {
            responseAt: null,
            firstEventAt: null,
            firstDeltaAt: null,
            completedAt: null,
            failedAt: null
        };

        const configuredThrottle = Number(handlers.throttleMs);
        const throttleMs = Number.isFinite(configuredThrottle)
            ? Math.max(0, configuredThrottle)
            : DEFAULT_DELTA_THROTTLE_MS;
        let pendingDelta = null;
        let deltaTimer = null;
        let lastEvent = null;

        const emitMetrics = outcome => {
            if (!handlers.onMetrics) return;
            try {
                handlers.onMetrics({
                    outcome,
                    responseMs: elapsed(startedAt, metrics.responseAt),
                    firstEventMs: elapsed(startedAt, metrics.firstEventAt),
                    firstDeltaMs: elapsed(startedAt, metrics.firstDeltaAt),
                    durationMs: elapsed(
                        startedAt,
                        metrics.completedAt || metrics.failedAt || now()
                    )
                });
            } catch (error) {
                // Telemetry must never change the stream's error semantics.
                console.debug('SSE metrics callback failed', error);
            }
        };

        const flushDelta = () => {
            if (deltaTimer) {
                clearTimeout(deltaTimer);
                deltaTimer = null;
            }
            if (!pendingDelta) return;
            const payload = pendingDelta;
            pendingDelta = null;
            if (handlers.onDelta) handlers.onDelta(payload);
        };

        const queueDelta = payload => {
            if (throttleMs === 0) {
                if (handlers.onDelta) handlers.onDelta(payload);
                return;
            }

            const fragment = payload.content;
            if (!fragment) return;

            if (!pendingDelta) {
                pendingDelta = { ...payload, content: '' };
            }
            pendingDelta.content += String(fragment);

            // A large burst should be rendered promptly even if the provider
            // does not pause between chunks.
            if (pendingDelta.content.length >= 512) {
                flushDelta();
                return;
            }
            if (!deltaTimer) {
                deltaTimer = setTimeout(flushDelta, throttleMs);
            }
        };

        const processBuffer = (buffer, flush = false) => {
            const blocks = buffer.split(/\r?\n\r?\n/);
            const remainder = blocks.pop() || '';
            blocks.forEach(block => dispatchEvent(
                block,
                {
                    ...handlers,
                    onDone: payload => {
                        lastEvent = payload;
                        if (handlers.onDone) handlers.onDone(payload);
                    }
                },
                queueDelta,
                flushDelta,
                metrics
            ));

            if (flush && remainder.trim()) {
                dispatchEvent(
                    remainder,
                    {
                        ...handlers,
                        onDone: payload => {
                            lastEvent = payload;
                            if (handlers.onDone) handlers.onDone(payload);
                        }
                    },
                    queueDelta,
                    flushDelta,
                    metrics
                );
            }
            return flush ? '' : remainder;
        };

        try {
            const response = await fetch(url, {
                ...options,
                headers: {
                    'Accept': 'text/event-stream',
                    ...(options.headers || {})
                }
            });
            metrics.responseAt = now();

            if (!response.ok) {
                let message = `请求失败: HTTP ${response.status}`;
                try {
                    const body = await response.json();
                    message = body.message || body.error || message;
                } catch (_) {
                    // Keep the HTTP status when the server did not return JSON.
                }
                throw new Error(message);
            }
            if (!response.body || !response.body.getReader) {
                throw new Error('浏览器不支持流式响应');
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = '';

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                buffer = processBuffer(buffer);
            }
            buffer += decoder.decode();
            processBuffer(buffer, true);
            flushDelta();
            metrics.completedAt = now();
            emitMetrics('complete');
            return lastEvent;
        } catch (error) {
            // Preserve any text that arrived immediately before a broken read.
            flushDelta();
            metrics.failedAt = now();
            emitMetrics('error');
            throw error;
        }
    }

    window.consumeSSE = consumeSSE;
})();
