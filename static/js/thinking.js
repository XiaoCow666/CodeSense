/**
 * 三阶段引导式学习系统 — 前端交互逻辑
 * Guided Learning Arena (thinking.js)
 */

(function () {
    'use strict';

    // ============================================================
    // State Management
    // ============================================================
    const state = {
        sessionId: null,
        assignmentId: null,
        currentStage: 1,
        preset: null,
        // Timer
        startTime: null,
        timerInterval: null,
        // Stage 1
        stage1Score: null,
        // Stage 2
        solutionBlocks: [],
        poolSortable: null,
        solutionSortable: null,
        // Stage 3
        teacherMessages: [],
        studentMessages: [],
        feynmanPhase: 'chat', // 'chat' | 'code_review' | 'completed'
        buggyCode: null,
        // Flags
        isLoading: false,
    };

    // ============================================================
    // Initialization
    // ============================================================
    function init() {
        const container = document.getElementById('arena-container');
        if (!container) return;

        state.assignmentId = parseInt(container.dataset.assignmentId);
        const presetStatus = (container.dataset.presetStatus || '').trim();

        if (presetStatus !== 'ready') {
            if (presetStatus === 'generating') {
                pollPresetStatus();
            }
            return;
        }

        startTimer();
        startSession();
        
        // Initialize Developer Debug Panel (localhost/127.0.0.1 only)
        initDevDebugConsole();
    }

    function pollPresetStatus() {
        const interval = setInterval(() => {
            fetchJSON(`/thinking/api/preset_status/${state.assignmentId}`, { method: 'GET' })
                .then(data => {
                    if (data.status === 'ready' || data.status === 'failed') {
                        clearInterval(interval);
                        location.reload();
                    }
                })
                .catch(err => console.error('轮询预设状态失败:', err));
        }, 3000);
    }

    function startSession() {
        setLoading(true);
        fetchJSON('/thinking/api/start_session', {
            method: 'POST',
            body: JSON.stringify({ assignment_id: state.assignmentId })
        }).then(data => {
            if (data.success) {
                state.sessionId = data.session_id;
                state.currentStage = data.current_stage;
                state.preset = data.preset;

                if (data.resumed) {
                    showNotification('已恢复上次的学习进度', 'info');
                    state.isResumed = true;
                    state.elapsedSeconds = data.elapsed_seconds || 0;
                    state.stage1Description = data.stage1_description || '';
                    state.stage1Score = data.stage1_score || null;
                    state.stage2BlockOrder = data.stage2_block_order || null;
                    state.companionHistory = data.companion_history || [];
                    state.teacherHistory = data.teacher_history || [];
                    state.studentHistory = data.student_history || [];
                    state.buggyCodeInfo = data.buggy_code_info || null;

                    // 同步并重新启动计时器
                    if (state.timerInterval) {
                        clearInterval(state.timerInterval);
                    }
                    state.startTime = Date.now() - state.elapsedSeconds * 1000;
                    startTimer();
                }

                initStage(state.currentStage);
            } else {
                showError(data.error || '创建会话失败');
            }
        }).catch(err => {
            showError('连接服务器失败: ' + err.message);
        }).finally(() => setLoading(false));
    }

    // ============================================================
    // Stage Navigation
    // ============================================================
    function initStage(stage) {
        state.currentStage = stage;
        updateProgressUI(stage);

        document.querySelectorAll('.stage-section').forEach(s => s.classList.remove('active'));
        const target = document.getElementById(`stage-${stage}`);
        if (target) target.classList.add('active');

        // Toggle code preview panel in right column for Stage 2
        const previewPanel = document.getElementById('stage2-preview-panel');
        if (previewPanel) {
            if (stage === 2) {
                previewPanel.classList.add('active');
            } else {
                previewPanel.classList.remove('active');
            }
        }

        // Toggle companion and student panels appropriately
        const companionPanel = document.getElementById('ai-companion-panel');
        const studentPanel = document.getElementById('student-agent-panel');
        if (stage === 3) {
            if (companionPanel) companionPanel.classList.remove('active');
            if (studentPanel) studentPanel.classList.add('active');
        } else {
            if (companionPanel) companionPanel.classList.add('active');
            if (studentPanel) studentPanel.classList.remove('active');
        }

        // Update body layout for stages
        const body = document.querySelector('.arena-body');
        if (body) {
            body.classList.toggle('stage-2-layout', stage === 2);
            body.classList.toggle('feynman-layout', stage === 3);
        }

        if (stage === 1) initStage1();
        else if (stage === 2) initStage2();
        else if (stage === 3) initStage3();
    }

    function updateProgressUI(currentStage) {
        for (let i = 1; i <= 3; i++) {
            const circle = document.getElementById(`step-circle-${i}`);
            const label = document.getElementById(`step-label-${i}`);
            const line = document.getElementById(`step-line-${i}`);

            if (circle) {
                circle.classList.remove('active', 'completed');
                if (i < currentStage) circle.classList.add('completed');
                else if (i === currentStage) circle.classList.add('active');
            }
            if (label) {
                label.classList.remove('active', 'completed');
                if (i < currentStage) label.classList.add('completed');
                else if (i === currentStage) label.classList.add('active');
            }
            if (line) {
                line.classList.remove('completed');
                if (i < currentStage) line.classList.add('completed');
            }
        }
    }

    // ============================================================
    // Stage 1: Natural Language Description
    // ============================================================
    function initStage1() {
        const textarea = document.getElementById('description-input');
        const submitBtn = document.getElementById('stage1-submit');
        const hintBtn = document.getElementById('stage1-hint');

        if (submitBtn) {
            submitBtn.onclick = () => submitDescription();
        }
        if (hintBtn) {
            hintBtn.onclick = () => requestStage1Hint();
        }
        if (textarea) {
            // Hide the original textarea completely
            textarea.style.display = 'none';
        }

        // Setup algorithm summary collapse toggle & display
        const algoSummaryWrapper = document.getElementById('algo-summary-wrapper');
        const algoSummaryContent = document.getElementById('algo-summary-content');
        const algoSummaryIcon = document.getElementById('algo-summary-icon');
        const algoSummaryHeader = document.getElementById('algo-summary-header');
        const stage1Instruction = document.getElementById('stage1-instruction');

        if (state.preset && state.preset.algorithm_summary) {
            if (algoSummaryWrapper) {
                algoSummaryWrapper.style.display = 'block';
            }
            if (algoSummaryContent) {
                algoSummaryContent.innerText = state.preset.algorithm_summary;
                algoSummaryContent.style.display = 'block'; // Default expanded
            }
            if (algoSummaryIcon) {
                algoSummaryIcon.className = 'bi bi-chevron-up';
            }
            if (stage1Instruction) {
                stage1Instruction.style.display = 'flex';
            }
        } else {
            if (algoSummaryWrapper) algoSummaryWrapper.style.display = 'none';
            if (stage1Instruction) stage1Instruction.style.display = 'none';
        }

        if (algoSummaryHeader) {
            algoSummaryHeader.onclick = () => {
                if (algoSummaryContent) {
                    if (algoSummaryContent.style.display === 'none') {
                        algoSummaryContent.style.display = 'block';
                        if (algoSummaryIcon) algoSummaryIcon.className = 'bi bi-chevron-up';
                    } else {
                        algoSummaryContent.style.display = 'none';
                        if (algoSummaryIcon) algoSummaryIcon.className = 'bi bi-chevron-down';
                    }
                }
            };
        }

        // Setup guided questions display & dynamic input boxes
        const questionsWrapper = document.getElementById('guided-questions-wrapper');
        const questionsList = document.getElementById('guided-questions-list');
        const questions = (state.preset && state.preset.guided_questions && state.preset.guided_questions.length > 0)
            ? state.preset.guided_questions
            : [
                "本题需要设计几个循环？循环的截止条件是什么？",
                "需要使用哪些辅助数据结构或变量（如数组、小根堆、指针等）？",
                "输入数据的读取和输出结果的打印如何对应到算法流程中？"
            ];

        if (questionsWrapper && questionsList) {
            questionsList.innerHTML = '';
            questions.forEach(q => {
                const li = document.createElement('li');
                li.innerText = q;
                questionsList.appendChild(li);
            });
            questionsWrapper.style.display = 'block';
        }

        // Render dynamic textareas for questions
        const qaWrapper = document.getElementById('stage-qa-inputs-wrapper');
        if (qaWrapper) {
            qaWrapper.innerHTML = '';
            const parsedAnswers = {};
            
            if (state.isResumed && state.stage1Description) {
                // Try parsing our format
                questions.forEach((q, index) => {
                    const qMarker = `【问题 ${index + 1}】：`;
                    const nextQMarker = `【问题 ${index + 2}】：`;
                    const startIdx = state.stage1Description.indexOf(qMarker);
                    if (startIdx !== -1) {
                        const ansMarker = "\n【回答】：";
                        const ansStart = state.stage1Description.indexOf(ansMarker, startIdx);
                        if (ansStart !== -1) {
                            const valStart = ansStart + ansMarker.length;
                            let endIdx = nextQMarker ? state.stage1Description.indexOf(nextQMarker, valStart) : -1;
                            if (endIdx === -1) {
                                endIdx = state.stage1Description.length;
                            }
                            parsedAnswers[index] = state.stage1Description.slice(valStart, endIdx).trim();
                        }
                    }
                });
            }

            questions.forEach((q, i) => {
                const qContainer = document.createElement('div');
                qContainer.className = 'qa-item';
                qContainer.style.marginBottom = '16px';

                const qLabel = document.createElement('div');
                qLabel.className = 'qa-question-label';
                qLabel.style.fontWeight = '600';
                qLabel.style.color = '#1e3a8a';
                qLabel.style.fontSize = '13.5px';
                qLabel.style.marginBottom = '6px';
                qLabel.style.display = 'flex';
                qLabel.style.alignItems = 'flex-start';
                qLabel.style.gap = '6px';
                qLabel.innerHTML = `<span class="qa-index" style="background: #3b82f6; color: white; border-radius: 50%; width: 18px; height: 18px; display: inline-flex; align-items: center; justify-content: center; font-size: 11px; flex-shrink: 0; margin-top: 2px;">${i + 1}</span> <span>${escapeHtml(q)}</span>`;
                
                const qTextarea = document.createElement('textarea');
                qTextarea.className = 'description-textarea qa-answer-textarea';
                qTextarea.id = `qa-answer-${i}`;
                qTextarea.dataset.questionIndex = i;
                qTextarea.placeholder = `请输入你对问题 ${i + 1} 的思考回答...`;
                qTextarea.style.minHeight = '70px';
                qTextarea.style.width = '100%';
                qTextarea.style.padding = '10px';
                qTextarea.style.borderRadius = '6px';
                qTextarea.style.border = '1px solid #cbd5e1';
                qTextarea.style.fontFamily = 'inherit';
                qTextarea.style.fontSize = '13px';
                qTextarea.style.resize = 'vertical';
                qTextarea.style.boxSizing = 'border-box';
                
                if (parsedAnswers[i]) {
                    qTextarea.value = parsedAnswers[i];
                } else if (state.isResumed && state.stage1Description && !state.stage1Description.includes('【问题') && i === 0) {
                    // Fallback for legacy plain description
                    qTextarea.value = state.stage1Description;
                }

                // Prevent Paste & Drop
                qTextarea.addEventListener('paste', (e) => {
                    e.preventDefault();
                    showNotification('为了确保你真正理解解题思路，此处禁止复制粘贴，请手动输入回答。', 'warning');
                });
                qTextarea.addEventListener('drop', (e) => {
                    e.preventDefault();
                    showNotification('为了确保你真正理解解题思路，此处禁止拖放文本，请手动输入回答。', 'warning');
                });

                // Small voice input button row
                const voiceRow = document.createElement('div');
                voiceRow.style.display = 'flex';
                voiceRow.style.justifyContent = 'flex-end';
                voiceRow.style.marginTop = '4px';

                const voiceBtn = document.createElement('button');
                voiceBtn.className = 'arena-btn-voice-small';
                voiceBtn.type = 'button';
                voiceBtn.innerHTML = '<i class="bi bi-mic-fill"></i> 语音输入';
                voiceBtn.onclick = () => startVoiceInput(`qa-answer-${i}`, voiceBtn);

                voiceRow.appendChild(voiceBtn);

                qContainer.appendChild(qLabel);
                qContainer.appendChild(qTextarea);
                qContainer.appendChild(voiceRow);
                qaWrapper.appendChild(qContainer);
            });

            // Focus on the first answer box
            const firstBox = qaWrapper.querySelector('.qa-answer-textarea');
            if (firstBox) firstBox.focus();
        }

        // Initialize dynamic companion chat greeting for Stage 1
        const container = document.getElementById('companion-messages');
        if (container) {
            container.innerHTML = '';
            state.companionMessages = [];
            
            if (state.isResumed && state.companionHistory && state.companionHistory.length > 0) {
                state.companionHistory.forEach(msg => {
                    appendCompanionMessage(msg.content, msg.role === 'student' ? 'student' : 'ai');
                    state.companionMessages.push({ role: msg.role === 'student' ? 'user' : 'assistant', content: msg.content });
                });
            } else {
                const problemTitle = document.querySelector('.problem-panel h2')?.innerText?.replace(/[\r\n]/g, '').replace('引导式学习 - ', '').trim() || '当前任务';
                
                let greeting = `哈罗！我是你的 AI 伴学助手。我们今天的任务是完成《${problemTitle}》。\n\n`;
                if (state.preset && state.preset.algorithm_summary) {
                    greeting += `我已为你准备好了这道题的标准算法步骤简述（见左侧「算法思路参考」）。\n\n为了帮你理清思路，请认真思考并逐一在左侧文本框内回答以下引导问题：\n`;
                } else {
                    greeting += `为了帮你理清思路，请认真思考并逐一在左侧文本框内回答以下引导问题：\n`;
                }
                
                questions.forEach((q, i) => {
                    greeting += `${i + 1}️⃣ **${q}**\n`;
                });
                
                greeting += `\n你可以结合左侧的算法流程在下方的各个问答输入框中进行作答。如果你遇到了困难，随时可以在这里向我提问哦！加油！✨`;
                
                appendCompanionMessage(greeting, 'ai');
            }
        }
    }

    function submitDescription() {
        const textareas = document.querySelectorAll('.qa-answer-textarea');
        const questions = (state.preset && state.preset.guided_questions && state.preset.guided_questions.length > 0)
            ? state.preset.guided_questions
            : [
                "本题需要设计几个循环？循环的截止条件是什么？",
                "需要使用哪些辅助数据结构或变量（如数组、小根堆、指针等）？",
                "输入数据的读取和输出结果的打印如何对应到算法流程中？"
            ];

        let answers = [];
        let emptyIndex = -1;
        let shortIndex = -1;

        textareas.forEach((ta, idx) => {
            const val = ta.value.trim();
            answers.push({
                question: questions[idx],
                answer: val
            });
            if (!val) {
                if (emptyIndex === -1) emptyIndex = idx;
            } else if (val.length < 2) {
                if (shortIndex === -1) shortIndex = idx;
            }
        });

        if (emptyIndex !== -1) {
            showNotification(`请填写问题 ${emptyIndex + 1} 的回答`, 'warning');
            const targetTa = document.querySelector(`.qa-answer-textarea[data-question-index="${emptyIndex}"]`);
            if (targetTa) targetTa.focus();
            return;
        }

        if (shortIndex !== -1) {
            showNotification(`问题 ${shortIndex + 1} 的回答太短了，请至少输入2个字`, 'warning');
            const targetTa = document.querySelector(`.qa-answer-textarea[data-question-index="${shortIndex}"]`);
            if (targetTa) targetTa.focus();
            return;
        }

        // Aggregate description
        let aggregatedDescription = "";
        answers.forEach((item, idx) => {
            aggregatedDescription += `【问题 ${idx + 1}】：${item.question}\n【回答】：${item.answer}\n\n`;
        });

        // Set value of original (hidden) textarea so the rest of the code works
        const origTextarea = document.getElementById('description-input');
        if (origTextarea) {
            origTextarea.value = aggregatedDescription;
        }

        // Show loading state on submit button to prevent "frozen" feeling
        const submitBtn = document.getElementById('stage1-submit');
        const originalBtnHtml = submitBtn ? submitBtn.innerHTML : '';
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="bi bi-hourglass-split rotating-icon"></i> 正在评判中，请稍候...';
        }
        textareas.forEach(ta => ta.disabled = true);

        setLoading(true);
        fetchJSON('/thinking/api/stage1/submit', {
            method: 'POST',
            body: JSON.stringify({
                session_id: state.sessionId,
                description: aggregatedDescription
            })
        }).then(data => {
            if (data.success) {
                state.stage1Score = data.score;
                showScoreResult(data.score, data.feedback, data.passed);

                if (data.passed) {
                    showNotification('🎉 思路描述通过！进入积木编程阶段', 'success');
                    setTimeout(() => initStage(2), 1500);
                } else {
                    // Proactively post AI Companion guidance
                    appendCompanionMessage(`我看到你的思路描述评判为 ${data.score}%，还差一点就达到通过标准啦！\n导师点评说："${data.feedback}"\n\n别灰心，你可以根据点评修改你的各个回答，然后重新提交。如果你修改有困难，可以随时在下方提问或者点击【请求提示】！`, 'ai');
                }
            }
        }).catch(err => showError(err.message))
          .finally(() => {
            setLoading(false);
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = originalBtnHtml;
            }
            textareas.forEach(ta => ta.disabled = false);
          });
    }

    function showScoreResult(score, feedback, passed) {
        const container = document.getElementById('score-result');
        if (!container) return;

        container.innerHTML = `
            <div class="score-display">
                <div class="score-circle ${passed ? 'pass' : 'fail'}">${score}%</div>
                <div class="score-feedback">${feedback}</div>
            </div>
        `;
        container.style.display = 'block';
    }

    function requestStage1Hint() {
        const textareas = document.querySelectorAll('.qa-answer-textarea');
        const questions = (state.preset && state.preset.guided_questions && state.preset.guided_questions.length > 0)
            ? state.preset.guided_questions
            : [
                "本题需要设计几个循环？循环的截止条件是什么？",
                "需要使用哪些辅助数据结构或变量（如数组、小根堆、指针等）？",
                "输入数据的读取和输出结果的打印如何对应到算法流程中？"
            ];

        let aggregatedDescription = "";
        textareas.forEach((ta, idx) => {
            const val = ta.value.trim();
            aggregatedDescription += `【问题 ${idx + 1}】：${questions[idx]}\n【回答】：${val}\n\n`;
        });

        setLoading(true);
        // Route hint request through AI Companion chat
        appendCompanionMessage('我在撰写思路描述时遇到困难，请给我一些引导提示。', 'student');

        fetchJSON('/thinking/api/stage1/hint', {
            method: 'POST',
            body: JSON.stringify({
                session_id: state.sessionId,
                description: aggregatedDescription
            })
        }).then(data => {
            if (data.success) {
                appendCompanionMessage(data.hint, 'ai');
                if (!state.companionMessages) state.companionMessages = [];
                state.companionMessages.push({ role: 'user', content: '我在撰写思路描述时遇到困难，请给我一些引导提示。' });
                state.companionMessages.push({ role: 'assistant', content: data.hint });
            }
        }).catch(err => showError(err.message))
          .finally(() => setLoading(false));
    }

    // ============================================================
    // Stage 2: Step-by-Step Quiz (Choice / Fill-in-the-Blank)
    // ============================================================
    function initStage2() {
        if (!state.preset) {
            showError('\u9884\u8bbe\u6570\u636e\u672a\u52a0\u8f7d');
            return;
        }

        state.companionMessages = [];
        state.quizAnswers = {};  // { step_id: selected_answer }

        // \u6062\u590d\u4f34\u5b66\u52a9\u624b\u804a\u5929\u8bb0\u5f55
        if (state.isResumed && state.companionHistory && state.companionHistory.length > 0) {
            const container = document.getElementById('companion-messages');
            if (container) {
                container.innerHTML = '';
                state.companionHistory.forEach(msg => {
                    appendCompanionMessage(msg.content, msg.role === 'student' ? 'student' : 'ai');
                    state.companionMessages.push({ role: msg.role === 'student' ? 'user' : 'assistant', content: msg.content });
                });
            }
        } else {
            const greeting = '\u592a\u68d2\u4e86\uff01\u7b2c\u4e00\u9636\u6bb5\u7684\u601d\u8def\u63cf\u8ff0\u987a\u5229\u901a\u5173\uff01\ud83c\udf89\n\n\u63a5\u4e0b\u6765\u662f\u7b2c\u4e8c\u9636\u6bb5\uff1a**\u7a0b\u5e8f\u6784\u5efa**\u3002\u6211\u4eec\u9700\u8981\u901a\u8fc7\u9010\u6b65\u56de\u7b54\u95ee\u9898\u6765\u642d\u5efa\u5b8c\u6574\u7684\u7a0b\u5e8f\u4ee3\u7801\uff1a\n1\ufe0f\u20e3 **\u9605\u8bfb\u9898\u76ee**\uff1a\u6bcf\u9053\u9898\u5bf9\u5e94\u7a0b\u5e8f\u4e2d\u7684\u4e00\u6761\u5173\u952e\u8bed\u53e5\u3002\n2\ufe0f\u20e3 **\u9009\u62e9\u6216\u586b\u7a7a**\uff1a\u9009\u62e9\u9898\u9700\u8981\u4ece\u9009\u9879\u4e2d\u9009\u51fa\u6b63\u786e\u4ee3\u7801\uff0c\u586b\u7a7a\u9898\u9700\u8981\u4f60\u624b\u52a8\u8f93\u5165\u4ee3\u7801\u7247\u6bb5\u3002\n3\ufe0f\u20e3 **\u5b9e\u65f6\u9884\u89c8**\uff1a\u53f3\u4fa7\u4f1a\u5b9e\u65f6\u663e\u793a\u4f60\u6784\u5efa\u51fa\u7684\u5b8c\u6574\u4ee3\u7801\u3002\n4\ufe0f\u20e3 **\u6ce8\u610f\u9677\u9631**\uff1a\u9009\u62e9\u9898\u4e2d\u6709\u4e9b\u9009\u9879\u5305\u542b\u5fae\u5c0f\u7684\u903b\u8f91\u9519\u8bef\uff0c\u8981\u4ed4\u7ec6\u8fa8\u522b\uff01\n\n\u9047\u5230\u56f0\u96be\u968f\u65f6\u53ef\u4ee5\u70b9\u51fb\u3010\u8bf7\u6c42\u63d0\u793a\u3011\u6216\u5728\u4e0b\u65b9\u95ee\u6211\uff01';
            appendCompanionMessage(greeting, 'ai');
        }

        // \u83b7\u53d6 quiz_steps \u6570\u636e
        const quizSteps = state.preset.quiz_steps || [];
        if (quizSteps.length === 0) {
            showNotification('\u8be5\u9898\u76ee\u5c1a\u672a\u751f\u6210\u9009\u62e9/\u586b\u7a7a\u9898\u6570\u636e\uff0c\u8bf7\u91cd\u65b0\u751f\u6210\u9884\u8bbe', 'warning');
            return;
        }

        // \u6062\u590d\u4e4b\u524d\u7684\u7b54\u9898\u72b6\u6001
        if (state.isResumed && state.stage2BlockOrder) {
            try {
                const savedAnswers = typeof state.stage2BlockOrder === 'string'
                    ? JSON.parse(state.stage2BlockOrder) : state.stage2BlockOrder;
                if (savedAnswers && typeof savedAnswers === 'object' && !Array.isArray(savedAnswers)) {
                    state.quizAnswers = savedAnswers;
                }
            } catch(e) { /* ignore parse errors */ }
        }

        const container = document.getElementById('stage2-quiz-container');
        if (!container) return;
        container.innerHTML = '';

        // \u6309 part_name \u5206\u7ec4\uff0c\u751f\u6210\u5206\u533a\u6807\u9898
        let currentPart = '';
        quizSteps.forEach((step, idx) => {
            const partName = step.part_name || '\u6838\u5fc3\u7a0b\u5e8f';
            if (partName !== currentPart) {
                currentPart = partName;
                const partHeader = document.createElement('div');
                partHeader.className = 'quiz-part-header';
                partHeader.innerHTML = `<i class="bi bi-code-square"></i> ${escapeHtml(partName)}`;
                container.appendChild(partHeader);
            }

            const card = document.createElement('div');
            card.className = 'quiz-step-card';
            card.id = `quiz-step-${step.step_id}`;
            card.dataset.stepId = step.step_id;
            card.dataset.type = step.type;

            const stepNum = `<span class="quiz-step-num">${step.step_id}</span>`;
            const questionHtml = `<div class="quiz-step-question">${stepNum} ${escapeHtml(step.question)}</div>`;

            let answerHtml = '';
            if (step.type === 'choice') {
                const options = step.options || [];
                answerHtml = '<div class="quiz-choice-options">';
                options.forEach((opt, oidx) => {
                    const optId = `quiz-${step.step_id}-opt-${oidx}`;
                    const isChecked = state.quizAnswers[step.step_id] === opt ? 'checked' : '';
                    answerHtml += `
                        <label class="quiz-choice-option ${isChecked ? 'selected' : ''}" for="${optId}">
                            <input type="radio" name="quiz-step-${step.step_id}" id="${optId}"
                                   value="${escapeHtml(opt)}" ${isChecked}
                                   onchange="ThinkingArena.onQuizAnswer(${step.step_id}, this.value, this)">
                            <code>${escapeHtml(opt)}</code>
                        </label>`;
                });
                answerHtml += '</div>';
            } else if (step.type === 'fill_blank') {
                const ctxBefore = step.context_before || '';
                const ctxAfter = step.context_after || '';
                const savedVal = state.quizAnswers[step.step_id] || '';
                answerHtml = '<div class="quiz-fill-container">';
                if (ctxBefore) {
                    answerHtml += `<code class="quiz-fill-context">${escapeHtml(ctxBefore)}</code>`;
                }
                answerHtml += `<input type="text" class="quiz-fill-input" id="quiz-fill-${step.step_id}"
                                     placeholder="${escapeHtml(step.blank_hint || '\u8bf7\u8f93\u5165\u4ee3\u7801...')}"
                                     value="${escapeHtml(savedVal)}"
                                     oninput="ThinkingArena.onQuizFillInput(${step.step_id}, this.value)"
                                     onblur="ThinkingArena.onQuizFillInput(${step.step_id}, this.value)">`;
                if (ctxAfter) {
                    answerHtml += `<code class="quiz-fill-context">${escapeHtml(ctxAfter)}</code>`;
                }
                answerHtml += '</div>';
            }

            const feedbackHtml = `<div class="quiz-step-feedback" id="quiz-feedback-${step.step_id}"></div>`;

            card.innerHTML = questionHtml + answerHtml + feedbackHtml;
            container.appendChild(card);
        });

        updateQuizPreview();
    }

    function onQuizAnswer(stepId, value, inputEl) {
        state.quizAnswers[stepId] = value;
        // Update visual selection state
        const card = document.getElementById(`quiz-step-${stepId}`);
        if (card) {
            card.querySelectorAll('.quiz-choice-option').forEach(opt => {
                opt.classList.remove('selected');
            });
            if (inputEl) {
                inputEl.closest('.quiz-choice-option').classList.add('selected');
            }
        }
        updateQuizPreview();
    }

    function onQuizFillInput(stepId, value) {
        state.quizAnswers[stepId] = value.trim();
        updateQuizPreview();
    }

    function getNormalizedIndent(indent) {
        let val = parseInt(indent);
        if (isNaN(val)) return 0;
        // 如果 AI 返回的是空格数（如 4, 8, 12），则转换为缩进级别
        if (val >= 4) {
            val = Math.floor(val / 4);
        }
        // 限制最大缩进层级为 3 层，防止缩进过多偏离视口
        return Math.min(Math.max(0, val), 3);
    }

    function updateQuizPreview() {
        const quizSteps = state.preset.quiz_steps || [];
        if (quizSteps.length === 0) return;

        // Group steps by part_name, preserving order
        const parts = [];
        const partMap = {};
        quizSteps.forEach(step => {
            const pName = step.part_name || '核心程序';
            if (!partMap[pName]) {
                const pData = {
                    part_name: pName,
                    part_header: (step.part_header || 'int main() {').replace('{{', '{').replace('}}', '}'),
                    part_footer: (step.part_footer || '    return 0;\n}').replace('{{', '{').replace('}}', '}'),
                    steps: []
                };
                partMap[pName] = pData;
                parts.push(pData);
            }
            partMap[pName].steps.push(step);
        });

        let preview = '#include <iostream>\nusing namespace std;\n\n';
        parts.forEach(part => {
            preview += part.part_header + '\n';
            part.steps.forEach(step => {
                const answer = state.quizAnswers[step.step_id];
                const level = getNormalizedIndent(step.indent);
                const indent = '    ' + '    '.repeat(level);
                if (answer) {
                    const codeLine = (answer === step.correct_answer && step.code_line) ? step.code_line : answer;
                    preview += indent + codeLine + '\n';
                } else {
                    preview += indent + `// Step ${step.step_id}: ???\n`;
                }
            });
            preview += part.part_footer + '\n\n';
        });

        const previewEl = document.getElementById('code-preview');
        if (previewEl) {
            previewEl.textContent = preview;
        }
    }

    function normalizeCppCode(code) {
        if (!code) return '';
        let s = code.replace(/\s+/g, ' ').trim();
        let regex = /\s*([+*\/%=<>!&|^~?:,;\(\)\[\]\{\}-])\s*/g;
        s = s.replace(regex, '$1');
        return s;
    }

    function getQuizAnswers() {
        return state.quizAnswers || {};
    }

    function verifyQuiz() {
        const quizSteps = state.preset.quiz_steps || [];
        const answers = state.quizAnswers || {};

        // Check if all steps have been answered
        const unanswered = quizSteps.filter(s => !answers[s.step_id] || answers[s.step_id].trim() === '');
        if (unanswered.length > 0) {
            showNotification(`\u8fd8\u6709 ${unanswered.length} \u9053\u9898\u672a\u4f5c\u7b54\uff0c\u8bf7\u5b8c\u6210\u6240\u6709\u6b65\u9aa4\u540e\u518d\u9a8c\u8bc1`, 'warning');
            const firstUnanswered = document.getElementById(`quiz-step-${unanswered[0].step_id}`);
            if (firstUnanswered) firstUnanswered.scrollIntoView({ behavior: 'smooth', block: 'center' });
            return;
        }

        setLoading(true);
        fetchJSON('/thinking/api/stage2/verify', {
            method: 'POST',
            body: JSON.stringify({
                session_id: state.sessionId,
                block_order: state.quizAnswers,
                quiz_answers: state.quizAnswers
            })
        }).then(data => {
            if (data.success) {
                const wrongSteps = data.wrong_steps || [];
                const feedbackDetails = data.feedback_details || {};

                // Update visual correctness state for all cards based on server response
                quizSteps.forEach(step => {
                    const card = document.getElementById(`quiz-step-${step.step_id}`);
                    const feedbackEl = document.getElementById(`quiz-feedback-${step.step_id}`);
                    const isWrong = wrongSteps.includes(String(step.step_id));

                    if (card) {
                        card.classList.remove('quiz-step-correct', 'quiz-step-wrong');
                        card.classList.add(isWrong ? 'quiz-step-wrong' : 'quiz-step-correct');
                    }

                    if (feedbackEl) {
                        if (!isWrong) {
                            feedbackEl.innerHTML = '<i class="bi bi-check-circle-fill" style="color: #22c55e;"></i> \u6b63\u786e\uff01';
                            feedbackEl.className = 'quiz-step-feedback feedback-correct';
                        } else {
                            const expl = feedbackDetails[step.step_id] || step.explanation || '\u8bf7\u518d\u60f3\u60f3';
                            feedbackEl.innerHTML = `<i class="bi bi-x-circle-fill" style="color: #ef4444;"></i> ${escapeHtml(expl)}`;
                            feedbackEl.className = 'quiz-step-feedback feedback-wrong';
                        }
                    }
                });

                if (data.passed) {
                    showNotification('\ud83c\udf89 \u606d\u559c\uff01\u6240\u6709\u7b54\u6848\u6b63\u786e\uff0c\u4ee3\u7801\u6784\u5efa\u6210\u529f\uff01', 'success');
                    appendCompanionMessage('\u592a\u68d2\u4e86\uff01\u4f60\u7684\u6240\u6709\u7b54\u6848\u90fd\u5b8c\u5168\u6b63\u786e\uff01\u7a0b\u5e8f\u5df2\u7ecf\u6210\u529f\u6784\u5efa\uff01\ud83d\udc4d\n\n\u73b0\u5728\u7cfb\u7edf\u4f1a\u4e3a\u4f60\u4fdd\u5b58\u8fdb\u5ea6\u5e76\u8fdb\u5165\u4e0b\u4e00\u9636\u6bb5\u3002', 'ai');
                    state.currentStage = 3;
                    setTimeout(() => {
                        location.reload();
                    }, 2000);
                } else {
                    showNotification(`\u6709 ${wrongSteps.length} \u9053\u6b65\u9aa4\u7684\u7b54\u6848\u4e0d\u6b63\u786e\uff0c\u8bf7\u6839\u636e\u63d0\u793a\u8fdb\u884c\u8c03\u657e`, 'warning');
                    appendCompanionMessage(`\u63d0\u793a\uff1a\u6709 ${wrongSteps.length} \u9053\u9898\u7684\u7b54\u6848\u8fd8\u4e0d\u5b8c\u5168\u6b63\u786e\u3002\u6211\u5728\u9519\u9898\u65c1\u6807\u6ce8\u4e86\u5177\u4f53\u7684\u4fee\u6539\u5efa\u8bae\uff0c\u8f66\u5bf9\u7167\u4fee\u6539\u3002\u5982\u679c\u8fd8\u6709\u7591\u95ee\uff0c\u53ef\u4ee5\u968f\u65f6\u95ee\u6211\u54e6\uff01`, 'ai');
                }
            } else {
                showNotification(data.feedback || '\u9a8c\u8bc1\u672a\u901a\u8fc7', 'warning');
            }
        }).catch(err => showError(err.message))
          .finally(() => setLoading(false));
    }

    function requestStage2Hint() {
        setLoading(true);
        appendCompanionMessage('\u6211\u5728\u6784\u5efa\u7a0b\u5e8f\u65f6\u9047\u5230\u56f0\u96be\uff0c\u8bf7\u7ed9\u6211\u4e00\u4e9b\u5f15\u5bfc\u63d0\u793a\u3002', 'student');

        const quizSteps = state.preset.quiz_steps || [];
        const answers = state.quizAnswers || {};
        const currentState = quizSteps.map(s => ({
            step_id: s.step_id,
            question: s.question,
            answered: !!answers[s.step_id],
            student_answer: answers[s.step_id] || null
        }));

        fetchJSON('/thinking/api/stage2/hint', {
            method: 'POST',
            body: JSON.stringify({
                session_id: state.sessionId,
                current_blocks: Object.keys(answers),
                quiz_state: currentState
            })
        }).then(data => {
            if (data.success) {
                appendCompanionMessage(data.hint, 'ai');
                if (!state.companionMessages) state.companionMessages = [];
                state.companionMessages.push({ role: 'user', content: '\u6211\u5728\u6784\u5efa\u7a0b\u5e8f\u65f6\u9047\u5230\u56f0\u96be\uff0c\u8bf7\u7ed9\u6211\u4e00\u4e9b\u5f15\u5bfc\u63d0\u793a\u3002' });
                state.companionMessages.push({ role: 'assistant', content: data.hint });
            }
        }).catch(err => showError(err.message))
          .finally(() => setLoading(false));
    }

    function collectStudentState() {
        const studentState = {
            stage1: {},
            stage2: {},
            stage3: {}
        };

        // 1. Stage 1 Q&A answers
        const qaAnswers = [];
        document.querySelectorAll('.qa-answer-textarea').forEach(ta => {
            const index = ta.dataset.questionIndex;
            const value = ta.value.trim();
            let questionText = "";
            const parent = ta.parentElement;
            if (parent) {
                const labelSpan = parent.querySelector('.qa-question-label span:not(.qa-index)');
                if (labelSpan) {
                    questionText = labelSpan.textContent.trim();
                }
            }
            qaAnswers.push({
                question: questionText,
                answer: value
            });
        });
        studentState.stage1.qa_answers = qaAnswers;

        // 2. Stage 2 quiz state
        const quizSteps = (state.preset && state.preset.quiz_steps) || [];
        const answers = state.quizAnswers || {};
        const stepsState = quizSteps.map(step => {
            const studentAns = (answers[step.step_id] || '').trim();
            const correctAns = (step.correct_answer || '').trim();
            const isCorrect = studentAns ? (normalizeCppCode(studentAns) === normalizeCppCode(correctAns)) : false;
            return {
                step_id: step.step_id,
                question: step.question,
                student_answer: studentAns || null,
                correct_answer: correctAns,
                is_correct: isCorrect
            };
        });

        studentState.stage2 = {
            is_quiz: true,
            answered_count: quizSteps.filter(s => answers[s.step_id]).length,
            total_count: quizSteps.length,
            steps: stepsState
        };

        // 3. Stage 3 code fix state
        const codeFixInput = document.getElementById('code-fix-input');
        studentState.stage3.current_fixed_code = codeFixInput ? codeFixInput.value : '';

        return studentState;
    }

    function sendCompanionChat() {
        const input = document.getElementById('companion-chat-input');
        if (!input) return;
        const msgText = input.value.trim();
        if (!msgText) return;

        input.value = '';
        appendCompanionMessage(msgText, 'student');
        sendCompanionQueryStream(msgText);
    }

    function sendCompanionQueryStream(msgText) {
        const messages = state.companionMessages || [];
        messages.push({ role: 'user', content: msgText });
        state.companionMessages = messages;

        const container = document.getElementById('companion-messages');
        const typingId = 'typing-' + Date.now();
        if (container) {
            const typingDiv = document.createElement('div');
            typingDiv.className = 'chat-message';
            typingDiv.id = typingId;
            typingDiv.innerHTML = `
                <div class="chat-avatar teacher">🤖</div>
                <div class="chat-bubble ai"><span class="typing-dots">思考引导中...</span></div>
            `;
            container.appendChild(typingDiv);
            container.scrollTop = container.scrollHeight;
        }

        // 构造伴学对话请求体，注入当前的阶段及积木状态
        const requestBody = {
            session_id: state.sessionId,
            messages: messages,
            current_stage: state.currentStage,
            student_state: collectStudentState()
        };

        if (state.currentStage === 2) {
            requestBody.stage2_state = requestBody.student_state.stage2;
        }

        fetchJSON('/thinking/api/companion/chat', {
            method: 'POST',
            body: JSON.stringify(requestBody)
        }).then(data => {
            const typingEl = document.getElementById(typingId);
            if (typingEl) typingEl.remove();

            if (data.success) {
                messages.push({ role: 'assistant', content: data.response });
                appendCompanionMessage(data.response, 'ai');
            } else {
                appendCompanionMessage('连接错误，请重试。', 'ai');
            }
        }).catch(err => {
            const typingEl = document.getElementById(typingId);
            if (typingEl) typingEl.remove();
            appendCompanionMessage('连接服务器失败，请重试。', 'ai');
        });
    }

    function appendCompanionMessage(text, sender) {
        const container = document.getElementById('companion-messages');
        if (!container) return;

        const isUser = sender === 'student';
        const avatarClass = isUser ? 'student' : 'teacher';
        const avatarIcon = isUser ? '👤' : '🤖';

        const msgDiv = document.createElement('div');
        msgDiv.className = `chat-message ${isUser ? 'user' : ''}`;
        msgDiv.innerHTML = `
            <div class="chat-avatar ${avatarClass}">${avatarIcon}</div>
            <div class="chat-bubble ${isUser ? 'user-msg' : 'ai'}">${renderMarkdown(text)}</div>
        `;
        container.appendChild(msgDiv);
        container.scrollTop = container.scrollHeight;
    }

    function regeneratePreset() {
        if (!confirm('确定要应用最新大括号归拢规范，重新拆解并生成当前作业的代码积木吗？')) return;

        const container = document.getElementById('arena-container');
        const assignmentId = container ? container.dataset.assignmentId : null;
        if (!assignmentId) return;

        setLoading(true);
        showNotification('正在应用全新整合规则重构积木池，请稍候...', 'info');

        fetchJSON('/thinking/api/generate_preset', {
            method: 'POST',
            body: JSON.stringify({ assignment_id: parseInt(assignmentId) })
        }).then(data => {
            if (data.success || data.status === 'ready') {
                showNotification('✨ 积木重构成功！正在重新加载版面', 'success');
                setTimeout(() => location.reload(), 1500);
            } else {
                showNotification('重构已触发，请稍后手动刷新', 'warning');
            }
        }).catch(err => showError(err.message))
          .finally(() => setLoading(false));
    }

    // ============================================================
    // Stage 3: Feynman Teaching (Dual Agent)
    // ============================================================
    function initStage3() {
        state.teacherMessages = [];
        state.studentMessages = [];
        state.feynmanPhase = 'chat';

        // 恢复老师辅导对话
        let restoredTeacher = false;
        if (state.isResumed && state.teacherHistory && state.teacherHistory.length > 0) {
            const container = document.getElementById('teacher-messages');
            if (container) {
                container.innerHTML = '';
                state.teacherHistory.forEach(msg => {
                    addChatMessage('teacher', msg.role, msg.content);
                    state.teacherMessages.push({ role: msg.role, content: msg.content });
                });
                restoredTeacher = true;
            }
        }
        if (!restoredTeacher) {
            addChatMessage('teacher', 'assistant',
                '你好！你已经完成了积木编程挑战，说明你对这道题有了不错的理解。现在我们来做一个更有趣的练习——你需要把你学到的东西教给你的同学小明（他刚开始学编程）。准备好了吗？');
        }

        // 恢复教学生（小明）对话
        let restoredStudent = false;
        if (state.isResumed && state.studentHistory && state.studentHistory.length > 0) {
            const container = document.getElementById('student-messages');
            if (container) {
                container.innerHTML = '';
                state.studentHistory.forEach(msg => {
                    addChatMessage('student', msg.role, msg.content);
                    state.studentMessages.push({ role: msg.role, content: msg.content });
                });
                restoredStudent = true;
            }
        }
        if (!restoredStudent) {
            addChatMessage('student', 'assistant',
                '嗨！听说你这道题做得很好，老师让你教教我😅 我刚开始学编程，你能给我讲讲这道题要怎么做吗？');
        }

        // 恢复代码修复面板
        if (state.isResumed && state.buggyCodeInfo) {
            state.feynmanPhase = 'code_review';
            state.buggyCode = state.buggyCodeInfo.buggy_code;
            showCodeReviewPanel(state.buggyCodeInfo.buggy_code);
        }
    }

    function sendTeacherChat() {
        const input = document.getElementById('teacher-chat-input');
        const message = input ? input.value.trim() : '';
        if (!message || state.isLoading) return;

        // Add user message to UI
        addChatMessage('teacher', 'user', message);
        state.teacherMessages.push({ role: 'user', content: message });
        input.value = '';

        // Show typing indicator
        showTypingIndicator('teacher');

        fetchJSON('/thinking/api/stage3/chat', {
            method: 'POST',
            body: JSON.stringify({
                session_id: state.sessionId,
                messages: state.teacherMessages,
                student_state: collectStudentState()
            })
        }).then(data => {
            hideTypingIndicator('teacher');
            if (data.success) {
                addChatMessage('teacher', 'assistant', data.response);
                state.teacherMessages.push({ role: 'assistant', content: data.response });
            }
        }).catch(err => {
            hideTypingIndicator('teacher');
            showError(err.message);
        });
    }

    function sendStudentChat() {
        const input = document.getElementById('student-chat-input');
        const message = input ? input.value.trim() : '';
        if (!message || state.isLoading) return;

        addChatMessage('student', 'user', message);
        state.studentMessages.push({ role: 'user', content: message });
        input.value = '';

        showTypingIndicator('student');

        fetchJSON('/thinking/api/stage3/teach', {
            method: 'POST',
            body: JSON.stringify({
                session_id: state.sessionId,
                messages: state.studentMessages,
                student_state: collectStudentState()
            })
        }).then(data => {
            hideTypingIndicator('student');
            if (data.success) {
                addChatMessage('student', 'assistant', data.response);
                state.studentMessages.push({ role: 'assistant', content: data.response });

                // Check if ready for code writing phase
                if (data.ready_for_code && state.feynmanPhase === 'chat') {
                    setTimeout(() => triggerCodeWritingPhase(), 2000);
                }
            }
        }).catch(err => {
            hideTypingIndicator('student');
            showError(err.message);
        });
    }

    function triggerCodeWritingPhase() {
        state.feynmanPhase = 'code_review';

        showTypingIndicator('student');

        fetchJSON('/thinking/api/stage3/write_code', {
            method: 'POST',
            body: JSON.stringify({
                session_id: state.sessionId,
                messages: state.studentMessages
            })
        }).then(data => {
            hideTypingIndicator('student');
            if (data.success) {
                state.buggyCode = data.buggy_code;

                // Show the "bad student" message
                addChatMessage('student', 'assistant', data.message);
                state.studentMessages.push({ role: 'assistant', content: data.message });

                // Show code review panel
                showCodeReviewPanel(data.buggy_code);
            }
        }).catch(err => {
            hideTypingIndicator('student');
            showError(err.message);
        });
    }

    function showCodeReviewPanel(buggyCode) {
        const panel = document.getElementById('code-review-section');
        if (!panel) return;

        panel.innerHTML = `
            <div class="code-review-panel">
                <div class="code-review-header">
                    <i class="bi bi-exclamation-triangle"></i>
                    修改小明的错误代码并提交
                </div>
                <div class="code-review-body">
                    <textarea class="code-fix-input" id="code-fix-input"
                              style="font-family: var(--arena-mono); font-size: 13px;"
                              placeholder="你可以修改代码，或者用文字描述哪里有问题、应该怎么改..."></textarea>
                    <div style="margin-top: 12px; display: flex; gap: 10px;">
                        <button class="arena-btn arena-btn-primary" onclick="window.ThinkingArena.submitCodeFix()">
                            <i class="bi bi-check2-circle"></i> 提交修复
                        </button>
                    </div>
                </div>
            </div>
        `;
        panel.style.display = 'block';

        // Pre-fill with buggy code for editing
        const fixInput = document.getElementById('code-fix-input');
        if (fixInput) {
            fixInput.value = buggyCode;
            
            // Auto-adjust height to display the code completely without vertical scrollbar
            const adjustHeight = () => {
                fixInput.style.height = 'auto';
                fixInput.style.height = (fixInput.scrollHeight + 10) + 'px';
            };
            
            // Adjust height immediately
            adjustHeight();
            
            // Bind input listener to adjust height dynamically as they edit
            fixInput.addEventListener('input', adjustHeight);
        }
    }

    function submitCodeFix() {
        const fixInput = document.getElementById('code-fix-input');
        const fixedCode = fixInput ? fixInput.value.trim() : '';

        if (!fixedCode) {
            showNotification('请修改代码或描述问题所在', 'warning');
            return;
        }

        setLoading(true);
        fetchJSON('/thinking/api/stage3/fix_code', {
            method: 'POST',
            body: JSON.stringify({
                session_id: state.sessionId,
                buggy_code: state.buggyCode,
                fixed_code: fixedCode
            })
        }).then(data => {
            if (data.success) {
                if (data.correct) {
                    state.feynmanPhase = 'completed';
                    addChatMessage('student', 'assistant',
                        '哦！原来是这样！谢谢你帮我找出来了，我以后会注意的！🎉');
                    setTimeout(() => showCelebration(), 1000);
                    completeSession();
                } else {
                    showNotification(data.feedback || '修复不太对，再看看？', 'warning');
                    addChatMessage('student', 'assistant',
                        '嗯...我觉得好像还是不太对。你再帮我看看？' + (data.feedback ? '\n（' + data.feedback + '）' : ''));
                }
            }
        }).catch(err => showError(err.message))
          .finally(() => setLoading(false));
    }

    function completeSession() {
        const elapsed = Math.floor((Date.now() - state.startTime) / 1000);
        fetchJSON('/thinking/api/complete_session', {
            method: 'POST',
            body: JSON.stringify({
                session_id: state.sessionId,
                total_time_seconds: elapsed
            })
        });
    }

    // ============================================================
    // Chat UI Helpers
    // ============================================================
    function addChatMessage(panel, role, content) {
        const container = document.getElementById(`${panel}-messages`);
        if (!container) return;

        const isUser = role === 'user';
        const avatarClass = isUser ? 'student' : (panel === 'teacher' ? 'teacher' : 'bad-student');
        const avatarIcon = isUser ? '👤' : (panel === 'teacher' ? '👨‍🏫' : '🧑‍🎓');

        const msgDiv = document.createElement('div');
        msgDiv.className = `chat-message ${isUser ? 'user' : ''}`;
        msgDiv.innerHTML = `
            <div class="chat-avatar ${avatarClass}">${avatarIcon}</div>
            <div class="chat-bubble ${isUser ? 'user-msg' : 'ai'}">${renderMarkdown(content)}</div>
        `;
        container.appendChild(msgDiv);
        container.scrollTop = container.scrollHeight;
    }

    function showTypingIndicator(panel) {
        const container = document.getElementById(`${panel}-messages`);
        if (!container) return;

        const existing = container.querySelector('.typing-indicator');
        if (existing) return;

        const div = document.createElement('div');
        div.className = 'typing-indicator';
        div.innerHTML = '<span></span><span></span><span></span>';
        container.appendChild(div);
        container.scrollTop = container.scrollHeight;
    }

    function hideTypingIndicator(panel) {
        const container = document.getElementById(`${panel}-messages`);
        if (!container) return;
        const indicator = container.querySelector('.typing-indicator');
        if (indicator) indicator.remove();
    }

    // ============================================================
    // UI Helpers
    // ============================================================
    function showHint(hint, containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;

        const div = document.createElement('div');
        div.className = 'hint-bubble';
        div.innerHTML = `<i class="bi bi-lightbulb"></i><span>${renderMarkdown(hint)}</span>`;
        container.appendChild(div);
        container.scrollTop = container.scrollHeight;
    }

    function showNotification(message, type) {
        // Reuse or create Bootstrap toast container
        let toastContainer = document.querySelector('.toast-container');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.className = 'toast-container position-fixed bottom-0 end-0 p-3';
            toastContainer.style.zIndex = '999999';
            document.body.appendChild(toastContainer);
        }

        if (typeof bootstrap !== 'undefined') {
            const toastEl = document.createElement('div');
            // Choose color based on notification type
            const bgClass = type === 'success' ? 'bg-success' : type === 'warning' ? 'bg-warning text-dark' : type === 'danger' ? 'bg-danger' : 'bg-info text-dark';
            toastEl.className = `toast align-items-center text-white ${bgClass} border-0`;
            toastEl.setAttribute('role', 'alert');
            toastEl.setAttribute('aria-live', 'assertive');
            toastEl.setAttribute('aria-atomic', 'true');
            toastEl.innerHTML = `
                <div class="toast-header">
                    <strong class="me-auto">${type === 'success' ? '✅' : type === 'warning' ? '⚠️' : 'ℹ️'}</strong>
                    <button type="button" class="btn-close" data-bs-dismiss="toast"></button>
                </div>
                <div class="toast-body">${message}</div>
            `;
            toastContainer.appendChild(toastEl);
            const toast = new bootstrap.Toast(toastEl, { delay: 4000 });
            toast.show();
            return;
        }
        // Fallback
        console.log(`[${type}] ${message}`);
    }

    function showError(message) {
        showNotification(message, 'danger');
    }

    // ============================================================
    // Developer Debug Mode (localhost / 127.0.0.1 only)
    // ============================================================
    function initDevDebugConsole() {
        const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
        const container = document.getElementById('arena-container');
        const isDemo = container && container.dataset.demoExperience === '1';
        if (!isLocal && !isDemo) return;

        const panelTitle = isDemo ? '体验进度快捷入口' : '开发者调试面板 (Dev Only)';
        const panelDescription = isDemo
            ? '按需查看三个学习阶段的页面效果，完成体验后可重新回到任意阶段。'
            : '快速进行阶段流转及自动化测试';

        const panel = document.createElement('div');
        panel.className = 'dev-debug-panel';
        panel.innerHTML = `
            <h4><i class="bi bi-braces-asterisk"></i> ${panelTitle}</h4>
            <div style="font-size: 11px; margin-bottom: 8px; color: #94a3b8;">${panelDescription}</div>
            <div class="dev-debug-btn-group">
                <button class="dev-debug-btn" onclick="window.ThinkingArena.debugJumpStage(1)">跳到阶段一</button>
                <button class="dev-debug-btn" onclick="window.ThinkingArena.debugJumpStage(2)">跳到阶段二</button>
                <button class="dev-debug-btn" onclick="window.ThinkingArena.debugJumpStage(3)">跳到阶段三</button>
                <button class="dev-debug-btn dev-debug-btn-success" onclick="window.ThinkingArena.debugJumpStage(4)">一键通关</button>
            </div>
            <div class="dev-debug-btn-group" style="margin-bottom: 0;">
                <button class="dev-debug-auto dev-debug-btn dev-debug-btn-primary dev-debug-btn-full" onclick="window.ThinkingArena.debugAutoS1()">秒杀阶段一 (Auto S1)</button>
                <button class="dev-debug-auto dev-debug-btn dev-debug-btn-primary dev-debug-btn-full" onclick="window.ThinkingArena.debugAutoS2()" style="margin-top: 6px;">秒杀阶段二 (Auto S2)</button>
            </div>
        `;
        if (isDemo) {
            panel.querySelectorAll('.dev-debug-auto').forEach(button => button.remove());
        }
        document.body.appendChild(panel);
    }

    function debugJumpStage(stage) {
        if (!state.sessionId) {
            showNotification('会话未初始化，无法跳转', 'warning');
            return;
        }
        setLoading(true);
        fetchJSON('/thinking/api/debug/jump_stage', {
            method: 'POST',
            body: JSON.stringify({
                session_id: state.sessionId,
                stage: stage
            })
        }).then(data => {
            if (data.success) {
                showNotification(`已切换到阶段 ${stage === 4 ? '已完成' : stage}`, 'success');
                const arena = document.getElementById('arena-container');
                const isDemo = arena && arena.dataset.demoExperience === '1';
                if (stage === 4 && isDemo) {
                    state.currentStage = 3;
                    showCelebration();
                } else {
                    setTimeout(() => location.reload(), 1000);
                }
            } else {
                showNotification(data.error || '跳转失败', 'warning');
            }
        }).catch(err => showNotification('网络错误: ' + err.message, 'danger'))
          .finally(() => setLoading(false));
    }

    function debugAutoS1() {
        if (state.currentStage !== 1) {
            showNotification('必须在阶段一才能使用此功能', 'warning');
            return;
        }
        if (!state.preset || !state.preset.blocks) {
            showNotification('无预设积木数据，无法自动填充', 'warning');
            return;
        }
        const nonNoiseBlocks = state.preset.blocks.filter(b => !b.id.startsWith('noise-'));
        if (nonNoiseBlocks.length === 0) {
            showNotification('预设积木数据不完整', 'warning');
            return;
        }

        const textareas = document.querySelectorAll('.qa-answer-textarea');
        if (textareas.length === 0) return;

        const stepTexts = nonNoiseBlocks.map(b => b.label || b.code);
        const chunkSize = Math.ceil(stepTexts.length / textareas.length);
        
        textareas.forEach((ta, idx) => {
            const start = idx * chunkSize;
            const end = start + chunkSize;
            const chunk = stepTexts.slice(start, end).join('。');
            ta.value = `首先，我们通过以下核心步骤来实现这部分逻辑：${chunk}。`;
        });

        showNotification('已自动填入标准思路，正在提交评判...', 'info');
        submitDescription();
    }

    function debugAutoS2() {
        if (state.currentStage !== 2) {
            showNotification('必须在阶段二才能使用此功能', 'warning');
            return;
        }
        if (!state.preset || !state.preset.quiz_steps) {
            showNotification('缺少逐步问答预设数据', 'warning');
            return;
        }

        const quizSteps = state.preset.quiz_steps || [];
        quizSteps.forEach(step => {
            state.quizAnswers[step.step_id] = step.correct_answer;
            // Also populate inputs in the UI
            const inputEl = document.getElementById(`quiz-fill-${step.step_id}`);
            if (inputEl) {
                inputEl.value = step.correct_answer;
            }
            const radioEl = document.querySelector(`input[name="quiz-step-${step.step_id}"][value="${escapeHtml(step.correct_answer)}"]`);
            if (radioEl) {
                radioEl.checked = true;
                const optionEl = radioEl.closest('.quiz-choice-option');
                if (optionEl) optionEl.classList.add('selected');
            }
        });

        updateQuizPreview();
        showNotification('已自动填入标准答案，正在提交验证...', 'info');
        verifyQuiz();
    }

    function showCelebration() {
        const elapsed = Math.floor((Date.now() - state.startTime) / 1000);
        const minutes = Math.floor(elapsed / 60);
        const seconds = elapsed % 60;

        const overlay = document.createElement('div');
        overlay.className = 'celebration-overlay';
        overlay.innerHTML = `
            <div class="celebration-card">
                <div class="celebration-icon">🏆</div>
                <div class="celebration-title">三阶段学习完成！</div>
                <div class="celebration-subtitle">
                    你成功完成了思路描述、积木编程和费曼教学三个阶段。<br>
                    总用时: ${minutes}分${seconds}秒
                </div>
                <button class="arena-btn arena-btn-success" onclick="this.closest('.celebration-overlay').remove()">
                    <i class="bi bi-check-lg"></i> 完成
                </button>
            </div>
        `;
        document.body.appendChild(overlay);
    }

    function setLoading(isLoading) {
        state.isLoading = isLoading;
        document.querySelectorAll('.arena-btn-primary, .arena-btn-send').forEach(btn => {
            btn.disabled = isLoading;
        });
    }

    // ============================================================
    // Timer
    // ============================================================
    function startTimer() {
        if (!state.startTime) {
            state.startTime = Date.now();
        }
        state.timerInterval = setInterval(() => {
            const elapsed = Math.floor((Date.now() - state.startTime) / 1000);
            const m = String(Math.floor(elapsed / 60)).padStart(2, '0');
            const s = String(elapsed % 60).padStart(2, '0');
            const el = document.getElementById('arena-timer');
            if (el) el.textContent = `${m}:${s}`;
        }, 1000);
    }

    // ============================================================
    // Utilities
    // ============================================================
    function fetchJSON(url, options = {}) {
        return fetch(url, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...(options.headers || {})
            }
        }).then(res => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
        });
    }

    function renderMarkdown(str) {
        if (!str) return '';
        if (typeof marked !== 'undefined') {
            marked.setOptions({ breaks: true, gfm: true });
            let html = marked.parse(str);
            if (typeof DOMPurify !== 'undefined') {
                html = DOMPurify.sanitize(html);
            }
            return html;
        }
        return escapeHtml(str).replace(/\n/g, '<br>');
    }

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    let activeRecognition = null;
    let activeMediaRecorder = null;
    let audioChunks = [];

    /**
     * 麦克风测试弹窗 —— 用户每次登录后首次点击语音按钮时触发
     * 测试通过后将标记写入 sessionStorage，本次会话内不再弹出
     */
    function showMicTestModal(targetId, btnEl) {
        // 创建遮罩
        const overlay = document.createElement('div');
        overlay.id = 'mic-test-overlay';
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:10000;display:flex;align-items:center;justify-content:center;';

        const card = document.createElement('div');
        card.style.cssText = 'background:#fff;border-radius:14px;padding:28px 32px;max-width:420px;width:90%;box-shadow:0 20px 60px rgba(0,0,0,0.2);text-align:center;font-family:inherit;';

        card.innerHTML = `
            <div style="font-size:36px;margin-bottom:8px;">🎙️</div>
            <h3 style="margin:0 0 6px;font-size:17px;font-weight:700;color:#1f2937;">麦克风测试</h3>
            <p style="font-size:13px;color:#6b7280;line-height:1.6;margin-bottom:16px;">
                首次使用语音输入功能，需要先测试一下您的麦克风是否正常工作。<br>
                点击下方按钮开始录音，说一句话后系统会自动回放给您听。
            </p>
            <div id="mic-test-status" style="font-size:13px;color:#2563eb;min-height:20px;margin-bottom:14px;"></div>
            <div id="mic-test-visualizer" style="display:none;height:32px;margin-bottom:14px;display:flex;align-items:center;justify-content:center;gap:3px;"></div>
            <audio id="mic-test-playback" style="display:none;width:100%;margin-bottom:14px;" controls></audio>
            <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap;">
                <button id="mic-test-start-btn" style="padding:8px 20px;border-radius:8px;border:none;background:#2563eb;color:#fff;font-size:13px;font-weight:600;cursor:pointer;transition:background 0.2s;">
                    <i class="bi bi-mic"></i> 开始测试录音
                </button>
                <button id="mic-test-skip-btn" style="padding:8px 20px;border-radius:8px;border:1px solid #e5e7eb;background:#fff;color:#6b7280;font-size:13px;cursor:pointer;transition:background 0.2s;">
                    跳过测试
                </button>
            </div>
            <div id="mic-test-result-btns" style="display:none;margin-top:12px;display:none;gap:10px;justify-content:center;">
                <button id="mic-test-ok-btn" style="padding:8px 20px;border-radius:8px;border:none;background:#10b981;color:#fff;font-size:13px;font-weight:600;cursor:pointer;">
                    ✅ 能听到，开始使用
                </button>
                <button id="mic-test-retry-btn" style="padding:8px 20px;border-radius:8px;border:1px solid #e5e7eb;background:#fff;color:#6b7280;font-size:13px;cursor:pointer;">
                    🔄 重新测试
                </button>
            </div>
        `;

        overlay.appendChild(card);
        document.body.appendChild(overlay);

        const statusEl = card.querySelector('#mic-test-status');
        const startBtn = card.querySelector('#mic-test-start-btn');
        const skipBtn = card.querySelector('#mic-test-skip-btn');
        const resultBtns = card.querySelector('#mic-test-result-btns');
        const okBtn = card.querySelector('#mic-test-ok-btn');
        const retryBtn = card.querySelector('#mic-test-retry-btn');
        const audioEl = card.querySelector('#mic-test-playback');

        let mediaRecorder = null;
        let chunks = [];

        function closeMicTest(passed) {
            if (mediaRecorder && mediaRecorder.state !== 'inactive') {
                try { mediaRecorder.stop(); } catch(e) {}
            }
            overlay.remove();
            if (passed) {
                sessionStorage.setItem('mic_tested', '1');
                // 直接启动真正的语音输入
                _doStartVoiceInput(targetId, btnEl);
            }
        }

        skipBtn.onclick = () => closeMicTest(true);

        startBtn.onclick = async () => {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                chunks = [];
                mediaRecorder = new MediaRecorder(stream);

                mediaRecorder.ondataavailable = (e) => {
                    if (e.data.size > 0) chunks.push(e.data);
                };

                mediaRecorder.onstop = () => {
                    stream.getTracks().forEach(t => t.stop());
                    if (chunks.length === 0) {
                        statusEl.textContent = '未录到有效音频，请重试。';
                        statusEl.style.color = '#ef4444';
                        startBtn.style.display = '';
                        return;
                    }
                    const blob = new Blob(chunks, { type: 'audio/webm' });
                    const url = URL.createObjectURL(blob);
                    audioEl.src = url;
                    audioEl.style.display = 'block';

                    statusEl.innerHTML = '录音完成！请点击播放按钮试听。<br>如果能听到你的声音，说明麦克风正常。';
                    statusEl.style.color = '#10b981';
                    resultBtns.style.display = 'flex';
                };

                mediaRecorder.start();
                startBtn.style.display = 'none';
                statusEl.textContent = '正在录音，请说话...（3秒后自动停止）';
                statusEl.style.color = '#ef4444';

                // 3秒后自动停止
                setTimeout(() => {
                    if (mediaRecorder && mediaRecorder.state === 'recording') {
                        mediaRecorder.stop();
                    }
                }, 3000);
            } catch (err) {
                console.error('麦克风测试失败:', err);
                if (err.name === 'NotAllowedError') {
                    statusEl.innerHTML = '麦克风权限被拒绝。请点击浏览器地址栏左侧的🔒图标，允许麦克风权限后重试。';
                } else if (err.name === 'NotFoundError') {
                    statusEl.innerHTML = '未检测到麦克风设备，请检查硬件连接。';
                } else {
                    statusEl.innerHTML = `麦克风访问失败: ${err.message}`;
                }
                statusEl.style.color = '#ef4444';
            }
        };

        okBtn.onclick = () => closeMicTest(true);
        retryBtn.onclick = () => {
            audioEl.style.display = 'none';
            audioEl.src = '';
            resultBtns.style.display = 'none';
            statusEl.textContent = '';
            startBtn.style.display = '';
        };

        // 点击遮罩关闭
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) closeMicTest(false);
        });
    }

    function startVoiceInput(targetId, btnEl) {
        // 每次登录后首次点击 → 弹出麦克风测试
        if (!sessionStorage.getItem('mic_tested')) {
            showMicTestModal(targetId, btnEl);
            return;
        }
        _doStartVoiceInput(targetId, btnEl);
    }

    function _doStartVoiceInput(targetId, btnEl) {
        const inputEl = document.getElementById(targetId);
        if (!inputEl) return;

        // Check if browser supports Web Speech API
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            showNotification('您的浏览器不支持语音输入功能，建议使用 Chrome 或 Edge 浏览器', 'warning');
            return;
        }

        // If already recording, stop it
        if (btnEl.classList.contains('recording')) {
            stopRecording(btnEl, inputEl);
            return;
        }

        // If another recognition is active, stop it first
        if (activeRecognition) {
            try { activeRecognition.stop(); } catch(e) {}
        }
        if (activeMediaRecorder && activeMediaRecorder.state !== 'inactive') {
            try { activeMediaRecorder.stop(); } catch(e) {}
        }

        const recognition = new SpeechRecognition();
        recognition.lang = 'zh-CN'; // Set language to Chinese
        recognition.continuous = true; // 开启连续识别，支持长时间说话
        recognition.interimResults = true; // 开启流式（临时）结果返回，实时显示打字效果
        recognition.maxAlternatives = 1;

        // 保存开始录音时的初始内容，并在末尾留出适当的空格
        let baseValue = inputEl.value;
        if (baseValue && !baseValue.endsWith(' ') && !baseValue.endsWith('\n') && !baseValue.endsWith('，') && !baseValue.endsWith('。')) {
            baseValue += ' ';
        }
        btnEl.dataset.baseValue = baseValue;
        btnEl.setAttribute('data-using-fallback', 'false');

        // 同时启动本地音频录制作为兼容备用方案
        let fallbackRecorder = null;
        let localChunks = [];
        navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
            if (!btnEl.classList.contains('recording')) {
                stream.getTracks().forEach(t => t.stop());
                return;
            }
            fallbackRecorder = new MediaRecorder(stream);
            fallbackRecorder.ondataavailable = (e) => {
                if (e.data.size > 0) localChunks.push(e.data);
            };
            fallbackRecorder.onstop = () => {
                stream.getTracks().forEach(t => t.stop());
            };
            fallbackRecorder.start();
            activeMediaRecorder = fallbackRecorder;
            audioChunks = localChunks;
        }).catch(err => {
            console.warn('无法启动备用本地录音设备:', err);
        });

        recognition.onstart = () => {
            btnEl.classList.add('recording');
            const micIcon = btnEl.querySelector('i');
            if (micIcon) {
                micIcon.className = 'bi bi-mic-mute-fill';
            }
            showNotification('正在录音中，请说话...', 'info');
        };

        recognition.onresult = (event) => {
            // 如果已经被标记为使用备用模式，忽略浏览器接口返回（可能为空或滞后错误）
            if (btnEl.getAttribute('data-using-fallback') === 'true') return;

            if (event && event.results) {
                let finalTranscript = '';
                let interimTranscript = '';
                
                for (let i = 0; i < event.results.length; ++i) {
                    let text = event.results[i][0].transcript;
                    if (event.results[i].isFinal) {
                        text = text.trim();
                        if (text) {
                            // 自动添加标点：如果该分句末尾没有标点符号，自动补上逗号
                            if (!/[，。？！,.?!]/.test(text.slice(-1))) {
                                text += '，';
                            }
                            finalTranscript += text;
                        }
                    } else {
                        interimTranscript += text;
                    }
                }
                
                inputEl.value = baseValue + finalTranscript + interimTranscript;
                // 触发输入事件，以便同步更新字符长度和相关绑定状态
                inputEl.dispatchEvent(new Event('input', { bubbles: true }));
            }
        };

        recognition.onerror = (event) => {
            console.error('语音识别错误: ', event.error);
            if (event.error === 'network') {
                // 如果是网络连接失败（常见于国内 Chrome 访问 Google 语音服务器被墙），自动切换为本地录制+后端转写模式
                console.log('检测到浏览器语音接口网络连接失败，已自动无缝切换为本地兼容录音转写模式。');
                btnEl.setAttribute('data-using-fallback', 'true');
                showNotification('由于网络限制，已切换为本地备用录音模式，请继续说话并点击红色按钮结束...', 'info');
                return; // 拦截错误，不执行默认停止逻辑
            }

            let msg = '语音识别出错，请重试';
            if (event.error === 'not-allowed') {
                msg = '麦克风访问权限被拒绝，或者您的连接不是安全的 HTTPS 连接（非 localhost 的 HTTP 访问将被浏览器禁用麦克风）。请检查浏览器地址栏左侧的权限设置。';
            } else if (event.error === 'no-speech') {
                msg = '未检测到说话声，请尝试靠近麦克风或调整输入音量后重试。';
            } else if (event.error === 'audio-capture') {
                msg = '未找到录音设备，或者麦克风正被其他程序占用，请检查硬件设置。';
            } else {
                msg = `语音识别出错 (错误原因: ${event.error})，请重试。`;
            }
            showNotification(msg, 'warning');
            stopRecording(btnEl, inputEl);
        };

        recognition.onend = () => {
            // 如果已启用备用录音，并且按钮仍处于 recording 状态，说明用户仍在通过备用 MediaRecorder 录音，忽略 onend
            if (btnEl.getAttribute('data-using-fallback') === 'true' && btnEl.classList.contains('recording')) {
                return;
            }
            stopRecording(btnEl, inputEl);
        };

        activeRecognition = recognition;
        
        try {
            recognition.start();
        } catch (err) {
            console.error('启动语音识别失败:', err);
            showNotification(`无法启动语音识别: ${err.message}`, 'warning');
            stopRecording(btnEl, inputEl);
        }
    }

    function stopRecording(btnEl, inputEl) {
        btnEl.classList.remove('recording');
        const micIcon = btnEl.querySelector('i');
        const originalIconClass = btnEl.classList.contains('arena-btn-voice-small') ? 'bi bi-mic-fill' : 'bi bi-mic';
        if (micIcon) {
            // Restore default icon
            micIcon.className = originalIconClass;
        }

        const isFallback = btnEl.getAttribute('data-using-fallback') === 'true';

        // 停止浏览器 SpeechRecognition 实例
        if (activeRecognition) {
            try { activeRecognition.stop(); } catch(e) {}
        }

        // 停止本地备用 MediaRecorder
        if (activeMediaRecorder && activeMediaRecorder.state !== 'inactive') {
            const currentRecorder = activeMediaRecorder;
            const currentChunks = audioChunks;

            currentRecorder.onstop = () => {
                if (currentRecorder.stream) {
                    currentRecorder.stream.getTracks().forEach(t => t.stop());
                }

                if (isFallback) {
                    if (currentChunks.length === 0) {
                        showNotification('未录制到有效音频，请重试', 'warning');
                        return;
                    }

                    // 打包音频 Blob 并上传到后端 transcribe 接口
                    const audioBlob = new Blob(currentChunks, { type: 'audio/webm' });
                    const formData = new FormData();
                    formData.append('file', audioBlob, 'voice.webm');

                    if (micIcon) {
                        micIcon.className = 'bi bi-arrow-repeat rotating-icon';
                    }
                    btnEl.disabled = true;

                    showNotification('正在通过大模型（Whisper/GLM-ASR）智能转换语音...', 'info');

                    fetch('/thinking/api/stt/transcribe', {
                        method: 'POST',
                        body: formData
                    })
                    .then(res => {
                        if (!res.ok) throw new Error(`HTTP ${res.status}`);
                        return res.json();
                    })
                    .then(data => {
                        if (data.success && data.text) {
                            const baseValue = btnEl.dataset.baseValue || '';
                            inputEl.value = baseValue + data.text;
                            inputEl.dispatchEvent(new Event('input', { bubbles: true }));
                        } else {
                            showNotification('未识别出有效内容，请重试或大声一些', 'warning');
                        }
                    })
                    .catch(err => {
                        console.error('音频转文字失败:', err);
                        showNotification('音频云端转换失败，请手动输入或使用 Edge/Safari 浏览器', 'warning');
                    })
                    .finally(() => {
                        btnEl.disabled = false;
                        if (micIcon) {
                            micIcon.className = originalIconClass;
                        }
                    });
                }
            };

            try { currentRecorder.stop(); } catch(e) {}
        }
        
        // 如果使用的是标准浏览器语音 API 流程，执行原始客户端润色整理
        if (!isFallback && inputEl) {
            let val = inputEl.value;
            if (val) {
                val = val.trim();
                if (val.endsWith('，')) {
                    val = val.slice(0, -1) + '。';
                } else if (!/[。？！?!]$/.test(val)) {
                    val = val + '。';
                }
                inputEl.value = val;
                inputEl.dispatchEvent(new Event('input', { bubbles: true }));

                // 异步请求大模型进行智能纠错与润色（修正同音字，补充合适的分句中文标点）
                const baseValue = btnEl.dataset.baseValue || '';
                let spokenText = val.slice(baseValue.length).trim();
                
                if (spokenText) {
                    if (micIcon) {
                        micIcon.className = 'bi bi-arrow-repeat rotating-icon';
                    }
                    btnEl.disabled = true;

                    fetchJSON('/thinking/api/stt/optimize', {
                        method: 'POST',
                        body: JSON.stringify({ text: spokenText })
                    }).then(data => {
                        if (data.success && data.optimized_text) {
                            inputEl.value = baseValue + data.optimized_text;
                            inputEl.dispatchEvent(new Event('input', { bubbles: true }));
                        }
                    }).catch(err => {
                        console.error('语音优化失败:', err);
                    }).finally(() => {
                        btnEl.disabled = false;
                        if (micIcon) {
                            micIcon.className = originalIconClass;
                        }
                    });
                }
            }
        }

        activeRecognition = null;
        activeMediaRecorder = null;
        audioChunks = [];
    }

    // ============================================================
    // Public API (for onclick handlers in HTML)
    // ============================================================
    window.ThinkingArena = {
        init,
        submitDescription,
        requestStage1Hint,
        verifyQuiz,
        onQuizAnswer,
        onQuizFillInput,
        requestStage2Hint,
        sendCompanionChat,
        sendTeacherChat,
        sendStudentChat,
        submitCodeFix,
        startVoiceInput,
        // Debug API
        debugJumpStage,
        debugAutoS1,
        debugAutoS2,
    };

    // Auto-init on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
