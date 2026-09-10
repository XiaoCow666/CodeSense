/* global marked, DOMPurify */
/*
 * One Markdown entry point for CodeSense AI content.
 *
 * It keeps parsing, sanitisation and small presentation enhancements in one
 * place.  Pages may still call renderToString() while streaming, but they no
 * longer need to know which marked version or fallback rules are active.
 */
(function (window, document) {
    'use strict';

    var MARKDOWN_OPTIONS = {
        breaks: true,
        gfm: true,
        headerIds: false,
        mangle: false
    };

    var CALLOUT_LABELS = {
        note: '说明',
        info: '说明',
        tip: '提示',
        success: '完成',
        warning: '注意',
        caution: '注意',
        important: '重点',
        danger: '风险'
    };

    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function normaliseMarkdown(value) {
        var raw = String(value == null ? '' : value)
            .replace(/\r\n?/g, '\n')
            .replace(/\u00a0/g, ' ');

        // Preserve code blocks while making compact AI paragraphs easier to scan.
        if (!raw.includes('\n') || raw.split('\n').length < 3) {
            raw = raw.replace(/(\s)(\d[\)\.]\s?)/g, '\n\n$2');
        }
        return raw.trim();
    }

    function renderFallbackInline(value) {
        var escaped = escapeHtml(value);
        var placeholders = [];
        var placeholder = function (html) {
            var token = '___CS_MD_TOKEN_' + placeholders.length + '___';
            placeholders.push(html);
            return token;
        };

        // 先保护行内代码，再处理强调语法，避免代码里的星号被误解析。
        escaped = escaped.replace(/`([^`\n]+)`/g, function (_, code) {
            return placeholder('<code>' + code + '</code>');
        });
        escaped = escaped.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/gi, function (_, label, href) {
            return placeholder('<a href="' + href + '" target="_blank" rel="noopener noreferrer">' + label + '</a>');
        });
        escaped = escaped.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
        escaped = escaped.replace(/__([^_\n]+)__/g, '<strong>$1</strong>');
        escaped = escaped.replace(/(^|[^*])\*([^*\n]+)\*([^*]|$)/g, '$1<em>$2</em>$3');

        return escaped.replace(/___CS_MD_TOKEN_(\d+)___/g, function (_, index) {
            return placeholders[Number(index)] || '';
        });
    }

    // marked CDN 不可用时的本地安全降级：至少保留标题、列表、引用、代码块和加粗。
    // 所有用户/模型文字先经过 escapeHtml，只拼接固定标签，不能执行原始 HTML。
    function renderFallbackMarkdown(value) {
        var raw = normaliseMarkdown(value);
        if (!raw) return '';

        var lines = raw.split('\n');
        var html = [];
        var paragraph = [];
        var listType = null;
        var listItems = [];
        var codeLines = [];
        var codeLanguage = '';
        var inCode = false;

        function flushParagraph() {
            if (!paragraph.length) return;
            html.push('<p>' + renderFallbackInline(paragraph.join('\n')).replace(/\n/g, '<br>') + '</p>');
            paragraph = [];
        }

        function flushList() {
            if (!listItems.length) return;
            html.push('<' + listType + '>' + listItems.map(function (item) {
                return '<li>' + renderFallbackInline(item) + '</li>';
            }).join('') + '</' + listType + '>');
            listType = null;
            listItems = [];
        }

        function flushCode() {
            if (!inCode) return;
            html.push('<pre><code class="language-' + escapeHtml(codeLanguage || 'text') + '">' +
                escapeHtml(codeLines.join('\n')) + '</code></pre>');
            codeLines = [];
            codeLanguage = '';
        }

        lines.forEach(function (line) {
            var fence = line.match(/^\s*```\s*([\w+-]*)\s*$/);
            if (fence) {
                if (inCode) {
                    flushCode();
                    inCode = false;
                } else {
                    flushParagraph();
                    flushList();
                    inCode = true;
                    codeLanguage = fence[1] || 'text';
                }
                return;
            }

            if (inCode) {
                codeLines.push(line);
                return;
            }

            if (!line.trim()) {
                flushParagraph();
                flushList();
                return;
            }

            var heading = line.match(/^\s*(#{1,6})\s+(.+?)\s*#*\s*$/);
            if (heading) {
                flushParagraph();
                flushList();
                var level = heading[1].length;
                html.push('<h' + level + '>' + renderFallbackInline(heading[2]) + '</h' + level + '>');
                return;
            }

            if (/^\s*(?:---+|___+|\*\s*\*\s*\*)\s*$/.test(line)) {
                flushParagraph();
                flushList();
                html.push('<hr>');
                return;
            }

            var quote = line.match(/^\s*>\s?(.*)$/);
            if (quote) {
                flushParagraph();
                flushList();
                html.push('<blockquote><p>' + renderFallbackInline(quote[1]) + '</p></blockquote>');
                return;
            }

            var ordered = line.match(/^\s*(\d+)(?:[.)]|\uFE0F\u20E3)\s+(.+)$/);
            var unordered = line.match(/^\s*[-+*]\s+(.+)$/);
            if (ordered || unordered) {
                flushParagraph();
                var nextType = ordered ? 'ol' : 'ul';
                if (listType && listType !== nextType) flushList();
                listType = nextType;
                listItems.push(ordered ? ordered[2] : unordered[1]);
                return;
            }

            if (listType) flushList();
            paragraph.push(line);
        });

        if (inCode) flushCode();
        flushParagraph();
        flushList();
        return html.join('');
    }

    function safeHtmlFromMarkdown(value) {
        var raw = normaliseMarkdown(value);
        if (!raw) return '';

        if (typeof marked === 'undefined' || typeof marked.parse !== 'function') {
            return renderFallbackMarkdown(raw);
        }

        var rendered = marked.parse(raw, MARKDOWN_OPTIONS);
        if (typeof DOMPurify === 'undefined' || typeof DOMPurify.sanitize !== 'function') {
            // A missing sanitiser must never turn model output into executable HTML.
            return renderFallbackMarkdown(raw);
        }

        return DOMPurify.sanitize(rendered, {
            USE_PROFILES: { html: true },
            FORBID_TAGS: ['form', 'iframe', 'object', 'embed', 'style'],
            FORBID_ATTR: ['srcdoc']
        });
    }

    function removeLeadingMarker(paragraph, markerLength) {
        var walker = document.createTreeWalker(paragraph, NodeFilter.SHOW_TEXT);
        var remaining = markerLength;
        var node;

        while (remaining > 0 && (node = walker.nextNode())) {
            var text = node.nodeValue || '';
            if (!text) continue;

            var removeCount = Math.min(remaining, text.length);
            node.nodeValue = text.slice(removeCount);
            remaining -= removeCount;
        }
    }

    function decorateCallouts(root) {
        root.querySelectorAll('blockquote').forEach(function (blockquote) {
            var firstParagraph = blockquote.firstElementChild;
            if (!firstParagraph || firstParagraph.tagName.toLowerCase() !== 'p') return;

            var match = (firstParagraph.textContent || '').match(/^\s*\[!(NOTE|INFO|TIP|SUCCESS|WARNING|CAUTION|IMPORTANT|DANGER)\]\s*/i);
            if (!match) return;

            var type = match[1].toLowerCase();
            blockquote.classList.add('cs-md-callout', 'cs-md-callout-' + type);
            blockquote.setAttribute('data-callout-type', type);
            removeLeadingMarker(firstParagraph, match[0].length);

            var label = document.createElement('span');
            label.className = 'cs-md-callout-label';
            label.textContent = CALLOUT_LABELS[type] || '说明';
            firstParagraph.parentNode.insertBefore(label, firstParagraph);
        });
    }

    function getLanguage(code) {
        var className = code.className || '';
        var match = className.match(/(?:language|lang)-([\w+-]+)/i);
        return match ? match[1] : 'code';
    }

    function copyText(value) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            return navigator.clipboard.writeText(value);
        }

        return new Promise(function (resolve, reject) {
            var textarea = document.createElement('textarea');
            textarea.value = value;
            textarea.setAttribute('readonly', '');
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.select();
            try {
                if (!document.execCommand('copy')) throw new Error('copy command failed');
                resolve();
            } catch (error) {
                reject(error);
            } finally {
                textarea.remove();
            }
        });
    }

    function makeCopyButton(code) {
        var button = document.createElement('button');
        button.type = 'button';
        button.className = 'cs-code-copy';
        button.setAttribute('data-cs-copy', '');
        button.setAttribute('aria-label', '复制代码');
        button.textContent = '复制';
        button.dataset.copyText = code.textContent || '';
        return button;
    }

    function decorateCodeBlocks(root) {
        root.querySelectorAll('pre').forEach(function (pre) {
            var code = pre.querySelector('code');
            if (!code) return;

            var existingFrame = pre.closest('.cs-code-frame, .code-block-container');
            if (existingFrame) {
                existingFrame.classList.add('cs-code-frame');
                pre.classList.add('cs-code-pre', 'code-block');
                if (!existingFrame.querySelector('[data-cs-copy], .code-copy-button')) {
                    var action = existingFrame.querySelector('.code-block-action');
                    if (!action) {
                        action = document.createElement('div');
                        action.className = 'code-block-action';
                        var banner = existingFrame.querySelector('.code-block-banner');
                        if (banner) banner.appendChild(action);
                    }
                    if (action) action.appendChild(makeCopyButton(code));
                }
                return;
            }

            var frame = document.createElement('div');
            frame.className = 'cs-code-frame';

            var toolbar = document.createElement('div');
            toolbar.className = 'cs-code-toolbar';

            var language = document.createElement('span');
            language.className = 'cs-code-language';
            language.textContent = getLanguage(code);

            toolbar.appendChild(language);
            toolbar.appendChild(makeCopyButton(code));

            pre.parentNode.insertBefore(frame, pre);
            frame.appendChild(toolbar);
            frame.appendChild(pre);
            // 保留旧兼容脚本识别的 .code-block 标记，避免它在 DOMContentLoaded
            // 后再次包裹同一段代码。
            pre.classList.add('cs-code-pre', 'code-block');
            code.classList.add('cs-code-source');
        });
    }

    function decorateTables(root) {
        root.querySelectorAll('table').forEach(function (table) {
            if (table.parentElement && table.parentElement.classList.contains('cs-table-wrap')) return;
            var wrapper = document.createElement('div');
            wrapper.className = 'cs-table-wrap';
            table.parentNode.insertBefore(wrapper, table);
            wrapper.appendChild(table);
        });
    }

    function decorateLinks(root) {
        root.querySelectorAll('a[href]').forEach(function (link) {
            var href = link.getAttribute('href') || '';
            if (/^https?:\/\//i.test(href)) {
                link.setAttribute('target', '_blank');
                link.setAttribute('rel', 'noopener noreferrer');
            }
        });
    }

    function enhanceElement(root) {
        if (!root || !root.querySelectorAll) return root;
        root.classList.add('cs-markdown');
        decorateCallouts(root);
        decorateTables(root);
        decorateCodeBlocks(root);
        decorateLinks(root);
        root.querySelectorAll('input[type="checkbox"]').forEach(function (checkbox) {
            checkbox.disabled = true;
        });
        return root;
    }

    function renderToString(value) {
        var wrapper = document.createElement('div');
        wrapper.innerHTML = safeHtmlFromMarkdown(value);
        enhanceElement(wrapper);
        return wrapper.innerHTML;
    }

    function readRawValue(element) {
        if (element.hasAttribute('data-markdown')) {
            return element.getAttribute('data-markdown') || '';
        }
        return element.textContent || element.innerText || '';
    }

    function renderElement(element, value, options) {
        if (!element) return;
        element.innerHTML = safeHtmlFromMarkdown(value);
        enhanceElement(element);
        element.setAttribute('data-cs-md-rendered', '1');
        if (options && options.streaming) {
            element.setAttribute('data-cs-streaming', '1');
        } else {
            element.removeAttribute('data-cs-streaming');
        }
    }

    function renderAll(root) {
        var scope = root && root.querySelectorAll ? root : document;
        var elements = scope.querySelectorAll('[data-markdown], .markdown-render, .markdown-body');
        elements.forEach(function (element) {
            if (element.getAttribute('data-cs-md-rendered') === '1') return;
            var raw = readRawValue(element);
            if (raw.trim()) renderElement(element, raw);
        });
    }

    function handleCopyClick(event) {
        var button = event.target.closest('[data-cs-copy], .code-copy-button');
        if (!button) return;

        var frame = button.closest('.cs-code-frame, .code-block-container');
        var code = frame ? frame.querySelector('pre code') : null;
        var value = button.dataset.copyText || (code ? code.textContent : '');
        if (!value) return;

        copyText(value).then(function () {
            var previous = button.textContent;
            button.textContent = '已复制';
            window.setTimeout(function () {
                button.textContent = previous || '复制';
            }, 1600);
        }).catch(function (error) {
            console.warn('代码复制失败:', error);
        });
    }

    document.addEventListener('click', handleCopyClick);

    window.CodeSenseMarkdown = {
        enhance: enhanceElement,
        options: MARKDOWN_OPTIONS,
        render: renderElement,
        renderAll: renderAll,
        renderToString: renderToString,
        readRaw: readRawValue
    };
    window.renderCodeSenseMarkdown = renderToString;
    window.renderMarkdownElements = renderAll;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { renderAll(document); });
    } else {
        renderAll(document);
    }
})(window, document);
