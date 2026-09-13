/**
 * 代码问答系统功能模块
 * 负责处理学生提问和AI回答
 */

// 初始化问题系统
function initQuestionSystem() {
    console.log("初始化代码问答系统");
    
    const questionBtn = document.getElementById('ask-question-btn');
    const questionInput = document.getElementById('student-question');
    const questionDisplay = document.getElementById('student-question-display');
    
    if (!questionBtn || !questionInput) {
        console.error("找不到问答系统必要的元素");
        return;
    }
    
    // 防抖函数，防止频繁提交
    function debounce(func, wait) {
        let timeout;
        return function() {
            const context = this;
            const args = arguments;
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(context, args), wait);
        };
    }
    
    // 提交问题的事件处理
    questionBtn.addEventListener('click', handleQuestionSubmit);
    
    // 回车提交问题
    questionInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleQuestionSubmit();
        }
    });
    
    console.log("问答系统初始化完成");
}

// 表单提交处理
function handleQuestionSubmit() {
    const questionInput = document.getElementById('student-question');
    const questionBtn = document.getElementById('ask-question-btn');
    const questionDisplay = document.getElementById('student-question-display');
    const answerContainer = document.getElementById('ai-answer-container');
    
    if (!questionInput || !questionBtn) {
        console.error("找不到问答系统必要的元素");
        return;
    }
    
    var question = questionInput.value.trim();
    
    if (!question) {
        showQuestionAlert('warning', '请输入问题');
        return;
    }
    
    // 禁用按钮，防止重复提交
    questionBtn.disabled = true;
    questionBtn.innerHTML = '<i class="bi bi-hourglass-split"></i> 思考中...';
    
    // 显示学生问题
    if (questionDisplay) {
        questionDisplay.textContent = question;
        questionDisplay.style.display = 'block';
    }
    
    // 显示加载状态
    showAnswerLoadingState();
    
    // 获取代码编辑器内容
    var code = '';
    if (typeof getEditorCode === 'function') {
        code = getEditorCode();
    } else {
        // 尝试通过其他方式获取
        const codeElement = document.getElementById('code');
        if (codeElement) {
            code = codeElement.value;
        }
    }
    
    // 如果code为空，显示一个警告
    if (!code || code.trim() === '') {
        showQuestionAlert('warning', '警告：无法获取编辑器代码内容，这可能会影响AI回答');
        code = '// 未能获取到代码内容';
    }
    
    // 获取作业ID和当前编程语言
    const assignmentIdElement = document.querySelector('input[name="assignment_id"]');
    const assignmentId = assignmentIdElement ? assignmentIdElement.value : '';
    
    const languageElement = document.getElementById('language');
    const currentLanguage = languageElement ? languageElement.value : 'cpp';
    
    // 滚动到回答区域
    if (answerContainer) {
        answerContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    
    console.log('准备发送问题请求，问题长度:', question.length, '代码长度:', code.length);
    
    // 发送请求：采用统一 SSE，让回答可以边生成边阅读。
    let streamedAnswer = '';
    let streamError = null;
    window.consumeSSE('/api/ask_question', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Accept': 'text/event-stream'
        },
        body: JSON.stringify({ 
            question: question, 
            code: code,
            assignment_id: assignmentId,
            language: currentLanguage
        })
    }, {
        onDelta: function(event) {
            streamedAnswer += event.content || '';
            if (streamedAnswer) {
                hideAnswerLoadingState();
                displayAnswer(streamedAnswer);
            }
        },
        onError: function(event) {
            streamError = new Error(event.message || event.error || '获取回答失败');
        }
    })
    .then(function(data) {
        if (streamError) throw streamError;
        // 隐藏加载状态
        hideAnswerLoadingState();
        
        // 调试输出完整响应
        console.log("收到API响应:", data);
        
        // 获取回答内容（处理多种可能的数据结构）
        var answerText;
        try {
            // 检查各种可能的数据结构
            if (data.data && data.data.answer) {
                // 标准结构: {success:true, data:{answer:"..."}}
                answerText = data.data.answer;
                console.log("从data.data.answer获取回答，长度:", answerText.length);
            } else if (data.answer) {
                // 简化结构: {success:true, answer:"..."}
                answerText = data.answer;
                console.log("从data.answer获取回答，长度:", answerText.length);
            } else if (typeof data === 'string') {
                // 纯文本响应
                answerText = data;
                console.log("直接获取字符串回答，长度:", answerText.length);
            } else if (data.content || streamedAnswer) {
                answerText = data.content || streamedAnswer;
            } else {
                // 未知结构，尝试查看响应内容
                console.error("未知的响应结构:", data);
                if (data.message) {
                    answerText = "服务器消息: " + data.message;
                } else {
                    answerText = "收到响应，但格式无法识别。请联系管理员检查API接口。";
                }
            }
        } catch (error) {
            console.error("处理响应时出错:", error);
            answerText = "处理响应时出错: " + error.message;
        }
        
        // 确保答案内容不为空
        if (!answerText || answerText.trim() === '') {
            answerText = "收到空的回答内容，可能是API接口问题。请稍后再试。";
        }
        
        // 显示回答内容
        displayAnswer(answerText);
        
        // 恢复按钮状态
        questionBtn.disabled = false;
        questionBtn.innerHTML = '<i class="bi bi-send"></i> 提问';
        
        // 清空输入框
        questionInput.value = '';
    })
    .catch(function(error) {
        // 隐藏加载状态
        hideAnswerLoadingState();
        
        // 显示错误信息
        console.error("提问时出错:", error);
        displayAnswerError(error.message);
        
        // 恢复按钮状态
        questionBtn.disabled = false;
        questionBtn.innerHTML = '<i class="bi bi-send"></i> 提问';
    });
}

// 显示回答加载状态
function showAnswerLoadingState() {
    const answerContainer = document.getElementById('ai-answer-container');
    if (!answerContainer) return;
    
    answerContainer.innerHTML = `
        <div class="answer-loading">
            <div class="typing-indicator">
                <span></span>
                <span></span>
                <span></span>
            </div>
            <div class="small text-muted mt-2">AI助手正在思考中...</div>
        </div>
    `;
}

// 隐藏回答加载状态
function hideAnswerLoadingState() {
    const answerContainer = document.getElementById('ai-answer-container');
    if (!answerContainer) return;
    
    // 保留容器但清空内容，准备填充回答
    answerContainer.innerHTML = '';
}

// 显示回答内容
function displayAnswer(answerText) {
    const answerContainer = document.getElementById('ai-answer-container');
    if (!answerContainer) return;
    
    // 转换为Markdown（如果有可用的渲染函数）
    let formattedAnswer;
    if (typeof renderMarkdown === 'function') {
        formattedAnswer = renderMarkdown(answerText);
    } else {
        // 简单的HTML格式化
        formattedAnswer = answerText
            .replace(/\n\n/g, '<br><br>')
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code class="language-$1">$2</code></pre>');
    }
    
    // 创建回答元素
    answerContainer.innerHTML = `
        <div class="ai-answer">
            <div class="answer-header">
                <i class="bi bi-robot"></i>
                <span>AI助手回答</span>
            </div>
            <div class="answer-content markdown-content cs-markdown">
                ${formattedAnswer}
            </div>
        </div>
    `;
    
    // 处理代码高亮
    if (typeof processCodeBlocks === 'function') {
        processCodeBlocks();
    } else if (typeof hljs !== 'undefined') {
        // 直接使用highlight.js
        document.querySelectorAll('pre code').forEach((block) => {
            hljs.highlightElement(block);
        });
    }
}

// 显示回答错误
function displayAnswerError(errorMessage) {
    const answerContainer = document.getElementById('ai-answer-container');
    if (!answerContainer) return;
    
    answerContainer.innerHTML = `
        <div class="ai-answer error">
            <div class="answer-header">
                <i class="bi bi-exclamation-triangle"></i>
                <span>获取回答失败</span>
            </div>
            <div class="answer-content">
                <p>很抱歉，无法获取AI助手的回答。</p>
                <p class="error-details">错误信息: ${errorMessage}</p>
                <button onclick="handleQuestionSubmit()" class="retry-btn">
                    <i class="bi bi-arrow-repeat"></i> 重新尝试
                </button>
            </div>
        </div>
    `;
}

// 显示问题相关的警告或提示
function showQuestionAlert(type, message) {
    const alertContainer = document.getElementById('question-alert');
    
    // 如果不存在警告容器，创建一个
    if (!alertContainer) {
        const questionContainer = document.getElementById('question-container');
        if (!questionContainer) return;
        
        const newAlertContainer = document.createElement('div');
        newAlertContainer.id = 'question-alert';
        newAlertContainer.className = `alert alert-${type} mt-2`;
        newAlertContainer.innerHTML = message;
        
        // 插入到问题容器之后
        questionContainer.insertAdjacentElement('afterend', newAlertContainer);
    } else {
        // 更新已有的警告容器
        alertContainer.className = `alert alert-${type} mt-2`;
        alertContainer.innerHTML = message;
    }
    
    // 自动隐藏提示（仅对info类型）
    if (type === 'info') {
        setTimeout(() => {
            const currentAlert = document.getElementById('question-alert');
            if (currentAlert) {
                currentAlert.style.opacity = '0';
                setTimeout(() => currentAlert.remove(), 500);
            }
        }, 3000);
    }
}

// 在页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    // 初始化问答系统
    initQuestionSystem();
    
    // 添加问题相关的CSS样式
    addQuestionStyles();
});

/**
 * 代码提问功能模块
 * 负责处理学生向AI提问的功能
 */

// 初始化提问功能
document.addEventListener('DOMContentLoaded', function() {
    // 绑定提问按钮事件
    const askButton = document.getElementById('ask-question-btn');
    if (askButton) {
        askButton.addEventListener('click', function(e) {
            // 防止事件冒泡
            e.preventDefault();
            e.stopPropagation();
            handleAskQuestion();
        });
        console.log('已绑定提问按钮事件');
    }
    
    // 绑定按键事件（Ctrl+Enter提交问题）
    const questionInput = document.getElementById('student-question');
    if (questionInput) {
        questionInput.addEventListener('keydown', function(event) {
            if (event.ctrlKey && event.key === 'Enter') {
                event.preventDefault();
                handleAskQuestion();
            }
        });
    }
    
    // 添加问题相关的CSS样式
    addQuestionStyles();
});

// 处理提问操作
function handleAskQuestion() {
    const questionInput = document.getElementById('student-question');
    const answerContainer = document.getElementById('ai-answer-container');
    
    if (!questionInput || !answerContainer) {
        console.error('找不到提问相关元素');
        return;
    }
    
    const question = questionInput.value.trim();
    if (!question) {
        showNotification('请输入您的问题', 'warning');
        return;
    }
    
    // 显示加载状态
    answerContainer.innerHTML = `
        <div class="card">
            <div class="card-header">
                <div class="d-flex justify-content-between align-items-center">
                    <div><i class="bi bi-question-circle me-2"></i> 您的问题：</div>
                </div>
            </div>
            <div class="card-body">
                <p class="mb-0">${escapeHtml(question)}</p>
            </div>
        </div>
        
        <div class="card mt-2">
            <div class="card-header">
                <div class="d-flex justify-content-between align-items-center">
                    <div><i class="bi bi-robot me-2"></i> AI助手正在回答...</div>
                </div>
            </div>
            <div class="card-body">
                <div class="d-flex justify-content-center align-items-center p-3">
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    <span class="ms-3">正在思考您的问题...</span>
                </div>
            </div>
        </div>
    `;
    
    // 清空输入框
    questionInput.value = '';
    
    // 获取当前代码 - 尝试多种方式
    let code = getEditorCode();
    
    // 如果getEditorCode没有返回有效代码，尝试其他方式
    if (!code || code.trim().length < 5) {
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
    
    // 获取当前语言
    const languageElement = document.getElementById('language');
    const language = languageElement ? languageElement.value : 'cpp';
    
    // 获取当前题目ID
    const assignmentIdElement = document.querySelector('input[name="assignment_id"]');
    const assignmentId = assignmentIdElement ? assignmentIdElement.value : null;
    
    // 发送提问请求（统一 SSE）
    let streamedAnswer = '';
    let streamError = null;
    window.consumeSSE('/api/ask_question', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Accept': 'text/event-stream'
        },
        body: JSON.stringify({
            question: question,
            code: code || '',
            language: language,
            assignment_id: assignmentId
        })
    }, {
        onDelta: event => {
            streamedAnswer += event.content || '';
            if (streamedAnswer) {
                answerContainer.innerHTML = `<div class="card"><div class="card-body markdown-content cs-markdown">${formatMarkdown(streamedAnswer)}</div></div>`;
            }
        },
        onError: event => {
            streamError = new Error(event.message || event.error || '获取回答失败');
        }
    })
    .then(data => {
        if (streamError) throw streamError;
        const answer = data.answer || (data.data && data.data.answer) || data.content || streamedAnswer;
        if (data.success !== false && answer) {
            // 显示回答
            answerContainer.innerHTML = `
                <div class="card">
                    <div class="card-header">
                        <div class="d-flex justify-content-between align-items-center">
                            <div><i class="bi bi-question-circle me-2"></i> 您的问题：</div>
                        </div>
                    </div>
                    <div class="card-body">
                        <p class="mb-0">${escapeHtml(question)}</p>
                    </div>
                </div>
                
                <div class="card mt-2">
                    <div class="card-header">
                        <div class="d-flex justify-content-between align-items-center">
                            <div><i class="bi bi-robot me-2"></i> AI助手回答：</div>
                        </div>
                    </div>
                    <div class="card-body markdown-content cs-markdown">
                        ${formatMarkdown(answer)}
                    </div>
                </div>
            `;
            
            // 高亮代码块
            document.querySelectorAll('#ai-answer-container pre code').forEach((block) => {
                if (typeof hljs !== 'undefined') {
                    hljs.highlightBlock(block);
                }
            });
        } else {
            // 显示错误消息
            answerContainer.innerHTML = `
                <div class="card">
                    <div class="card-header">
                        <div class="d-flex justify-content-between align-items-center">
                            <div><i class="bi bi-question-circle me-2"></i> 您的问题：</div>
                        </div>
                    </div>
                    <div class="card-body">
                        <p class="mb-0">${escapeHtml(question)}</p>
                    </div>
                </div>
                
                <div class="card mt-2 border-danger">
                    <div class="card-header bg-danger text-white">
                        <div class="d-flex justify-content-between align-items-center">
                            <div><i class="bi bi-exclamation-triangle me-2"></i> 获取回答失败</div>
                        </div>
                    </div>
                    <div class="card-body">
                        <p class="mb-0">${data.error || '服务器无法回答您的问题，请稍后重试。'}</p>
                    </div>
                </div>
            `;
        }
    })
    .catch(error => {
        console.error('提问时出错:', error);
        answerContainer.innerHTML = `
            <div class="card">
                <div class="card-header">
                    <div class="d-flex justify-content-between align-items-center">
                        <div><i class="bi bi-question-circle me-2"></i> 您的问题：</div>
                    </div>
                </div>
                <div class="card-body">
                    <p class="mb-0">${escapeHtml(question)}</p>
                </div>
            </div>
            
            <div class="card mt-2 border-danger">
                <div class="card-header bg-danger text-white">
                    <div class="d-flex justify-content-between align-items-center">
                        <div><i class="bi bi-exclamation-triangle me-2"></i> 发生错误</div>
                    </div>
                </div>
                <div class="card-body">
                    <p class="mb-0">提问时发生错误：${error.message}</p>
                    <button class="btn btn-outline-primary mt-3" onclick="handleAskQuestion()">
                        <i class="bi bi-arrow-repeat me-2"></i> 重新尝试
                    </button>
                </div>
            </div>
        `;
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
        return escapeHtml(markdown).replace(/\n/g, '<br>');
    } catch (e) {
        console.error('格式化Markdown时出错:', e);
        return escapeHtml(markdown).replace(/\n/g, '<br>');
    }
}

/**
 * HTML转义函数
 * 
 * 该函数将文本中的特殊字符转换为HTML实体，防止XSS攻击
 * 主要功能包括：
 * - 转义HTML特殊字符（<, >, &, ", '）
 * - 提供安全的文本输出
 * - 支持DOM元素的文本内容设置
 * 
 * @param {string} text - 需要转义的文本
 * @returns {string} 转义后的HTML安全字符串
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * 显示通知
 * 
 * 该函数负责在页面上显示各种类型的通知消息
 * 主要功能包括：
 * - 支持多种通知类型（info, success, warning, danger）
 * - 自动消失机制
 * - 响应式设计适配
 * - 支持Bootstrap和自定义样式
 * - 提供全局和本地通知两种模式
 * 
 * @param {string} message - 通知消息内容
 * @param {string} type - 通知类型（'info', 'success', 'warning', 'danger'）
 */
function showNotification(message, type = 'info') {
    if (typeof window.showNotification === 'function') {
        // 如果全局已有通知函数，使用它
        window.showNotification(message, type);
        return;
    }
    
    // 否则创建自己的通知
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

// 添加问题系统的样式
function addQuestionStyles() {
    // 检查是否已添加样式
    if (document.getElementById('question-system-styles')) return;
    
    const styleElement = document.createElement('style');
    styleElement.id = 'question-system-styles';
    styleElement.textContent = `
        /* 问题系统样式 */
        #student-question {
            resize: vertical;
            min-height: 60px;
        }
        
        #ask-question-btn {
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 8px 16px;
        }
        
        #ask-question-btn i {
            margin-right: 6px;
        }
        
        #student-question-display {
            background-color: #f8f9fa;
            border-left: 4px solid #6c757d;
            padding: 10px 15px;
            margin-bottom: 15px;
            font-style: italic;
            display: none;
        }
        
        .ai-answer {
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            overflow: hidden;
            margin-top: 10px;
        }
        
        .ai-answer.error {
            border-left: 4px solid #dc3545;
        }
        
        .answer-header {
            background-color: #f8f9fa;
            padding: 10px 15px;
            border-bottom: 1px solid #e0e0e0;
            font-weight: 500;
            display: flex;
            align-items: center;
        }
        
        .answer-header i {
            margin-right: 8px;
            color: #0d6efd;
        }
        
        .ai-answer.error .answer-header i {
            color: #dc3545;
        }
        
        .answer-content {
            padding: 15px;
        }
        
        .error-details {
            color: #6c757d;
            font-size: 0.9em;
            margin-top: 10px;
        }
        
        .typing-indicator {
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .typing-indicator span {
            height: 8px;
            width: 8px;
            margin: 0 2px;
            background-color: #0d6efd;
            border-radius: 50%;
            opacity: 0.6;
            animation: typing 1s infinite;
        }
        
        .typing-indicator span:nth-child(1) {
            animation-delay: 0s;
        }
        
        .typing-indicator span:nth-child(2) {
            animation-delay: 0.2s;
        }
        
        .typing-indicator span:nth-child(3) {
            animation-delay: 0.4s;
        }
        
        @keyframes typing {
            0% { transform: translateY(0px); }
            50% { transform: translateY(-10px); }
            100% { transform: translateY(0px); }
        }
        
        .retry-btn {
            display: inline-flex;
            align-items: center;
            background-color: #f8f9fa;
            border: 1px solid #ced4da;
            padding: 6px 12px;
            border-radius: 4px;
            cursor: pointer;
            margin-top: 10px;
            font-size: 0.9em;
        }
        
        .retry-btn i {
            margin-right: 6px;
        }
        
        .retry-btn:hover {
            background-color: #e2e6ea;
        }
    `;
    
    document.head.appendChild(styleElement);
}
