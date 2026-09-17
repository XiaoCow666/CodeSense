(function (window, document) {
    'use strict';

    var MAX_ITEMS = 8;
    var STATUS_COPY = {
        grounded: {
            label: '已找到作业知识证据',
            summary: '已找到与当前作业相关的知识证据。',
            next: '展开证据详情，把问题与对应概念联系起来。'
        },
        no_result: {
            label: '暂无匹配证据',
            summary: '当前问题暂无可引用的作业知识证据。',
            next: '缩小问题，或查看作业知识焦点后继续提问。'
        },
        unavailable: {
            label: '证据暂时不可用',
            summary: '知识证据暂时不可用，但基础指导仍可继续。',
            next: '继续查看基础指导，稍后重试证据检索。'
        },
        timeout: {
            label: '证据检索超时',
            summary: '本次知识证据检索没有在时间预算内完成，基础指导仍可继续。',
            next: '继续查看基础指导，稍后重新检索证据。'
        },
        rate_limited: {
            label: '证据请求需要稍候',
            summary: '知识证据请求过于频繁，基础指导仍可继续。',
            next: '稍等片刻后重新检索证据，或先继续检查题目和代码。'
        },
        unknown: {
            label: '证据状态不可用',
            summary: '当前无法确认知识证据状态。',
            next: '继续使用基础指导，稍后重试。'
        }
    };

    function objectOrEmpty(value) {
        return value && typeof value === 'object' && !Array.isArray(value)
            ? value
            : {};
    }

    function safeText(value, fallback, limit) {
        if (typeof value !== 'string') return fallback || '';
        return value.trim().slice(0, limit || 1200);
    }

    function appendText(parent, tagName, className, value) {
        var element = document.createElement(tagName);
        if (className) element.className = className;
        element.textContent = value || '';
        parent.appendChild(element);
        return element;
    }

    function appendRetryButton(parent, container, options, view) {
        if (!view.retryable || typeof options.retryUrl !== 'string' || !options.retryUrl) {
            return;
        }

        var retry = document.createElement('button');
        retry.type = 'button';
        retry.className = 'knowledge-evidence-receipt__retry';
        retry.textContent = '重新检索证据';
        retry.setAttribute('aria-label', '重新检索作业知识证据');
        retry.addEventListener('click', function () {
            if (retry.disabled) return;
            retry.disabled = true;
            retry.setAttribute('aria-busy', 'true');
            retry.textContent = '正在重新检索…';

            var statusMessage = document.createElement('span');
            statusMessage.className = 'knowledge-evidence-receipt__retry-status';
            statusMessage.setAttribute('role', 'status');
            statusMessage.setAttribute('aria-live', 'polite');
            statusMessage.textContent = '正在重新检索作业知识证据。';
            parent.appendChild(statusMessage);

            fetch(options.retryUrl, {
                method: 'GET',
                cache: 'no-store',
                headers: { Accept: 'application/json' }
            }).then(function (response) {
                if (!response.ok) throw new Error('knowledge evidence retry failed');
                return response.json();
            }).then(function (data) {
                var nextView = data.knowledge_evidence ||
                    (data.data && data.data.knowledge_evidence) || data;
                render(container, nextView, options);
            }).catch(function () {
                retry.disabled = false;
                retry.removeAttribute('aria-busy');
                retry.textContent = '重新检索证据';
                statusMessage.textContent = '重新检索失败，请稍后再试。';
            });
        });
        parent.appendChild(retry);
    }

    function render(container, payload, options) {
        if (!container || !document || typeof container.replaceChildren !== 'function') {
            return;
        }

        options = objectOrEmpty(options);
        var source = objectOrEmpty(payload);
        var view = objectOrEmpty(source.knowledge_evidence || source);
        var status = Object.prototype.hasOwnProperty.call(STATUS_COPY, view.status)
            ? view.status
            : 'unknown';
        var copy = STATUS_COPY[status];
        var section = document.createElement('section');
        section.className = 'knowledge-evidence-receipt' + (options.compact ? ' is-compact' : '');
        section.setAttribute('data-status', status);

        var heading = safeText(options.heading, '本次回答参考的作业知识', 120);
        appendText(section, 'h4', 'knowledge-evidence-receipt__title', heading);

        var statusBox = document.createElement('div');
        statusBox.className = 'knowledge-evidence-receipt__status';
        statusBox.setAttribute('role', 'status');
        statusBox.setAttribute('aria-live', 'polite');
        statusBox.setAttribute('aria-atomic', 'true');
        appendText(statusBox, 'strong', 'knowledge-evidence-receipt__label', safeText(view.status_label, copy.label, 120));
        appendText(statusBox, 'p', 'knowledge-evidence-receipt__summary', safeText(view.summary, copy.summary, 400));
        section.appendChild(statusBox);

        var evidence = Array.isArray(view.evidence) ? view.evidence.slice(0, MAX_ITEMS) : [];
        if (status === 'grounded' && evidence.length) {
            var details = document.createElement('div');
            details.className = 'knowledge-evidence-receipt__details';
            evidence.forEach(function (item) {
                var evidenceItem = objectOrEmpty(item);
                var detail = document.createElement('details');
                detail.className = 'knowledge-evidence-receipt__detail';
                var summary = document.createElement('summary');
                appendText(summary, 'span', 'knowledge-evidence-citation', safeText(evidenceItem.citation, '证据', 32));
                appendText(summary, 'span', '', safeText(evidenceItem.title, '未命名知识证据', 240));
                detail.appendChild(summary);
                var body = document.createElement('div');
                body.className = 'knowledge-evidence-receipt__body';
                appendText(body, 'p', '', safeText(evidenceItem.content, '暂无证据摘要。', 1200));
                appendText(body, 'span', 'knowledge-evidence-detail__source', safeText(evidenceItem.source_label, '作业知识证据', 80));
                detail.appendChild(body);
                details.appendChild(detail);
            });
            section.appendChild(details);
        } else {
            var recovery = document.createElement('div');
            recovery.className = 'knowledge-evidence-receipt__recovery';
            appendText(recovery, 'p', '', safeText(view.next_step, copy.next, 400));
            appendRetryButton(recovery, container, options, view);
            section.appendChild(recovery);
        }

        container.replaceChildren(section);
    }

    window.CodeSenseKnowledgeEvidence = {
        render: render
    };
}(window, document));
