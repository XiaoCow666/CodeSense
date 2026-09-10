/**
 * 代码建议模块 - 提供更简洁稳定的AI建议功能
 * 版本: 1.0.0
 */

document.addEventListener('DOMContentLoaded', () => {
    console.log('代码建议模块初始化');
    
    // 获取必要的DOM元素
    const adviceButton = document.getElementById('get-code-advice');
    const adviceContent = document.getElementById('advice-content');
    const loadingSpinner = document.getElementById('advice-loading');
    
    // 检查元素是否存在
    if (!adviceButton) {
        console.warn('未找到代码建议按钮，跳过初始化');
        return;
    }
    
    // 初始化UI元素
    initAdviceElements();
    
    // 绑定点击事件
    adviceButton.addEventListener('click', () => {
        getCodeAdvice();
    });
    
    console.log('代码建议模块初始化完成');
});

/**
 * 初始化建议UI元素
 */
function initAdviceElements() {
    // 检查是否需要创建UI元素
    if (!document.getElementById('advice-content')) {
        // 创建建议内容容器
        const adviceContainer = document.createElement('div');
        adviceContainer.className = 'card mt-4 advice-container';
        adviceContainer.innerHTML = `
            <div class="card-header bg-primary text-white">
                <h5 class="mb-0">
                    <i class="bi bi-lightbulb"></i> AI代码建议
                </h5>
            </div>
            <div class="card-body">
                <div id="advice-loading" style="display:none;" class="text-center p-4">
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">加载中...</span>
                    </div>
                    <p class="mt-2">正在分析代码，请稍候...</p>
                </div>
                <div id="advice-content" class="markdown-content cs-markdown"></div>
            </div>
        `;
        
        // 添加到代码区域后面
        const codeForm = document.getElementById('code-form');
        if (codeForm) {
            codeForm.parentNode.insertBefore(adviceContainer, codeForm.nextSibling);
        } else {
            // 如果没有找到代码表单，尝试添加到主内容区
            const mainContent = document.querySelector('.container') || document.querySelector('main');
            if (mainContent) {
                mainContent.appendChild(adviceContainer);
            }
        }
    }
    
    // 检查建议按钮是否需要创建
    if (!document.getElementById('get-code-advice')) {
        // 创建按钮
        const adviceBtn = document.createElement('button');
        adviceBtn.id = 'get-code-advice';
        adviceBtn.className = 'btn btn-outline-primary ms-2';
        adviceBtn.innerHTML = '<i class="bi bi-magic"></i> 获取代码建议';
        
        // 添加到提交按钮旁边
        const submitBtn = document.querySelector('button[type="submit"]');
        if (submitBtn) {
            submitBtn.parentNode.insertBefore(adviceBtn, submitBtn.nextSibling);
        }
    }
}

/**
 * 获取代码建议
 */
function getCodeAdvice() {
    // 获取必要元素
    const adviceContent = document.getElementById('advice-content');
    const loadingSpinner = document.getElementById('advice-loading');
    const adviceButton = document.getElementById('get-code-advice');
    
    if (!adviceContent || !loadingSpinner || !adviceButton) {
        console.error('找不到建议相关UI元素');
        return;
    }
    
    // 显示加载中状态
    adviceButton.disabled = true;
    adviceContent.style.display = 'none';
    loadingSpinner.style.display = 'block';
    
    // 获取代码内容
    const code = getCode();
    if (!code) {
        showAdviceError('无法获取代码，请确保您已输入代码');
        return;
    }
    
    // 获取当前作业ID
    const assignmentId = getAssignmentId();
    
    // 获取当前编程语言
    const language = getLanguage();
    
    // 构建请求数据
    const requestData = {
        code: code,
        assignment_id: assignmentId,
        language: language
    };
    
    console.log(`正在请求代码建议，代码长度: ${code.length}`);
    
    // 发送API请求：报告也通过统一 SSE 增量展示。
    let streamedAdvice = '';
    let streamError = null;
    window.consumeSSE('/api/code_advice', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'text/event-stream'
        },
        body: JSON.stringify(requestData)
    }, {
        onDelta: event => {
            streamedAdvice += event.content || event.token || '';
            if (streamedAdvice) displayAdvice(streamedAdvice);
        },
        onError: event => {
            streamError = new Error(event.message || event.error || '获取建议失败');
        }
    })
    .then(data => {
        if (streamError) throw streamError;
        const advice = data.advice || (data.data && data.data.advice) || data.content || streamedAdvice;
        if (data.success !== false && advice) {
            // 显示建议内容
            displayAdvice(advice);
        } else {
            // 显示错误信息
            showAdviceError(data.message || '获取建议失败，请稍后重试');
        }
    })
    .catch(error => {
        console.error('获取代码建议时出错:', error);
        showAdviceError(`获取建议时出错: ${error.message}`);
    })
    .finally(() => {
        // 恢复按钮状态
        adviceButton.disabled = false;
    });
}

/**
 * 获取代码内容的统一方法
 */
function getCode() {
    // 尝试从不同来源获取代码
    
    // 1. 从textarea获取
    const codeTextarea = document.querySelector('textarea[name="code"]');
    if (codeTextarea && codeTextarea.value.trim()) {
        return codeTextarea.value;
    }
    
    // 2. 从Monaco编辑器获取
    if (window.codeEditor) {
        try {
            const code = window.codeEditor.getValue();
            if (code && code.trim()) {
                return code;
            }
        } catch (e) {
            console.error('从Monaco编辑器获取代码失败:', e);
        }
    }
    
    // 3. 尝试全局函数
    if (typeof getEditorCode === 'function') {
        try {
            const code = getEditorCode();
            if (code && code.trim()) {
                return code;
            }
        } catch (e) {
            console.error('从getEditorCode函数获取代码失败:', e);
        }
    }
    
    // 4. 从全局变量获取
    if (window.currentCode) {
        return window.currentCode;
    }
    
    // 无法获取代码
    return null;
}

/**
 * 获取当前作业ID
 */
function getAssignmentId() {
    // 从隐藏字段获取
    const assignmentField = document.querySelector('input[name="assignment_id"]');
    if (assignmentField) {
        return assignmentField.value;
    }
    
    // 从URL获取
    const match = location.pathname.match(/\/assignments\/(\d+)/);
    if (match && match[1]) {
        return match[1];
    }
    
    // 从全局变量获取
    if (window.assignmentId) {
        return window.assignmentId;
    }
    
    return null;
}

/**
 * 获取当前编程语言
 */
function getLanguage() {
    // 从下拉菜单获取
    const languageSelect = document.getElementById('language');
    if (languageSelect) {
        return languageSelect.value;
    }
    
    // 从隐藏字段获取
    const languageField = document.querySelector('input[name="language"]');
    if (languageField) {
        return languageField.value;
    }
    
    // 从全局变量获取
    if (window.codeLanguage) {
        return window.codeLanguage;
    }
    
    // 默认为C++
    return 'cpp';
}

/**
 * 显示代码建议
 */
function displayAdvice(advice) {
    if (!advice) {
        showAdviceError('收到空的建议内容');
        return;
    }
    
    const adviceContent = document.getElementById('advice-content');
    const loadingSpinner = document.getElementById('advice-loading');
    
    if (!adviceContent || !loadingSpinner) {
        console.error('找不到建议相关UI元素');
        return;
    }
    
    // 格式化Markdown内容
    let formattedAdvice = '';
    try {
        // 使用共享渲染器，确保不同页面的 Markdown 视觉与安全策略一致。
        if (window.CodeSenseMarkdown) {
            formattedAdvice = window.CodeSenseMarkdown.renderToString(advice);
        } else {
            // 简单的Markdown格式化
            formattedAdvice = formatMarkdown(advice);
        }
    } catch (e) {
        console.error('格式化建议内容时出错:', e);
        formattedAdvice = `<p>${advice.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>')}</p>`;
    }
    
    // 更新UI
    adviceContent.innerHTML = formattedAdvice;
    adviceContent.style.display = 'block';
    loadingSpinner.style.display = 'none';
    
    // 应用代码高亮
    if (typeof hljs !== 'undefined') {
        document.querySelectorAll('#advice-content pre code').forEach(block => {
            hljs.highlightBlock(block);
        });
    }
    
    // 显示成功通知
    showToast('代码建议已生成', 'success');
}

/**
 * 显示错误信息
 */
function showAdviceError(message) {
    const adviceContent = document.getElementById('advice-content');
    const loadingSpinner = document.getElementById('advice-loading');
    const adviceButton = document.getElementById('get-code-advice');
    
    if (adviceContent) {
        adviceContent.innerHTML = `
            <div class="alert alert-danger">
                <i class="bi bi-exclamation-triangle-fill me-2"></i>
                ${message}
            </div>
        `;
        adviceContent.style.display = 'block';
    }
    
    if (loadingSpinner) {
        loadingSpinner.style.display = 'none';
    }
    
    if (adviceButton) {
        adviceButton.disabled = false;
    }
    
    // 显示错误通知
    showToast(message, 'danger');
}

/**
 * 简单的Markdown格式化
 */
function formatMarkdown(text) {
    if (!text) return '';
    
    return text
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/# (.*?)(\n|$)/g, '<h1>$1</h1>')
        .replace(/## (.*?)(\n|$)/g, '<h2>$1</h2>')
        .replace(/### (.*?)(\n|$)/g, '<h3>$1</h3>')
        .replace(/```(\w*)([\s\S]*?)```/g, '<pre><code class="$1">$2</code></pre>')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\n\n/g, '</p><p>')
        .replace(/\n/g, '<br>')
        .replace(/^(.+)$/, '<p>$1</p>');
}

/**
 * 显示Toast通知
 */
function showToast(message, type = 'info') {
    // 检查是否已存在Toast容器
    let toastContainer = document.getElementById('toast-container');
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.id = 'toast-container';
        toastContainer.style.position = 'fixed';
        toastContainer.style.top = '20px';
        toastContainer.style.right = '20px';
        toastContainer.style.zIndex = '9999';
        document.body.appendChild(toastContainer);
    }
    
    // 创建新的Toast
    const toast = document.createElement('div');
    toast.className = `toast align-items-center bg-${type} text-white border-0`;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">
                ${message}
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="关闭"></button>
        </div>
    `;
    
    // 添加到容器
    toastContainer.appendChild(toast);
    
    // 如果有Bootstrap的Toast，使用它
    if (typeof bootstrap !== 'undefined' && bootstrap.Toast) {
        const bsToast = new bootstrap.Toast(toast, {
            autohide: true,
            delay: 5000
        });
        bsToast.show();
    } else {
        // 简单的替代方案
        toast.style.display = 'block';
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transition = 'opacity 0.5s';
            setTimeout(() => {
                toast.remove();
            }, 500);
        }, 5000);
    }
}
