/**
 * 使用API提交代码（可选，用于AJAX提交）
 * 
 * 该函数提供了通过AJAX方式提交代码的替代方案
 * 主要功能包括：
 * - 获取代码编辑器内容
 * - 验证代码不为空
 * - 获取作业ID和语言信息
 * - 发送POST请求到后端API
 * - 处理响应并显示结果
 * - 提供重试机制
 * 
 * @returns {boolean} 提交是否成功
 */
function submitCodeViaAPI() {
    // 获取代码内容
    const code = getEditorCode();
    if (!code || code.trim() === '') {
        showSubmissionMessage("请输入代码后再提交！", "danger");
        return false;
    }
    
    // 获取作业ID
    const assignmentIdElement = document.querySelector('input[name="assignment_id"]');
    const assignmentId = assignmentIdElement ? assignmentIdElement.value : '';
    
    if (!assignmentId) {
        showSubmissionMessage("找不到作业ID，无法提交", "danger");
        return false;
    }
    
    // 获取语言
    const languageElement = document.getElementById('language');
    const language = languageElement ? languageElement.value : 'cpp';
    
    // 显示加载状态
    showSubmitLoadingState();
    
    // 发送API请求
    fetch('/api/submit', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            code: code,
            assignment_id: assignmentId,
            language: language
        })
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(data => {
                throw new Error(data.message || `HTTP 错误! 状态: ${response.status}`);
            });
        }
        return response.json();
    })
    .then(data => {
        console.log("提交成功:", data);
        const submission = data.data || {};

        if (data.data && data.data.status === "queued") {
            showSubmissionMessage("代码已提交，后台评测中，请稍候。", "info");
            return pollSubmissionUntilEvaluated(submission.submission_id)
                .then(result => {
                    showSubmissionMessage(`代码评测完成! 评分: ${result.score}/5`, "success");
                    window.location.href = `/assignments/view_submission/${submission.submission_id}`;
                });
        }

        // 默认线程/同步路径保留原有即时响应。
        showSubmissionMessage(`代码提交成功! 评分: ${submission.score}/5`, "success");
        if (submission.submission_id) {
            setTimeout(() => {
                window.location.href = `/assignments/view_submission/${submission.submission_id}`;
            }, 1500);
        } else {
            setTimeout(() => {
                window.location.reload();
            }, 1500);
        }
    })
    .catch(error => {
        console.error("提交代码时出错:", error);
        showSubmissionMessage("提交失败: " + error.message, "danger");
        resetSubmitButton();
    });
    
    return true;
}

function pollSubmissionUntilEvaluated(submissionId, attempt = 0) {
    const maxAttempts = 60;
    if (!submissionId || attempt >= maxAttempts) {
        return Promise.reject(new Error("评测时间较长，请稍后打开提交记录查看结果。"));
    }

    return fetch(`/api/submissions/${submissionId}/status`)
        .then(response => {
            if (!response.ok) throw new Error(`HTTP 错误! 状态: ${response.status}`);
            return response.json();
        })
        .then(data => {
            if (data.status === "evaluated") {
                return data;
            }
            if (data.queue_status === "unavailable") {
                throw new Error("评测队列暂时不可用，请稍后重试。");
            }
            if (data.status === "failed" || data.queue_status === "expired") {
                throw new Error("评测任务已过期或失败，请重新提交。");
            }
            return new Promise(resolve => setTimeout(resolve, 1500))
                .then(() => pollSubmissionUntilEvaluated(submissionId, attempt + 1));
        });
}
