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
            var recovery = document.createElement('p');
            recovery.className = 'knowledge-evidence-receipt__recovery';
            recovery.textContent = safeText(view.next_step, copy.next, 400);
            section.appendChild(recovery);
        }

        container.replaceChildren(section);
    }

    window.CodeSenseKnowledgeEvidence = {
        render: render
    };
}(window, document));
