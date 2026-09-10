/**
 * 代码指导功能模块
 * 负责提供编程指导和反馈
 */

// 全局变量
let isGuidanceBusy = false;
let lastGuidanceRequest = null;

// 初始化指导功能
document.addEventListener('DOMContentLoaded', function() {
    console.log('编程指导功能模块已加载');
    
    // 绑定获取指导按钮事件
    const manualGuidanceBtn = document.getElementById('manual-guidance-btn');
    if (manualGuidanceBtn) {
        manualGuidanceBtn.addEventListener('click', function(e) {
            // 防止事件冒泡，确保不会触发表单提交
            e.preventDefault();
            e.stopPropagation();
            updateGuidanceFeedback();
        });
        console.log('已绑定手动获取指导按钮');
    }
    
    // 绑定展开辅助功能按钮事件
    const toggleAiGuidanceBtn = document.getElementById('toggle-ai-guidance');
    if (toggleAiGuidanceBtn) {
        toggleAiGuidanceBtn.addEventListener('click', function(e) {
            // 防止事件冒泡
            e.preventDefault();
            e.stopPropagation();
            toggleAiGuidance();
        });
        console.log('已绑定展开辅助功能按钮');
    }
});

// 切换AI辅助功能显示状态
function toggleAiGuidance() {
    const toggleBtn = document.getElementById('toggle-ai-guidance');
    const aiHelperContent = document.querySelector('.ai-helper-content');
    
    if (aiHelperContent) {
        if (aiHelperContent.style.display === 'none') {
            aiHelperContent.style.display = 'block';
            if (toggleBtn) {
                toggleBtn.innerHTML = '<i class="bi bi-chevron-up"></i> 收起辅助功能';
            }
        } else {
            aiHelperContent.style.display = 'none';
            if (toggleBtn) {
                toggleBtn.innerHTML = '<i class="bi bi-chevron-down"></i> 展开辅助功能';
            }
        }
    }
}

// 获取编程指导
function updateGuidanceFeedback() {
    if (isGuidanceBusy) {
        console.log('正在生成编程指导，请稍候...');
        showNotification('正在生成编程指导，请稍候...', 'warning');
        return;
    }
    
    console.log('尝试获取代码内容');
    
    // 获取代码 - 尝试多种方式
    let code = getEditorCode();
    
    // 如果getEditorCode没有返回有效代码，尝试其他方式
    if (!code || code.trim().length < 10) {
        // 直接尝试从Monaco编辑器获取
        if (window.codeEditors && window.codeEditors['code']) {
            code = window.codeEditors['code'].getValue();
            console.log('从codeEditors获取代码，长度:', code.length);
        }
        // 尝试从textarea获取
        else {
            const textarea = document.querySelector('textarea[name="code"]');
            if (textarea) {
                code = textarea.value;
                console.log('从textarea获取代码，长度:', code.length);
            }
        }
    } else {
        console.log('从getEditorCode获取代码，长度:', code.length);
    }
    
    // 检查最终结果
    if (!code || code.trim().length < 10) {
        showNotification('未能获取代码或代码过短，请先编写一些代码', 'warning');
        return;
    }
    
    // 显示加载指示器和容器
    const guidanceFeedbackContainer = document.getElementById('guidance-feedback-container');
    const guidanceLoading = document.getElementById('guidance-feedback-loading');
    const guidanceContent = document.getElementById('guidance-feedback-content');
    
    if (!guidanceFeedbackContainer || !guidanceLoading || !guidanceContent) {
        console.error('找不到指导反馈相关元素');
        return;
    }

    guidanceContent.classList.add('cs-markdown');
    
    // 显示容器和加载指示
    guidanceFeedbackContainer.style.display = 'block';
    guidanceLoading.style.display = 'flex';
    guidanceContent.innerHTML = '<div class="waiting-message">正在分析您的代码并生成指导建议，请稍候...</div>';
    
    // 标记为忙碌状态
    isGuidanceBusy = true;
    
    // 获取当前题目ID，如果有的话
    const assignmentIdElement = document.querySelector('input[name="assignment_id"]');
    const assignmentId = assignmentIdElement ? assignmentIdElement.value : null;
    
    // 发送请求
    const requestData = {
        code: code,
        language: 'cpp', // 默认语言，后续可扩展
        assignment_id: assignmentId
    };
    
    lastGuidanceRequest = Date.now();
    const currentRequest = lastGuidanceRequest;
    
    // 发送到后端API。优先使用统一 SSE，边生成边展示指导内容。
    let guidanceText = '';
    let streamError = null;
    window.consumeSSE('/api/get_coding_guidance', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Accept': 'text/event-stream'
        },
        body: JSON.stringify(requestData)
    }, {
        onDelta: event => {
            if (currentRequest !== lastGuidanceRequest) return;
            guidanceText += event.content || event.token || '';
            guidanceLoading.style.display = 'none';
            guidanceContent.innerHTML = formatMarkdown(guidanceText);
        },
        onError: event => {
            streamError = new Error(event.message || event.error || '获取指导失败');
        }
    })
    .then(data => {
        if (streamError) throw streamError;
        // 如果不是最新请求，丢弃结果
        if (currentRequest !== lastGuidanceRequest) {
            console.log('丢弃过时的指导结果');
            return;
        }
        
        // 更新UI
        guidanceLoading.style.display = 'none';
        
        const finalGuidance = data.guidance ||
            (data.data && data.data.guidance) || data.content || guidanceText;
        if (data.success !== false && finalGuidance) {
            guidanceContent.innerHTML = formatMarkdown(finalGuidance);
            // 高亮代码块
            document.querySelectorAll('#guidance-feedback-content pre code').forEach((block) => {
                hljs.highlightBlock(block);
            });
            showNotification('指导建议生成成功', 'success');
        } else {
            guidanceContent.innerHTML = `<div class="error-message">获取指导失败：${data.error || '未知错误'}</div>`;
            showNotification('获取指导失败', 'error');
        }
    })
    .catch(error => {
        console.error('获取编程指导时出错:', error);
        
        // 更新UI
        guidanceLoading.style.display = 'none';
        guidanceContent.innerHTML = `<div class="error-message">获取指导时发生错误：${error.message}</div>`;
        showNotification('获取指导时发生错误', 'error');
    })
    .finally(() => {
        isGuidanceBusy = false;
    });
}

/**
 * 格式化Markdown内容
 * 
 * 该函数负责将Markdown文本转换为HTML格式
 * 主要功能包括：
 * - 支持基本的Markdown语法（标题、粗体、斜体、代码块等）
 * - 通过共享渲染器统一处理格式与安全过滤
 * - 确保输出的HTML安全性
 * - 支持代码高亮集成
 * 
 * @param {string} markdown - 要格式化的Markdown文本
 * @returns {string} 格式化后的HTML字符串
 */
function formatMarkdown(markdown) {
    if (!markdown) return '';
    
    try {
        // 使用共享渲染器，确保不同页面的 Markdown 视觉与安全策略一致。
        if (window.CodeSenseMarkdown) {
            return window.CodeSenseMarkdown.renderToString(markdown);
        }

        // 共享渲染器不可用时只返回转义后的纯文本，避免产生不安全 HTML。
        const fallback = document.createElement('div');
        fallback.textContent = markdown;
        return fallback.innerHTML.replace(/\n/g, '<br>');
    } catch (e) {
        console.error('格式化Markdown时出错:', e);
        const fallback = document.createElement('div');
        fallback.textContent = markdown;
        return fallback.innerHTML.replace(/\n/g, '<br>');
    }
}

// 显示通知
function showNotification(message, type = 'info') {
    const notificationContainer = document.getElementById('notification-container');
    
    // 如果不存在通知容器，创建一个
    if (!notificationContainer) {
        const container = document.createElement('div');
        container.id = 'notification-container';
        container.style.position = 'fixed';
        container.style.top = '20px';
        container.style.right = '20px';
        container.style.zIndex = '1050';
        document.body.appendChild(container);
    }
    
    // 创建通知元素
    const notification = document.createElement('div');
    notification.className = `alert alert-${type} alert-dismissible fade show`;
    notification.style.minWidth = '250px';
    notification.style.marginBottom = '10px';
    notification.style.boxShadow = '0 0 10px rgba(0,0,0,0.1)';
    
    notification.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;
    
    // 添加到容器
    document.getElementById('notification-container').appendChild(notification);
    
    // 自动消失
    setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => {
            notification.remove();
        }, 300);
    }, 5000);
}

// 创建一个防抖函数
function debounce(func, wait) {
    let timeout;
    return function(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => {
            func.apply(this, args);
        }, wait);
    };
}

// 导出函数
window.updateGuidanceFeedback = updateGuidanceFeedback;
window.debouncedUpdateGuidance = debounce(updateGuidanceFeedback, 2000);
