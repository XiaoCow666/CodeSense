/**
 * 三阶段引导式学习系统 — 前端交互逻辑
 * Guided Learning Arena (thinking.js)
 */

(function () {
    'use strict';

    // ============================================================
    // State Management
    // ============================================================
    const MAX_PUBLIC_FORUM_EVENTS = 80;
    const SYNTHETIC_FORUM_EVENT_PREFIXES = ['local-', 'forum-welcome-'];

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
        forumHistory: [],
        forumTargetRole: 'auto',
        forumReplyContext: null,
        forumReplyEventId: null,
        forumCoverageSummary: null,
        forumUserGoal: null,
        pendingForumRequestId: null,
        feynmanPhase: 'chat', // 'chat' | 'code_generation' | 'code_review' | 'completed'
        buggyCode: null,
        buggyCodeInfo: null,
        devDebugTraceLoaded: false,
        // Flags
        isLoading: false,
    };

    function defaultCoverageSummary() {
        return {
            coverage_score: 0,
            ready_for_code: false,
            unresolved_concepts: [],
            concept_coverage: [],
        };
    }

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
        initCompanionCollapse();
        initStage2PanelToggles();
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
                    state.forumHistory = sanitizePublicForumHistory(data.forum_history || [], { persisted: true });
                    state.teacherHistory = data.teacher_history || [];
                    state.studentHistory = data.student_history || [];
                    state.buggyCodeInfo = data.buggy_code_info || null;
                    applyRestoredForumState(data.forum_state || null, data.user_goal || null);

                    // 同步并重新启动计时器
                    if (state.timerInterval) {
                        clearInterval(state.timerInterval);
                    }
                    state.startTime = Date.now() - state.elapsedSeconds * 1000;
                    startTimer();
                } else {
                    state.isResumed = false;
                    state.forumHistory = [];
                    state.teacherHistory = [];
                    state.studentHistory = [];
                    state.buggyCode = null;
                    state.buggyCodeInfo = null;
                    applyRestoredForumState(data.forum_state || null, data.user_goal || null);
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

        // Toggle companion, dynamic goal, and stage guide panels appropriately
        const companionPanel = document.getElementById('ai-companion-panel');
        const goalPanel = document.getElementById('stage3-goal-panel');
        const guidePanel = document.getElementById('student-agent-panel');
        if (stage === 3) {
            if (companionPanel) companionPanel.classList.remove('active');
            if (goalPanel) goalPanel.classList.add('active');
            if (guidePanel) guidePanel.classList.add('active');
        } else {
            if (companionPanel) companionPanel.classList.add('active');
            if (goalPanel) goalPanel.classList.remove('active');
            if (guidePanel) guidePanel.classList.remove('active');
        }

        // Update body layout for stages
        const body = document.querySelector('.arena-body');
        if (body) {
            body.classList.toggle('stage-2-layout', stage === 2);
            body.classList.toggle('stage-1-layout', stage === 1);
            body.classList.toggle('feynman-layout', stage === 3);
            const companionToggle = document.getElementById('toggle-companion-panel');
            if (companionToggle) {
                companionToggle.hidden = stage === 3;
            }
            const previewToggle = document.getElementById('toggle-stage2-preview');
            if (previewToggle) {
                previewToggle.hidden = stage !== 2;
            }
            if (stage === 3) {
                body.classList.remove('companion-collapsed');
                body.classList.remove('preview-collapsed');
            }
            if (stage !== 2) {
                body.classList.remove('preview-collapsed');
            }
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
    function initCompanionCollapse() {
        const toggle = document.getElementById('toggle-companion-panel');
        const body = document.querySelector('.arena-body');
        if (!toggle || !body || toggle.dataset.bound === '1') return;

        toggle.dataset.bound = '1';
        toggle.addEventListener('click', () => {
            const collapsed = body.classList.toggle('companion-collapsed');
            toggle.setAttribute('aria-expanded', String(!collapsed));
            toggle.setAttribute('title', collapsed ? '展开 AI 伴学助手' : '收起 AI 伴学助手');
            toggle.querySelector('span').textContent = collapsed ? '展开' : '收起';
        });
    }

    function initStage2PanelToggles() {
        const toggle = document.getElementById('toggle-stage2-preview');
        const body = document.querySelector('.arena-body');
        if (!toggle || !body || toggle.dataset.bound === '1') return;

        toggle.dataset.bound = '1';
        toggle.addEventListener('click', () => {
            const collapsed = body.classList.toggle('preview-collapsed');
            toggle.setAttribute('aria-expanded', String(!collapsed));
            toggle.setAttribute('title', collapsed ? '展开代码预览' : '收起代码预览');
            toggle.querySelector('span').textContent = collapsed ? '展开' : '收起';
        });
    }

    function updateStage1AnswerProgress() {
        const answers = Array.from(document.querySelectorAll('.qa-answer-textarea'));
        const progress = document.getElementById('stage1-answer-progress');
        if (!progress) return;
        const filled = answers.filter(item => item.value.trim()).length;
        progress.textContent = `${filled}/${answers.length} 已填写`;
    }

    function updateStage2AnswerProgress() {
        const steps = state.preset && Array.isArray(state.preset.quiz_steps)
            ? state.preset.quiz_steps
            : [];
        const progress = document.getElementById('stage2-answer-progress');
        if (!progress) return;
        const answers = state.quizAnswers || {};
        const answered = steps.filter(step => String(answers[step.step_id] || '').trim()).length;
        progress.textContent = `${answered}/${steps.length} 已回答`;
    }

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
                algoSummaryContent.style.display = 'none'; // 默认收起，把空间留给作答区
            }
            if (algoSummaryIcon) {
                algoSummaryIcon.className = 'bi bi-chevron-down';
            }
            if (algoSummaryHeader) {
                algoSummaryHeader.setAttribute('aria-expanded', 'false');
            }
            if (stage1Instruction) {
                stage1Instruction.style.display = 'flex';
            }
        } else {
            if (algoSummaryWrapper) algoSummaryWrapper.style.display = 'none';
            if (stage1Instruction) stage1Instruction.style.display = 'none';
        }

        if (algoSummaryHeader) {
            const toggleAlgorithmSummary = () => {
                if (algoSummaryContent) {
                    const expanded = algoSummaryContent.style.display === 'none';
                    algoSummaryContent.style.display = expanded ? 'block' : 'none';
                    algoSummaryHeader.setAttribute('aria-expanded', String(expanded));
                    if (algoSummaryIcon) algoSummaryIcon.className = expanded ? 'bi bi-chevron-up' : 'bi bi-chevron-down';
                }
            };
            algoSummaryHeader.onclick = toggleAlgorithmSummary;
            algoSummaryHeader.onkeydown = event => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    toggleAlgorithmSummary();
                }
            };
        }

        // Setup guided questions display & dynamic input boxes
        const questionsWrapper = document.getElementById('guided-questions-wrapper');
        const questionsList = document.getElementById('guided-questions-list');
        const questionsHeader = document.getElementById('guided-questions-header');
        const questionsContent = document.getElementById('guided-questions-content');
        const questionsIcon = document.getElementById('guided-questions-icon');
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

        if (questionsHeader && questionsContent) {
            const toggleGuidedQuestions = () => {
                const expanded = questionsContent.hidden;
                questionsContent.hidden = !expanded;
                questionsHeader.setAttribute('aria-expanded', String(expanded));
                if (questionsIcon) questionsIcon.className = expanded ? 'bi bi-chevron-up' : 'bi bi-chevron-down';
            };
            questionsContent.hidden = true;
            questionsHeader.setAttribute('aria-expanded', 'false');
            questionsHeader.onclick = toggleGuidedQuestions;
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
                qTextarea.addEventListener('input', updateStage1AnswerProgress);

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
        updateStage1AnswerProgress();

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
            submitBtn.innerHTML = '<i class="bi bi-hourglass-split rotating-icon"></i> 正在快速检查关键点...';
        }
        textareas.forEach(ta => ta.disabled = true);

        setLoading(true);
        fetchAIStream('/thinking/api/stage1/submit', {
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

        let streamedHint = '';
        let hintPreview = null;
        fetchAIStream('/thinking/api/stage1/hint', {
            method: 'POST',
            body: JSON.stringify({
                session_id: state.sessionId,
                description: aggregatedDescription
            })
        }, {
            onDelta: event => {
            streamedHint += event.content || '';
                if (!hintPreview) hintPreview = createCompanionStreamingMessage();
                hintPreview(streamedHint);
            }
        }).then(data => {
            const hint = data.hint || data.content || streamedHint;
            if (data.success !== false && hint) {
                if (!hintPreview) hintPreview = createCompanionStreamingMessage();
                hintPreview(hint);
                if (!state.companionMessages) state.companionMessages = [];
                state.companionMessages.push({ role: 'user', content: '我在撰写思路描述时遇到困难，请给我一些引导提示。' });
                state.companionMessages.push({ role: 'assistant', content: hint });
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
            } else if (step.type === 'fill_blank' || step.type === 'fill') {
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
        updateStage2AnswerProgress();
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
        updateStage2AnswerProgress();
    }

    function onQuizFillInput(stepId, value) {
        state.quizAnswers[stepId] = value.trim();
        updateQuizPreview();
        updateStage2AnswerProgress();
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
        fetchAIStream('/thinking/api/stage2/verify', {
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

        let streamedHint = '';
        let hintPreview = null;
        fetchAIStream('/thinking/api/stage2/hint', {
            method: 'POST',
            body: JSON.stringify({
                session_id: state.sessionId,
                current_blocks: Object.keys(answers),
                quiz_state: currentState
            })
        }, {
            onDelta: event => {
            streamedHint += event.content || '';
                if (!hintPreview) hintPreview = createCompanionStreamingMessage();
                hintPreview(streamedHint);
            }
        }).then(data => {
            const hint = data.hint || data.content || streamedHint;
            if (data.success !== false && hint) {
                if (!hintPreview) hintPreview = createCompanionStreamingMessage();
                hintPreview(hint);
                if (!state.companionMessages) state.companionMessages = [];
                state.companionMessages.push({ role: 'user', content: '\u6211\u5728\u6784\u5efa\u7a0b\u5e8f\u65f6\u9047\u5230\u56f0\u96be\uff0c\u8bf7\u7ed9\u6211\u4e00\u4e9b\u5f15\u5bfc\u63d0\u793a\u3002' });
                state.companionMessages.push({ role: 'assistant', content: hint });
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
                <div class="chat-bubble ai cs-markdown"><span class="typing-dots">思考引导中...</span></div>
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

        let streamedResponse = '';
        let responsePreview = null;
        fetchAIStream('/thinking/api/companion/chat', {
            method: 'POST',
            body: JSON.stringify(requestBody)
        }, {
            onDelta: event => {
            streamedResponse += event.content || '';
                if (!responsePreview) responsePreview = createCompanionStreamingMessage();
                responsePreview(streamedResponse);
            }
        }).then(data => {
            const typingEl = document.getElementById(typingId);
            if (typingEl) typingEl.remove();

            const responseText = data.response || data.content || streamedResponse;
            if (data.success !== false && responseText) {
                if (!responsePreview) responsePreview = createCompanionStreamingMessage();
                responsePreview(responseText);
                messages.push({ role: 'assistant', content: responseText });
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
            <div class="chat-bubble cs-markdown ${isUser ? 'user-msg' : 'ai'}">${renderMarkdown(text)}</div>
        `;
        container.appendChild(msgDiv);
        container.scrollTop = container.scrollHeight;
    }

    function createCompanionStreamingMessage() {
        const container = document.getElementById('companion-messages');
        if (!container) return () => {};
        const msgDiv = document.createElement('div');
        msgDiv.className = 'chat-message';
        msgDiv.innerHTML = `
            <div class="chat-avatar teacher">🤖</div>
            <div class="chat-bubble ai cs-markdown"></div>
        `;
        container.appendChild(msgDiv);
        const bubble = msgDiv.querySelector('.chat-bubble');
        return text => {
            if (bubble) bubble.innerHTML = renderMarkdown(text || '');
            container.scrollTop = container.scrollHeight;
        };
    }

    function defaultUserGoal(summary = defaultCoverageSummary()) {
        const score = Number.isFinite(summary.coverage_score)
            ? Math.max(0, Math.min(1, summary.coverage_score))
            : 0;
        const conceptCount = Array.isArray(summary.concept_coverage)
            ? summary.concept_coverage.length
            : 0;
        return {
            id: 'stage3-teach-and-repair',
            title: '掌握关键思路并完成一次代码修复',
            description: '先用自己的话解释关键点，再由小明从不同角度检查，达标后自动生成一份错误代码供你修复。',
            status: 'in_progress',
            progress_percent: Math.min(79, Math.round(score * 80)),
            coverage_score: score,
            coverage_threshold: 0.8,
            covered_concepts: 0,
            total_concepts: conceptCount,
            current_milestone: 'understanding',
            next_action: '先用自己的话说明一个关键知识点，系统会按检查点推进。',
            steps: [
                { id: 'understanding', label: '说明关键知识点', status: 'active' },
                { id: 'peer_check', label: '小明完成多角度检查', status: 'todo' },
                { id: 'buggy_code', label: '生成待修复代码', status: 'todo' },
                { id: 'repair', label: '修复并通过验证', status: 'todo' },
            ],
        };
    }

    function regeneratePreset() {
        if (!confirm('确定要应用最新大括号归拢规范，重新拆解并生成当前作业的代码积木吗？')) return;

        const container = document.getElementById('arena-container');
        const assignmentId = container ? container.dataset.assignmentId : null;
        if (!assignmentId) return;

        setLoading(true);
        showNotification('正在应用全新整合规则重构积木池，请稍候...', 'info');

        fetchAIStream('/thinking/api/generate_preset', {
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
    // Stage 3: Feynman Teaching (Target-aware Forum)
    // ============================================================
    function initStage3() {
        state.feynmanPhase = 'chat';
        state.pendingForumRequestId = null;
        bindForumControls();
        bindForumStickyHead();
        renderForumUserGoal();
        renderForumFeed();
        restoreForumReplyContext();
        updateForumTargetControls();
        updateForumComposerState();

        // 恢复代码修复面板
        if (state.isResumed && state.buggyCodeInfo) {
            state.feynmanPhase = 'code_review';
            state.buggyCode = state.buggyCodeInfo.buggy_code;
            showCodeReviewPanel(state.buggyCodeInfo.buggy_code);
        } else if (
            state.isResumed &&
            state.forumUserGoal &&
            state.forumUserGoal.status === 'ready_for_code'
        ) {
            // A previous automatic generation may have failed after the
            // learning gate opened.  Resume the normal next action instead
            // of leaving the learner in a chat composer with no code panel.
            triggerCodeWritingPhase();
        }
    }

    function newAgentRequestId(prefix) {
        if (window.crypto && window.crypto.randomUUID) {
            return `${prefix}-${window.crypto.randomUUID()}`;
        }
        return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }

    function sendForumMessage(options = {}) {
        const input = document.getElementById('forum-input');
        const message = options.message ? String(options.message).trim() : (input ? input.value.trim() : '');
        const targetRole = normalizeForumTargetRole(options.targetRole || state.forumTargetRole);
        const replyToEventId = getPersistedForumReplyEventId();
        if (!message || state.isLoading || state.pendingForumRequestId) return;

        const requestId = newAgentRequestId('forum');
        const requestPayload = {
            session_id: state.sessionId,
            message: message,
            target_role: targetRole,
            reply_to_event_id: replyToEventId,
            request_id: requestId
        };
        const userEvent = sanitizeForumEvent({
            event_id: `local-user-${requestId}`,
            event_type: 'agent_user_message',
            role: 'student',
            source_role: 'user',
            target_role: targetRole,
            message_kind: 'user_message',
            visibility: 'public',
            content: message,
            request_id: requestId,
            reply_to_event_id: replyToEventId,
            parent_request_id: state.forumReplyContext
                ? (state.forumReplyContext.parent_request_id || state.forumReplyContext.request_id || null)
                : null,
        });
        if (!userEvent) return;

        state.pendingForumRequestId = requestId;
        appendForumEvent(userEvent);
        if (input) {
            input.value = '';
        }
        clearForumReplyContext();
        updateForumComposerState();
        showTypingIndicator('forum');

        fetchAIStream('/thinking/api/stage3/forum/message', {
            method: 'POST',
            body: JSON.stringify(requestPayload)
        }).then(data => {
            hideTypingIndicator('forum');
            applyForumTurnPayload(data, {
                requestId,
                targetRole,
                userEvent,
            });
            return reconcileForumHistory(requestId).catch(() => {
                // Keep the optimistic public messages, but leave their reply
                // actions disabled until a later refresh proves persistence.
                showNotification('消息已发送，但论坛记录尚未同步；请稍后刷新。', 'warning');
            });
        }).catch(err => {
            hideTypingIndicator('forum');
            removeForumEventsByRequestId(requestId);
            showError(err.message);
        }).finally(() => {
            state.pendingForumRequestId = null;
            updateForumComposerState();
        });
    }

    function sendTeacherChat() {
        setForumTarget('teacher_agent');
        sendForumMessage({ targetRole: 'teacher_agent' });
    }

    function sendStudentChat() {
        setForumTarget('student_agent');
        sendForumMessage({ targetRole: 'student_agent' });
    }

    function triggerCodeWritingPhase() {
        if (state.feynmanPhase === 'code_generation') return;
        state.feynmanPhase = 'code_generation';

        showTypingIndicator('forum');

        fetchAIStream('/thinking/api/stage3/write_code', {
            method: 'POST',
            body: JSON.stringify({
                session_id: state.sessionId,
                request_id: newAgentRequestId('write')
            })
        }).then(data => {
            hideTypingIndicator('forum');
            applyForumUserGoal(data && data.user_goal);
            if (data.success) {
                state.feynmanPhase = 'code_review';
                state.buggyCode = data.buggy_code;
                appendForumEvent({
                    event_id: `local-write-${data.request_id || newAgentRequestId('write-result')}`,
                    event_type: 'agent_message',
                    role: 'student_agent',
                    source_role: 'student_agent',
                    target_role: 'user',
                    message_kind: 'agent_message',
                    visibility: 'public',
                    content: safeForumText(data, '我写了一版代码，请帮我检查。'),
                    request_id: data.request_id || null,
                });

                // Show code review panel
                showCodeReviewPanel(data.buggy_code);
            } else {
                // A transient generator/provider error must not strand the
                // page in code_review. The server gate remains authoritative,
                // so the next turn can safely retry this idempotent step.
                state.feynmanPhase = 'chat';
                updateForumComposerState();
                showError((data && data.error) || '代码练习生成失败，请稍后重试。');
            }
        }).catch(err => {
            hideTypingIndicator('forum');
            state.feynmanPhase = 'chat';
            updateForumComposerState();
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
        fetchAIStream('/thinking/api/stage3/fix_code', {
            method: 'POST',
            body: JSON.stringify({
                session_id: state.sessionId,
                fixed_code: fixedCode,
                request_id: newAgentRequestId('fix')
            })
        }).then(data => {
            applyForumUserGoal(data && data.user_goal);
            if (data.success) {
                if (data.correct) {
                    state.feynmanPhase = 'completed';
                    appendForumEvent({
                        event_id: `local-fix-ok-${newAgentRequestId('fix-result')}`,
                        event_type: 'agent_message',
                        role: 'student_agent',
                        source_role: 'student_agent',
                        target_role: 'user',
                        message_kind: 'agent_message',
                        visibility: 'public',
                        content: '哦！原来是这样！谢谢你帮我找出来了，我以后会注意的！🎉',
                    });
                    setTimeout(() => showCelebration(), 1000);
                    completeSession();
                } else {
                    showNotification(data.feedback || '修复不太对，再看看？', 'warning');
                    appendForumEvent({
                        event_id: `local-fix-retry-${newAgentRequestId('fix-result')}`,
                        event_type: 'agent_message',
                        role: 'student_agent',
                        source_role: 'student_agent',
                        target_role: 'user',
                        message_kind: 'agent_message',
                        visibility: 'public',
                        content: '嗯...我觉得好像还是不太对。你再帮我看看？' + (data.feedback ? '\n（' + data.feedback + '）' : ''),
                    });
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
    function getMessageContainer(panel) {
        if (panel === 'forum') {
            return document.getElementById('forum-feed');
        }
        return document.getElementById(`${panel}-messages`);
    }

    function addChatMessage(panel, role, content) {
        const container = getMessageContainer(panel);
        if (!container) return;

        const isUser = role === 'user';
        const avatarClass = isUser ? 'student' : (panel === 'teacher' ? 'teacher' : 'bad-student');
        const avatarIcon = isUser ? '👤' : (panel === 'teacher' ? '👨‍🏫' : '🧑‍🎓');

        const msgDiv = document.createElement('div');
        msgDiv.className = `chat-message ${isUser ? 'user' : ''}`;
        msgDiv.innerHTML = `
            <div class="chat-avatar ${avatarClass}">${avatarIcon}</div>
            <div class="chat-bubble cs-markdown ${isUser ? 'user-msg' : 'ai'}">${renderMarkdown(content)}</div>
        `;
        container.appendChild(msgDiv);
        container.scrollTop = container.scrollHeight;
    }

    function bindForumControls() {
        const teacherBtn = document.getElementById('forum-target-teacher');
        const studentBtn = document.getElementById('forum-target-student');
        const clearReplyBtn = document.getElementById('forum-reply-clear');
        const autoBtn = document.getElementById('forum-target-auto');
        const input = document.getElementById('forum-input');

        if (teacherBtn && !teacherBtn.dataset.bound) {
            teacherBtn.dataset.bound = 'true';
            teacherBtn.addEventListener('click', () => setForumTarget('teacher_agent'));
        }
        if (studentBtn && !studentBtn.dataset.bound) {
            studentBtn.dataset.bound = 'true';
            studentBtn.addEventListener('click', () => setForumTarget('student_agent'));
        }
        if (autoBtn && !autoBtn.dataset.bound) {
            autoBtn.dataset.bound = 'true';
            autoBtn.addEventListener('click', () => setForumTarget('auto'));
        }
        if (clearReplyBtn && !clearReplyBtn.dataset.bound) {
            clearReplyBtn.dataset.bound = 'true';
            clearReplyBtn.addEventListener('click', clearForumReplyContext);
        }
        if (input && !input.dataset.bound) {
            input.dataset.bound = 'true';
            input.addEventListener('input', updateForumComposerState);
        }
    }

    function reconcileForumHistory(localRequestId) {
        if (!state.assignmentId || state.sessionId === null || state.sessionId === undefined) {
            return Promise.reject(new Error('论坛记录同步失败'));
        }

        const localHistory = state.forumHistory.slice();
        return fetchJSON('/thinking/api/start_session', {
            method: 'POST',
            body: JSON.stringify({ assignment_id: state.assignmentId })
        }).then(data => {
            if (
                !data ||
                data.success !== true ||
                String(data.session_id) !== String(state.sessionId) ||
                !Array.isArray(data.forum_history)
            ) {
                throw new Error('论坛记录同步失败');
            }

            const persistedHistory = sanitizePublicForumHistory(
                data.forum_history,
                { persisted: true }
            );
            state.forumHistory = mergeReconciledForumHistory(
                persistedHistory,
                localHistory,
                localRequestId
            );
            applyRestoredForumState(data.forum_state || null, data.user_goal || null);
            state.buggyCodeInfo = data.buggy_code_info || state.buggyCodeInfo;
            renderForumFeed();
            restoreForumReplyContext();
            return persistedHistory;
        });
    }

    function mergeReconciledForumHistory(persistedHistory, localHistory, localRequestId) {
        const persistedRequestIds = new Set(
            persistedHistory
                .map(event => event.request_id)
                .filter(Boolean)
        );
        const currentRequestId = optionalString(localRequestId);
        const currentRequestWasPersisted = Boolean(
            currentRequestId && persistedRequestIds.has(currentRequestId)
        );
        const localOnlyEvents = (Array.isArray(localHistory) ? localHistory : [])
            .filter(event => !isPersistedForumEvent(event))
            .filter(event => {
                const requestId = event.request_id;
                const parentRequestId = event.parent_request_id;
                const belongsToCurrentRequest = Boolean(
                    currentRequestId &&
                    (requestId === currentRequestId || parentRequestId === currentRequestId)
                );
                if (belongsToCurrentRequest) {
                    return !currentRequestWasPersisted;
                }
                return !(
                    (requestId && persistedRequestIds.has(requestId)) ||
                    (parentRequestId && persistedRequestIds.has(parentRequestId))
                );
            });
        return [...persistedHistory, ...localOnlyEvents].slice(-MAX_PUBLIC_FORUM_EVENTS);
    }

    function renderForumFeed() {
        const container = getMessageContainer('forum');
        if (!container) return;
        container.innerHTML = '';

        if (state.forumHistory.length === 0) {
            appendForumEvent({
                event_id: 'forum-welcome-teacher',
                event_type: 'agent_message',
                role: 'teacher_agent',
                source_role: 'teacher_agent',
                target_role: 'user',
                message_kind: 'agent_message',
                visibility: 'public',
                content: '老师会在这里公开解释你的问题，并在需要时引导出新的追问。',
            }, { persist: false });
            appendForumEvent({
                event_id: 'forum-welcome-student',
                event_type: 'agent_message',
                role: 'student_agent',
                source_role: 'student_agent',
                target_role: 'user',
                message_kind: 'agent_message',
                visibility: 'public',
                content: '小明会在这里公开提问、追问，并在理解达标后给出需要你修复的错误代码。',
            }, { persist: false });
            return;
        }

        const fragment = document.createDocumentFragment();
        state.forumHistory.forEach(event => {
            const node = createForumEventNode(event);
            if (node) {
                fragment.appendChild(node);
            }
        });
        container.appendChild(fragment);
        container.scrollTop = container.scrollHeight;
    }

    function appendForumEvent(event, options = {}) {
        const { persist = true } = options;
        const sanitized = sanitizeForumEvent(event);
        if (!sanitized) return null;
        if (persist) {
            state.forumHistory = [...state.forumHistory, sanitized].slice(-MAX_PUBLIC_FORUM_EVENTS);
        }
        const container = getMessageContainer('forum');
        if (!container) return sanitized;
        const node = createForumEventNode(sanitized);
        if (node) {
            container.appendChild(node);
            container.scrollTop = container.scrollHeight;
        }
        return sanitized;
    }

    function createForumEventNode(event) {
        const sanitized = sanitizeForumEvent(event);
        if (!sanitized) return null;

        const wrapper = document.createElement('article');
        wrapper.className = 'forum-event';
        if (sanitized.source_role === 'user') {
            wrapper.classList.add('is-user');
        }
        if (sanitized.event_id) {
            wrapper.dataset.eventId = sanitized.event_id;
        }

        const avatar = document.createElement('div');
        const avatarInfo = forumAvatar(sanitized.source_role);
        avatar.className = `forum-avatar role-${sanitized.source_role}`;
        avatar.setAttribute('aria-hidden', 'true');
        avatar.textContent = avatarInfo.icon;

        const card = document.createElement('div');
        card.className = 'forum-card';

        const meta = document.createElement('div');
        meta.className = 'forum-meta';

        const metaMain = document.createElement('div');
        metaMain.className = 'forum-meta-main';

        const role = document.createElement('span');
        role.className = 'forum-role';
        role.textContent = avatarInfo.label;

        const kind = document.createElement('span');
        kind.className = `forum-kind kind-${sanitized.message_kind}`;
        kind.textContent = forumKindLabel(sanitized.message_kind);

        const relation = document.createElement('div');
        relation.className = 'forum-relation';
        relation.textContent = forumRelationLabel(sanitized);

        metaMain.appendChild(role);
        metaMain.appendChild(kind);
        metaMain.appendChild(relation);
        meta.appendChild(metaMain);

        const content = document.createElement('div');
        content.className = 'forum-content';
        content.textContent = sanitized.content;

        card.appendChild(meta);
        card.appendChild(content);
        if (isPersistedForumEvent(sanitized)) {
            const actions = document.createElement('div');
            actions.className = 'forum-actions';

            const replyAction = document.createElement('button');
            replyAction.type = 'button';
            replyAction.className = 'forum-reply-action';
            replyAction.textContent = '回复';
            replyAction.addEventListener('click', () => {
                setForumTarget(replyTargetRoleForEvent(sanitized));
                setForumReplyContext(sanitized);
                const input = document.getElementById('forum-input');
                if (input) {
                    input.focus();
                }
            });

            actions.appendChild(replyAction);
            card.appendChild(actions);
        }
        wrapper.appendChild(avatar);
        wrapper.appendChild(card);
        return wrapper;
    }

    function applyForumTurnPayload(rawPayload, context) {
        const payload = normalizeForumTurnPayload(rawPayload);
        if (!payload || !payload.primary) return;
        if (payload.forum_state && typeof payload.forum_state === 'object') {
            state.forumCoverageSummary = sanitizeCoverageSummary(payload.forum_state.coverage_summary);
            if (
                payload.forum_state.target_role === 'student_agent'
                && state.feynmanPhase === 'chat'
            ) {
                // The server owns the next-probe handoff. Keep the composer
                // aligned when the Teacher authorized Xiaoming privately.
                setForumTarget('student_agent');
            }
        }
        applyForumUserGoal(payload.user_goal);

        const userEvent = context.userEvent || null;
        const replyToEventId = userEvent
            ? userEvent.event_id
            : (context.replyToEventId || getPersistedForumReplyEventId());
        const parentRequestId = userEvent
            ? (userEvent.parent_request_id || context.requestId)
            : null;
        const primaryEvent = appendForumEvent({
            event_id: `local-primary-${context.requestId}`,
            event_type: 'agent_message',
            role: payload.primary.agent || context.targetRole,
            source_role: payload.primary.agent || context.targetRole,
            target_role: 'user',
            message_kind: forumMessageKindFromPayload(payload.primary),
            visibility: 'public',
            content: safeForumText(payload.primary, forumFallbackText(payload.primary)),
            request_id: context.requestId,
            reply_to_event_id: replyToEventId,
            parent_request_id: parentRequestId,
        });

        handleForumAdvancement(payload.primary);
        if (primaryEvent && primaryEvent.message_kind === 'student_probe') {
            setForumTarget('student_agent');
        }

    }

    function handleForumAdvancement(payload) {
        if (!payload) return;
        const goalReadyForCode = Boolean(
            payload.user_goal &&
            typeof payload.user_goal === 'object' &&
            payload.user_goal.status === 'ready_for_code'
        );
        const shouldShowCodeReview = payload.ui_action === 'show_code_review'
            || payload.ready_for_code === true
            || goalReadyForCode;
        if (typeof payload.buggy_code === 'string' && payload.buggy_code.trim()) {
            state.feynmanPhase = 'code_review';
            state.buggyCode = payload.buggy_code;
            state.buggyCodeInfo = { buggy_code: payload.buggy_code, message: safeForumText(payload) };
            showCodeReviewPanel(payload.buggy_code);
            return;
        }
        if (shouldShowCodeReview && state.feynmanPhase === 'chat') {
            triggerCodeWritingPhase();
        }
    }

    function normalizeForumTurnPayload(payload) {
        if (!payload || typeof payload !== 'object') return null;
        if (payload.primary && typeof payload.primary === 'object') {
            return payload;
        }
        if (typeof payload.response === 'string') {
            return {
                primary: payload,
                interventions: [],
            };
        }
        return null;
    }

    function sanitizePublicForumHistory(history, options = {}) {
        if (!Array.isArray(history)) return [];
        return history
            .map(item => sanitizeForumEvent(item, options))
            .filter(Boolean)
            .slice(-MAX_PUBLIC_FORUM_EVENTS);
    }

    function sanitizeForumEvent(rawEvent, options = {}) {
        if (!rawEvent || typeof rawEvent !== 'object') return null;
        const sourceRole = normalizePublicRole(rawEvent.source_role || rawEvent.role);
        const targetRole = normalizePublicRole(rawEvent.target_role || 'user');
        const messageKind = normalizeForumMessageKind(rawEvent.message_kind || inferForumMessageKind(sourceRole));
        const content = safeString(rawEvent.content);
        if (!sourceRole || !targetRole || !messageKind || !content) return null;
        return {
            // This is client bookkeeping only; it is never included in a request.
            persisted: options.persisted === true || rawEvent.persisted === true,
            event_id: optionalString(rawEvent.event_id),
            event_type: optionalString(rawEvent.event_type) || (sourceRole === 'user' ? 'agent_user_message' : 'agent_message'),
            role: optionalString(rawEvent.role) || (sourceRole === 'user' ? 'student' : sourceRole),
            source_role: sourceRole,
            target_role: targetRole,
            message_kind: messageKind,
            visibility: 'public',
            content,
            request_id: optionalString(rawEvent.request_id),
            reply_to_event_id: optionalString(rawEvent.reply_to_event_id),
            parent_request_id: optionalString(rawEvent.parent_request_id),
        };
    }

    function normalizeForumTargetRole(role) {
        if (role === 'student_agent') return 'student_agent';
        if (role === 'auto') return 'auto';
        return 'teacher_agent';
    }

    function normalizePublicRole(role) {
        if (role === 'teacher_agent' || role === 'student_agent' || role === 'auto' || role === 'user' || role === 'system') {
            return role;
        }
        if (role === 'student') {
            return 'user';
        }
        return null;
    }

    function normalizeForumMessageKind(kind) {
        if (kind === 'user_message' || kind === 'agent_message' || kind === 'student_probe') {
            return kind;
        }
        return null;
    }

    function inferForumMessageKind(sourceRole) {
        return sourceRole === 'user' ? 'user_message' : 'agent_message';
    }

    function forumMessageKindFromPayload(payload) {
        if (payload && payload.message_kind) {
            const normalized = normalizeForumMessageKind(payload.message_kind);
            if (normalized) return normalized;
        }
        if (payload && payload.agent === 'student_agent' && payload.ui_action !== 'show_code_review') {
            return 'student_probe';
        }
        return 'agent_message';
    }

    function forumFallbackText(payload) {
        if (!payload || payload.success !== false) return '';
        const messages = {
            SESSION_LOCK_UNAVAILABLE: '当前会话正在处理中，请稍后再试。',
            STAGE3_NOT_ACTIVE: '当前会话还没有进入阶段 3，请刷新页面后再试。',
            STAGE3_UNAVAILABLE: '阶段 3 学习数据尚未准备好，请稍后再试。',
            CLIENT_UNAVAILABLE: '老师暂时无法连接模型，请先继续整理自己的思路，稍后再试。',
            CLIENT_ERROR: '老师暂时无法生成回复，请稍后再试。',
        };
        return messages[payload.error_code] || '当前暂时无法生成回复，请稍后重试。';
    }

    function safeForumText(payload, fallbackText = '') {
        if (!payload || typeof payload !== 'object') return fallbackText;
        if (typeof payload.message === 'string' && payload.message.trim()) {
            return payload.message.trim();
        }
        if (typeof payload.response === 'string' && payload.response.trim()) {
            return payload.response.trim();
        }
        return fallbackText;
    }

    function safeString(value) {
        return typeof value === 'string' ? value.trim() : '';
    }

    function optionalString(value) {
        return typeof value === 'string' && value.trim() ? value.trim() : null;
    }

    function forumComposerStorageKey() {
        if (state.assignmentId === null || state.assignmentId === undefined) return null;
        if (state.sessionId === null || state.sessionId === undefined) return null;
        return `codesense-stage3-forum-compose:${state.assignmentId}:${state.sessionId}`;
    }

    function loadPersistedForumComposerState() {
        if (!forumComposerStorageKey()) return null;
        try {
            return sanitizeStoredForumComposerState(sessionStorage.getItem(forumComposerStorageKey()));
        } catch (error) {
            return null;
        }
    }

    function persistForumComposerState() {
        if (!forumComposerStorageKey()) return;
        let replyToEventId = validateRestorableForumReplyEventId(state.forumReplyEventId);
        if (state.forumReplyContext) {
            replyToEventId = getPersistedForumReplyEventId();
        }
        const payload = {
            target_role: normalizeForumTargetRole(state.forumTargetRole),
            reply_to_event_id: replyToEventId,
        };
        if (!payload.reply_to_event_id && payload.target_role === 'teacher_agent') {
            clearPersistedForumComposerState();
            return;
        }
        try {
            sessionStorage.setItem(forumComposerStorageKey(), JSON.stringify(payload));
        } catch (error) {
            // Keep the composer usable when sessionStorage is unavailable.
        }
    }

    function clearPersistedForumComposerState() {
        if (!forumComposerStorageKey()) return;
        try {
            sessionStorage.removeItem(forumComposerStorageKey());
        } catch (error) {
            // Ignore storage errors and keep runtime state authoritative.
        }
    }

    function sanitizeStoredForumComposerState(rawState) {
        if (typeof rawState !== 'string' || !rawState.trim()) return null;
        try {
            const parsed = JSON.parse(rawState);
            if (!parsed || typeof parsed !== 'object') return null;
            return {
                target_role: normalizeForumTargetRole(parsed.target_role || 'teacher_agent'),
                reply_to_event_id: optionalString(parsed.reply_to_event_id),
            };
        } catch (error) {
            clearPersistedForumComposerState();
            return null;
        }
    }

    function sanitizeCoverageSummary(rawSummary) {
        const fallback = defaultCoverageSummary();
        if (!rawSummary || typeof rawSummary !== 'object') return fallback;
        const conceptCoverage = Array.isArray(rawSummary.concept_coverage)
            ? rawSummary.concept_coverage
                .map(item => sanitizeConceptCoverageItem(item))
                .filter(Boolean)
            : [];
        return {
            coverage_score: Number.isFinite(rawSummary.coverage_score) ? rawSummary.coverage_score : 0,
            ready_for_code: rawSummary.ready_for_code === true,
            unresolved_concepts: Array.isArray(rawSummary.unresolved_concepts)
                ? rawSummary.unresolved_concepts.map(item => safeString(item)).filter(Boolean)
                : [],
            concept_coverage: conceptCoverage,
            student_probe_intent: sanitizeProbeTarget(rawSummary.student_probe_intent),
        };
    }

    function sanitizeProbeTarget(rawTarget) {
        if (!rawTarget || typeof rawTarget !== 'object') return null;
        const concept = safeString(rawTarget.concept);
        const dimension = safeString(rawTarget.dimension);
        return concept && dimension ? { concept, dimension } : null;
    }

    function sanitizeUserGoal(rawGoal, fallbackSummary = defaultCoverageSummary()) {
        const fallback = defaultUserGoal(fallbackSummary);
        if (!rawGoal || typeof rawGoal !== 'object') return fallback;
        const rawSteps = Array.isArray(rawGoal.steps) ? rawGoal.steps : [];
        const steps = rawSteps
            .map(item => {
                if (!item || typeof item !== 'object') return null;
                const id = safeString(item.id);
                const label = safeString(item.label);
                const status = ['done', 'active', 'todo'].includes(item.status)
                    ? item.status
                    : 'todo';
                return id && label ? { id, label, status } : null;
            })
            .filter(Boolean);
        const numeric = (value, fallbackValue, minimum, maximum) => {
            const number = Number(value);
            return Number.isFinite(number)
                ? Math.max(minimum, Math.min(maximum, number))
                : fallbackValue;
        };
        return {
            ...fallback,
            id: safeString(rawGoal.id) || fallback.id,
            title: safeString(rawGoal.title) || fallback.title,
            description: safeString(rawGoal.description) || fallback.description,
            status: ['in_progress', 'ready_for_code', 'complete'].includes(rawGoal.status)
                ? rawGoal.status
                : fallback.status,
            progress_percent: Math.round(numeric(rawGoal.progress_percent, fallback.progress_percent, 0, 100)),
            coverage_score: numeric(rawGoal.coverage_score, fallback.coverage_score, 0, 1),
            coverage_threshold: numeric(rawGoal.coverage_threshold, fallback.coverage_threshold, 0, 1),
            covered_concepts: Math.round(numeric(rawGoal.covered_concepts, fallback.covered_concepts, 0, 999)),
            total_concepts: Math.round(numeric(rawGoal.total_concepts, fallback.total_concepts, 0, 999)),
            current_milestone: safeString(rawGoal.current_milestone) || fallback.current_milestone,
            next_action: safeString(rawGoal.next_action) || fallback.next_action,
            steps: steps.length ? steps : fallback.steps,
        };
    }

    function applyForumUserGoal(rawGoal) {
        if (rawGoal && typeof rawGoal === 'object') {
            state.forumUserGoal = sanitizeUserGoal(rawGoal, state.forumCoverageSummary || defaultCoverageSummary());
        } else if (!state.forumUserGoal) {
            state.forumUserGoal = defaultUserGoal(state.forumCoverageSummary || defaultCoverageSummary());
        }
        renderForumUserGoal();
    }

    function renderForumUserGoal() {
        const card = document.getElementById('forum-goal-card');
        if (!card) return;
        const goal = state.forumUserGoal || defaultUserGoal(state.forumCoverageSummary || defaultCoverageSummary());
        const title = document.getElementById('forum-goal-title');
        const description = document.getElementById('forum-goal-description');
        const status = document.getElementById('forum-goal-status');
        const progressBar = document.getElementById('forum-goal-progress-bar');
        const progressTrack = card.querySelector('.forum-goal-progress-track');
        const progressLabel = document.getElementById('forum-goal-progress-label');
        const coverageLabel = document.getElementById('forum-goal-coverage-label');
        const nextAction = document.getElementById('forum-goal-next');
        const steps = document.getElementById('forum-goal-steps');
        const progress = Math.max(0, Math.min(100, Number(goal.progress_percent) || 0));
        const statusLabels = {
            in_progress: '学习中',
            ready_for_code: '可以修复代码',
            complete: '已完成',
        };

        if (title) title.textContent = goal.title;
        if (description) description.textContent = goal.description;
        if (status) {
            status.className = `forum-goal-status is-${goal.status}`;
            status.textContent = statusLabels[goal.status] || '学习中';
        }
        if (progressBar) progressBar.style.width = `${progress}%`;
        if (progressTrack) progressTrack.setAttribute('aria-valuenow', String(progress));
        if (progressLabel) progressLabel.textContent = `${progress}%`;
        if (coverageLabel) {
            coverageLabel.textContent = goal.total_concepts > 0
                ? `${goal.covered_concepts}/${goal.total_concepts} 个关键点已覆盖`
                : '等待关键点检查';
        }
        if (nextAction) nextAction.textContent = goal.next_action;
        if (steps) {
            steps.innerHTML = '';
            goal.steps.forEach(item => {
                const step = document.createElement('li');
                step.className = `forum-goal-step is-${item.status}`;
                step.textContent = item.label;
                steps.appendChild(step);
            });
        }
    }

    function bindForumStickyHead() {
        const feed = document.getElementById('forum-feed');
        const stickyHead = document.getElementById('forum-sticky-head');
        if (!feed || !stickyHead || stickyHead.dataset.scrollBound) return;

        stickyHead.dataset.scrollBound = 'true';
        const panelBody = stickyHead.closest('.panel-body');
        const scrollTargets = [feed, panelBody].filter(
            (target, index, targets) => target && targets.indexOf(target) === index
        );
        let frameId = null;
        const updateStickyState = () => {
            frameId = null;
            const isScrolled = scrollTargets.some(target => target.scrollTop > 4);
            stickyHead.classList.toggle('is-scrolled', isScrolled);
        };

        scrollTargets.forEach(target => {
            target.addEventListener('scroll', () => {
                if (frameId === null) {
                    frameId = requestAnimationFrame(updateStickyState);
                }
            }, { passive: true });
        });
        updateStickyState();
    }

    function sanitizeConceptCoverageItem(rawItem) {
        if (!rawItem || typeof rawItem !== 'object') return null;
        const concept = safeString(rawItem.concept);
        const status = safeString(rawItem.status);
        const askedDimensions = Array.isArray(rawItem.asked_dimensions)
            ? rawItem.asked_dimensions
            : (Array.isArray(rawItem.used_dimensions) ? rawItem.used_dimensions : []);
        if (!concept || !status) return null;
        return {
            concept,
            status,
            asked_dimensions: askedDimensions
                .map(item => safeString(item))
                .filter(Boolean),
            accepted_evidence_count: Number.isInteger(rawItem.accepted_evidence_count)
                ? rawItem.accepted_evidence_count
                : 0,
            attempts: Number.isInteger(rawItem.attempts) ? rawItem.attempts : 0,
        };
    }

    function applyRestoredForumState(rawState, rawGoal = null) {
        const defaultState = {
            target_role: 'auto',
            reply_to_event_id: null,
            coverage_summary: defaultCoverageSummary(),
        };
        const source = rawState && typeof rawState === 'object' ? rawState : defaultState;
        state.forumCoverageSummary = sanitizeCoverageSummary(source.coverage_summary);
        const restoredGoal = rawGoal || source.user_goal;
        if (restoredGoal && typeof restoredGoal === 'object') {
            applyForumUserGoal(restoredGoal);
        } else {
            state.forumUserGoal = defaultUserGoal(state.forumCoverageSummary);
            renderForumUserGoal();
        }
        const restoredSelection = chooseRestoredForumComposerState(source);
        state.forumTargetRole = restoredSelection.target_role;
        state.forumReplyEventId = restoredSelection.reply_to_event_id;
        renderDevDebugCoverageSummary();
        persistForumComposerState();
    }

    function chooseRestoredForumComposerState(source) {
        const serverTargetRole = normalizeForumTargetRole(source.target_role || 'teacher_agent');
        const serverReplyEventId = validateRestorableForumReplyEventId(optionalString(source.reply_to_event_id));
        if (serverReplyEventId) {
            return {
                target_role: replyTargetRoleForEvent(findForumEventById(serverReplyEventId)),
                reply_to_event_id: serverReplyEventId,
            };
        }
        if (serverTargetRole === 'student_agent' || serverTargetRole === 'auto') {
            return {
                target_role: serverTargetRole,
                reply_to_event_id: null,
            };
        }
        const persistedComposer = loadPersistedForumComposerState();
        if (!persistedComposer) {
            return {
                target_role: serverTargetRole,
                reply_to_event_id: null,
            };
        }
        const replyEventId = validateRestorableForumReplyEventId(persistedComposer.reply_to_event_id);
        if (!replyEventId) {
            return {
                target_role: normalizeForumTargetRole(persistedComposer.target_role || serverTargetRole),
                reply_to_event_id: null,
            };
        }
        return {
            target_role: replyTargetRoleForEvent(findForumEventById(replyEventId)),
            reply_to_event_id: replyEventId,
        };
    }

    function validateRestorableForumReplyEventId(replyEventId) {
        if (!replyEventId || isSyntheticForumEventId(replyEventId)) {
            return null;
        }
        const persistedEvent = findForumEventById(replyEventId);
        if (!isPersistedForumEvent(persistedEvent)) {
            return null;
        }
        return persistedEvent.event_id;
    }

    function isSyntheticForumEventId(eventId) {
        const value = optionalString(eventId);
        return Boolean(value && SYNTHETIC_FORUM_EVENT_PREFIXES.some(prefix => value.indexOf(prefix) === 0));
    }

    function isPersistedForumEvent(event) {
        return Boolean(
            event &&
            event.persisted === true &&
            event.event_id &&
            !isSyntheticForumEventId(event.event_id)
        );
    }

    function forumAvatar(role) {
        if (role === 'teacher_agent') {
            return { label: 'Teacher Agent', icon: '👨‍🏫' };
        }
        if (role === 'student_agent') {
            return { label: 'Student Agent', icon: '🧑‍🎓' };
        }
        if (role === 'auto') {
            return { label: '自动安排', icon: '🧭' };
        }
        if (role === 'system') {
            return { label: 'System', icon: '🛠️' };
        }
        return { label: '用户', icon: '👤' };
    }

    function forumKindLabel(messageKind) {
        if (messageKind === 'student_probe') return '追问';
        if (messageKind === 'user_message') return '公开发言';
        return '回复';
    }

    function forumRelationLabel(event) {
        const targetLabel = forumAvatar(event.target_role).label;
        if (event.reply_to_event_id) {
            const replyTarget = findForumEventById(event.reply_to_event_id);
            if (replyTarget) {
                return `回复 ${forumAvatar(replyTarget.source_role).label}`;
            }
        }
        if (event.source_role === 'user') {
            return `发给 ${targetLabel}`;
        }
        return `面向 ${targetLabel}`;
    }

    function findForumEventById(eventId) {
        if (!eventId) return null;
        return state.forumHistory.find(item => item.event_id === eventId) || null;
    }

    function replyTargetRoleForEvent(event) {
        if (event.source_role === 'teacher_agent' || event.source_role === 'student_agent') {
            return event.source_role;
        }
        return normalizeForumTargetRole(event.target_role);
    }

    function setForumTarget(targetRole) {
        state.forumTargetRole = normalizeForumTargetRole(targetRole);
        if (state.forumReplyContext) {
            const replyTargetRole = replyTargetRoleForEvent(state.forumReplyContext);
            if (replyTargetRole !== state.forumTargetRole) {
                clearForumReplyContext();
            }
        }
        updateForumTargetControls();
        updateForumComposerState();
        persistForumComposerState();
    }

    function updateForumTargetControls() {
        const teacherBtn = document.getElementById('forum-target-teacher');
        const studentBtn = document.getElementById('forum-target-student');
        const autoBtn = document.getElementById('forum-target-auto');
        if (teacherBtn) {
            const selected = state.forumTargetRole === 'teacher_agent';
            teacherBtn.classList.toggle('is-selected', selected);
            teacherBtn.setAttribute('aria-pressed', String(selected));
        }
        if (studentBtn) {
            const selected = state.forumTargetRole === 'student_agent';
            studentBtn.classList.toggle('is-selected', selected);
            studentBtn.setAttribute('aria-pressed', String(selected));
        }
        if (autoBtn) {
            const selected = state.forumTargetRole === 'auto';
            autoBtn.classList.toggle('is-selected', selected);
            autoBtn.setAttribute('aria-pressed', String(selected));
        }
    }

    function setForumReplyContext(event) {
        const sanitized = sanitizeForumEvent(event);
        const container = document.getElementById('forum-reply-context');
        const label = container ? container.querySelector('.forum-reply-context-label') : null;
        if (!sanitized || !isPersistedForumEvent(sanitized) || !container || !label) {
            clearForumReplyContext();
            return;
        }
        state.forumReplyContext = sanitized;
        state.forumReplyEventId = sanitized.event_id;
        container.hidden = false;
        label.textContent = `正在回复 ${forumAvatar(sanitized.source_role).label}：${truncateText(sanitized.content, 48)}`;
        persistForumComposerState();
    }

    function getPersistedForumReplyEventId() {
        const context = state.forumReplyContext;
        if (!isPersistedForumEvent(context)) return null;
        const currentEvent = findForumEventById(context.event_id);
        return isPersistedForumEvent(currentEvent) ? currentEvent.event_id : null;
    }

    function clearForumReplyContext() {
        const container = document.getElementById('forum-reply-context');
        const label = container ? container.querySelector('.forum-reply-context-label') : null;
        state.forumReplyContext = null;
        state.forumReplyEventId = null;
        if (container) {
            container.hidden = true;
        }
        if (label) {
            label.textContent = '未选择回复对象';
        }
        persistForumComposerState();
    }

    function restoreForumReplyContext() {
        const replyEventId = validateRestorableForumReplyEventId(state.forumReplyEventId);
        if (!replyEventId) {
            clearForumReplyContext();
            return;
        }
        state.forumReplyEventId = replyEventId;
        const event = findForumEventById(replyEventId);
        if (!event) {
            clearForumReplyContext();
            return;
        }
        setForumReplyContext(event);
    }

    function updateForumComposerState() {
        const input = document.getElementById('forum-input');
        const sendBtn = document.getElementById('forum-send');
        const pending = Boolean(state.pendingForumRequestId);
        const hasText = Boolean(input && input.value.trim());
        if (input) {
            input.disabled = pending;
            input.setAttribute('aria-busy', String(pending));
        }
        if (sendBtn) {
            sendBtn.disabled = pending || !hasText;
            sendBtn.setAttribute('aria-busy', String(pending));
        }
    }

    function removeForumEventsByRequestId(requestId) {
        state.forumHistory = state.forumHistory.filter(item => item.request_id !== requestId);
        renderForumFeed();
    }

    function truncateText(text, maxLength) {
        if (typeof text !== 'string' || text.length <= maxLength) {
            return text || '';
        }
        return `${text.slice(0, maxLength - 1)}…`;
    }

    function showTypingIndicator(panel) {
        const container = getMessageContainer(panel);
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
        const container = getMessageContainer(panel);
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
        div.innerHTML = `<i class="bi bi-lightbulb"></i><span class="cs-markdown">${renderMarkdown(hint)}</span>`;
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
            <button type="button" class="dev-debug-toggle" aria-expanded="false"
                    aria-controls="dev-debug-content" aria-label="展开开发者调试面板">
                <span class="dev-debug-title">
                    <i class="bi bi-braces-asterisk" aria-hidden="true"></i>
                    <span>${panelTitle}</span>
                </span>
                <span class="dev-debug-chevron" aria-hidden="true">⌄</span>
            </button>
            <div id="dev-debug-content" class="dev-debug-content" hidden>
                <div class="dev-debug-description">${panelDescription}</div>
                <div class="dev-debug-btn-group">
                    <button class="dev-debug-btn" onclick="window.ThinkingArena.debugJumpStage(1)">跳到阶段一</button>
                    <button class="dev-debug-btn" onclick="window.ThinkingArena.debugJumpStage(2)">跳到阶段二</button>
                    <button class="dev-debug-btn" onclick="window.ThinkingArena.debugJumpStage(3)">跳到阶段三</button>
                    <button class="dev-debug-btn dev-debug-btn-success" onclick="window.ThinkingArena.debugJumpStage(4)">一键通关</button>
                </div>
                <div class="dev-debug-btn-group" style="margin-bottom: 0;">
                    <button class="dev-debug-auto dev-debug-btn dev-debug-btn-primary dev-debug-btn-full" onclick="window.ThinkingArena.debugAutoS1()">秒杀阶段一 (Auto S1)</button>
                    <button class="dev-debug-auto dev-debug-btn dev-debug-btn-primary dev-debug-btn-full" onclick="window.ThinkingArena.debugAutoS2()">秒杀阶段二 (Auto S2)</button>
                </div>
                <section class="dev-debug-trace" id="dev-debug-trace" aria-label="Stage 3 developer trace">
                    <div class="dev-debug-trace-header">
                        <span class="dev-debug-trace-title">Stage 3 Trace</span>
                        <button type="button" class="dev-debug-btn" id="dev-debug-trace-refresh">刷新</button>
                    </div>
                    <div class="dev-debug-trace-summary" id="dev-debug-trace-summary"></div>
                    <div class="dev-debug-trace-empty" id="dev-debug-trace-empty">展开后按需加载安全 Trace。</div>
                    <div class="dev-debug-trace-list" id="dev-debug-trace-list" hidden></div>
                </section>
            </div>
        `;

        if (isDemo) {
            panel.querySelectorAll('.dev-debug-auto').forEach(button => button.remove());
        }

        const toggle = panel.querySelector('.dev-debug-toggle');
        const content = panel.querySelector('.dev-debug-content');
        const traceRefresh = panel.querySelector('#dev-debug-trace-refresh');
        const storageKey = 'codesense-dev-debug-panel-collapsed';
        let storage = null;
        try {
            storage = window.sessionStorage;
        } catch (error) {
            // Private browsing modes may deny sessionStorage access.
        }

        const setCollapsed = (collapsed) => {
            panel.classList.toggle('is-collapsed', collapsed);
            toggle.setAttribute('aria-expanded', String(!collapsed));
            toggle.setAttribute('aria-label', collapsed ? '展开开发者调试面板' : '收起开发者调试面板');
            content.hidden = collapsed;
            if (storage) {
                try {
                    storage.setItem(storageKey, String(collapsed));
                } catch (error) {
                    // Keep the toggle usable when storage is unavailable.
                }
            }
        };

        let rememberedCollapsed = null;
        if (storage) {
            try {
                rememberedCollapsed = storage.getItem(storageKey);
            } catch (error) {
                // Use the default collapsed state when storage is unavailable.
            }
        }
        setCollapsed(rememberedCollapsed !== 'false');

        toggle.addEventListener('click', () => {
            setCollapsed(!panel.classList.contains('is-collapsed'));
            if (!panel.classList.contains('is-collapsed') && !state.devDebugTraceLoaded) {
                loadDevDebugTrace();
            }
        });
        toggle.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') {
                setCollapsed(true);
                toggle.focus();
            }
        });
        if (traceRefresh) {
            traceRefresh.addEventListener('click', () => {
                loadDevDebugTrace({ force: true });
            });
        }

        document.body.appendChild(panel);
        renderDevDebugCoverageSummary();
    }

    function renderDevDebugCoverageSummary() {
        const summaryEl = document.getElementById('dev-debug-trace-summary');
        if (!summaryEl) return;
        const summary = sanitizeCoverageSummary(state.forumCoverageSummary);
        const unresolvedText = summary.unresolved_concepts.length
            ? summary.unresolved_concepts.join('、')
            : '无';
        summaryEl.textContent = `coverage=${summary.coverage_score.toFixed(2)} | ready=${summary.ready_for_code ? 'yes' : 'no'} | unresolved=${unresolvedText}`;
    }

    function loadDevDebugTrace(options = {}) {
        const traceEmpty = document.getElementById('dev-debug-trace-empty');
        if (!state.sessionId) {
            renderDevDebugTrace([], '会话未初始化，暂无 Trace。');
            return Promise.resolve([]);
        }
        if (traceEmpty) {
            traceEmpty.textContent = '正在加载安全 Trace...';
        }
        return fetchJSON('/thinking/api/stage3/forum/trace', {
            method: 'POST',
            body: JSON.stringify({ session_id: state.sessionId })
        }).then(data => {
            const trace = Array.isArray(data.trace) ? data.trace : [];
            state.devDebugTraceLoaded = true;
            renderDevDebugTrace(trace);
            return trace;
        }).catch(error => {
            state.devDebugTraceLoaded = false;
            const message = options.force ? `Trace 加载失败：${error.message}` : 'Trace 暂不可用。';
            renderDevDebugTrace([], message);
            return [];
        });
    }

    function renderDevDebugTrace(rawTrace, emptyMessage) {
        const traceList = document.getElementById('dev-debug-trace-list');
        const traceEmpty = document.getElementById('dev-debug-trace-empty');
        if (!traceList || !traceEmpty) return;

        traceList.replaceChildren();
        const items = Array.isArray(rawTrace)
            ? rawTrace.map(item => sanitizeTraceEntry(item)).filter(Boolean)
            : [];
        if (!items.length) {
            traceList.hidden = true;
            traceEmpty.hidden = false;
            traceEmpty.textContent = emptyMessage || '暂无安全 Trace。';
            return;
        }

        const fields = [
            'event_type',
            'role',
            'target_role',
            'input_kind',
            'tool_name',
            'coverage_score',
            'ui_action',
        ];
        items.forEach(item => {
            const traceItem = document.createElement('article');
            traceItem.className = 'dev-debug-trace-item';
            fields.forEach(field => {
                const traceRow = document.createElement('div');
                traceRow.className = 'dev-debug-trace-row';

                const traceKey = document.createElement('span');
                traceKey.className = 'dev-debug-trace-key';
                traceKey.textContent = field;

                const traceValue = document.createElement('span');
                traceValue.className = 'dev-debug-trace-value';
                const value = item[field];
                traceValue.textContent = value === null || value === undefined ? 'null' : String(value);

                traceRow.appendChild(traceKey);
                traceRow.appendChild(traceValue);
                traceItem.appendChild(traceRow);
            });
            traceList.appendChild(traceItem);
        });
        traceEmpty.hidden = true;
        traceList.hidden = false;
    }

    function sanitizeTraceEntry(rawEntry) {
        if (!rawEntry || typeof rawEntry !== 'object') return null;
        const eventType = safeString(rawEntry.event_type);
        const role = safeString(rawEntry.role);
        if (!eventType || !role) return null;
        return {
            event_type: eventType,
            role,
            target_role: optionalString(rawEntry.target_role),
            input_kind: optionalString(rawEntry.input_kind),
            tool_name: optionalString(rawEntry.tool_name),
            coverage_score: Number.isFinite(rawEntry.coverage_score) ? rawEntry.coverage_score : null,
            ui_action: optionalString(rawEntry.ui_action),
        };
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
        renderForumProbeAction();
    }

    function fetchAIStream(url, options = {}, handlers = {}) {
        if (typeof window.consumeSSE !== 'function') {
            return fetchJSON(url, options);
        }
        let streamError = null;
        const streamOptions = {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...(options.headers || {})
            }
        };
        return window.consumeSSE(url, streamOptions, {
            ...handlers,
            onError: event => {
                streamError = new Error(event.message || event.error || '流式请求失败');
                if (handlers.onError) handlers.onError(event);
            }
        }).then(data => {
            if (streamError) throw streamError;
            return data || {};
        });
    }

    function renderMarkdown(str) {
        if (!str) return '';
        if (window.CodeSenseMarkdown) {
            return window.CodeSenseMarkdown.renderToString(str);
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

                    fetchAIStream('/thinking/api/stt/optimize', {
                        method: 'POST',
                        body: JSON.stringify({ text: spokenText })
                    }).then(data => {
                        const optimizedText = data.optimized_text || data.content || '';
                        if (data.success !== false && optimizedText) {
                            inputEl.value = baseValue + optimizedText;
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
        sendForumMessage,
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
