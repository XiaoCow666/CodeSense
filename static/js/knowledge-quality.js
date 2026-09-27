(function (window, document) {
    'use strict';

    var STATUS_LABELS = {
        grounded: '有证据',
        no_result: '无匹配',
        unavailable: '不可用',
        timeout: '超时',
        rate_limited: '限流'
    };

    function objectOrEmpty(value) {
        return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
    }

    function numberOrZero(value) {
        return typeof value === 'number' && isFinite(value) ? value : 0;
    }

    function setField(card, name, value) {
        var field = card.querySelector('[data-quality-field="' + name + '"]');
        if (field) field.textContent = String(value);
    }

    function renderMap(target, values, labels) {
        if (!target) return;
        target.replaceChildren();
        var entries = Object.keys(objectOrEmpty(values)).sort().slice(0, 12);
        if (!entries.length) {
            var empty = document.createElement('span');
            empty.className = 'knowledge-quality-card__chip';
            empty.textContent = '暂无样本';
            target.appendChild(empty);
            return;
        }
        entries.forEach(function (key) {
            var chip = document.createElement('span');
            chip.className = 'knowledge-quality-card__chip';
            chip.textContent = (labels[key] || key) + '：' + numberOrZero(values[key]);
            target.appendChild(chip);
        });
    }

    function render(card, payload) {
        var data = objectOrEmpty(payload.data || payload);
        var quality = objectOrEmpty(data.quality);
        var statusCounts = objectOrEmpty(quality.status_counts);
        var status = card.querySelector('#knowledge-quality-status');
        setField(card, 'requests', numberOrZero(quality.requests));
        setField(card, 'mean_latency_ms', numberOrZero(quality.mean_latency_ms));
        setField(card, 'latency_sample_count', numberOrZero(quality.latency_sample_count));
        setField(card, 'retrieval_timeout', numberOrZero(statusCounts.timeout));
        setField(card, 'rate_limited', numberOrZero(statusCounts.rate_limited));
        renderMap(card.querySelector('#knowledge-quality-status-counts'), statusCounts, STATUS_LABELS);
        renderMap(card.querySelector('#knowledge-quality-mode-counts'), quality.mode_counts, {});
        if (status) status.textContent = '状态已更新。仅含聚合指标，不含查询、代码或学生身份。';
    }

    function load(card, button) {
        var endpoint = card.getAttribute('data-endpoint');
        var status = card.querySelector('#knowledge-quality-status');
        if (!endpoint) return;
        button.disabled = true;
        if (status) {
            status.setAttribute('aria-live', 'polite');
            status.textContent = '正在加载检索状态…';
        }
        fetch(endpoint, {
            method: 'GET',
            cache: 'no-store',
            headers: { Accept: 'application/json' }
        }).then(function (response) {
            if (!response.ok) throw new Error('knowledge quality request failed');
            return response.json();
        }).then(function (payload) {
            render(card, payload);
        }).catch(function () {
            if (status) status.textContent = '检索状态暂时无法加载，请稍后重试。';
        }).finally(function () {
            button.disabled = false;
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        var card = document.getElementById('knowledge-quality-card');
        if (!card) return;
        var button = document.getElementById('knowledge-quality-refresh');
        if (!button) return;
        button.addEventListener('click', function () { load(card, button); });
        load(card, button);
    });
}(window, document));
