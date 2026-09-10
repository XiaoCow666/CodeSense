/**
 * 代码编辑器核心实现
 * 支持Monaco编辑器和简易模式
 */

// 全局编辑器实例注册表
window.codeEditors = window.codeEditors || {};

// 编辑器偏好设置全局变量
if (typeof window.editorPreferences === 'undefined') {
    window.editorPreferences = {
        theme: 'vs-dark',
        fontSize: 14,
        tabSize: 4,
        fontFamily: "Consolas, 'Courier New', monospace",
        autoIndent: true,
        minimap: true,
        wordWrap: true
    };
}

// 全局单例管理
if (typeof window.editorManager === 'undefined') {
    window.editorManager = {
        instances: {},
        monacoLoaded: false,
        loading: false,
        loadEvents: [],
        onMonacoLoaded: function(callback) {
            if (this.monacoLoaded) {
                callback();
            } else {
                this.loadEvents.push(callback);
            }
        },
        notifyLoaded: function() {
            this.monacoLoaded = true;
            this.loading = false;
            for (let callback of this.loadEvents) {
                try {
                    callback();
                } catch (e) {
                    console.error('Monaco加载回调执行错误:', e);
                }
            }
            this.loadEvents = [];
        }
    };
}

/**
 * 初始化代码编辑器
 * @param {Object} options - 编辑器配置选项
 */
function initEditor(options) {
    console.log('编辑器初始化开始', options);
    
    const id = options.id || 'code-editor';
    const language = options.language || 'cpp';
    const height = options.height || 400;
    const theme = options.theme || window.editorPreferences.theme;
    const autoFocus = options.autoFocus !== undefined ? options.autoFocus : true;
    const readOnly = options.readOnly !== undefined ? options.readOnly : false;
    
    // 如果实例已存在，直接返回
    if (window.editorManager.instances[id]) {
        console.log(`编辑器实例 ${id} 已存在，无需再次初始化`);
        return window.editorManager.instances[id];
    }
    
    // 获取容器元素
    const container = document.getElementById(`${id}-container`);
    if (!container) {
        console.error(`找不到编辑器容器: ${id}-container`);
        return null;
    }
    
    // 获取初始内容
    let initialContent = '';
    const textarea = document.querySelector(`textarea[name="${id}"]`);
    if (textarea) {
        initialContent = textarea.value || '';
    }
    
    // 尝试加载Monaco编辑器
    if (typeof monaco === 'undefined') {
        // 如果已经在加载中，等待加载完成
        if (window.editorManager.loading) {
            window.editorManager.onMonacoLoaded(() => {
                createEditorInstance(id, container, language, initialContent, height, theme, autoFocus, readOnly, textarea);
            });
            return;
        }
        
        // 标记为加载中
        window.editorManager.loading = true;
        
        // 尝试加载Monaco编辑器
        tryLoadMonaco(() => {
            createEditorInstance(id, container, language, initialContent, height, theme, autoFocus, readOnly, textarea);
            // 通知加载完成
            window.editorManager.notifyLoaded();
        });
    } else {
        // Monaco已加载，直接创建实例
        createEditorInstance(id, container, language, initialContent, height, theme, autoFocus, readOnly, textarea);
    }
}

// 尝试加载Monaco编辑器
function tryLoadMonaco(callback) {
    console.log('加载Monaco编辑器开始...');
    
    // 清除可能存在的全局变量以防冲突
    if (window._amdLoaderGlobal) {
        console.log('检测到已存在的AMD加载器，正在清理...');
        try {
            delete window._amdLoaderGlobal;
            delete window.define;
            delete window.require;
        } catch (e) {
            console.warn('清理AMD加载器失败:', e);
        }
    }
    
    // Monaco 依赖整套 AMD 模块，统一从项目同源静态目录加载，
    // 避免浏览器依次等待多个不可达 CDN。
    const monacoBases = [
        '/static/vendor/monaco/0.40.0/min'
    ];
    
    // 尝试使用Require方式加载
    try {
        if (typeof require !== 'undefined') {
            require.config({
                paths: { 'vs': monacoBases[0] + '/vs' }
            });
            
            require(['vs/editor/editor.main'], function() {
                console.log('Monaco编辑器加载成功(Require方式)');
                if (callback) callback();
            });
        } else {
            throw new Error('require is not defined');
        }
    } catch (e) {
        console.log('Require方式加载Monaco失败，尝试脚本方式: ', e);
        loadMonacoScript(monacoBases, 0, callback);
    }
}

// 通过脚本方式加载Monaco
function loadMonacoScript(cdnList, index, callback) {
    if (index >= cdnList.length) {
        console.error('Monaco加载失败：所有CDN源都尝试失败');
        
        // 加载失败时回退到CodeMirror
        trySwitchToCodeMirror();
        return;
    }
    
    const cdn = cdnList[index];
    console.log(`尝试从 ${cdn} 加载Monaco编辑器 (${index + 1}/${cdnList.length})`);
    
    // 加载loader.js
    const loaderScript = document.createElement('script');
    loaderScript.src = `${cdn}/vs/loader.js`;
    loaderScript.async = true;
    
    // 设置超时
    const timeoutId = setTimeout(() => {
        console.warn(`从 ${cdn} 加载超时，尝试下一个CDN源`);
        loadMonacoScript(cdnList, index + 1, callback);
    }, 10000);
    
    // 加载成功
    loaderScript.onload = function() {
        clearTimeout(timeoutId);
        console.log('Monaco加载脚本加载成功，继续初始化');
        
        // 确保require已定义
        if (typeof require === 'undefined') {
            console.error('脚本加载成功但require未定义，尝试下一个CDN源');
            loadMonacoScript(cdnList, index + 1, callback);
            return;
        }
        
        require.config({
            paths: { 'vs': `${cdn}/vs` }
        });
        
        // 设置内部加载超时
        const internalTimeout = setTimeout(() => {
            console.warn('Monaco内部模块加载超时，尝试下一个CDN源');
            loadMonacoScript(cdnList, index + 1, callback);
        }, 15000);
        
        // 加载主编辑器模块
        require(['vs/editor/editor.main'], function() {
            clearTimeout(internalTimeout);
            console.log('Monaco编辑器加载成功(脚本方式)');
            if (callback) callback();
        });
    };
    
    // 加载失败
    loaderScript.onerror = function() {
        clearTimeout(timeoutId);
        console.warn(`从 ${cdn} 加载失败，尝试下一个CDN源`);
        loadMonacoScript(cdnList, index + 1, callback);
    };
    
    document.head.appendChild(loaderScript);
}

// 创建编辑器实例
function createEditorInstance(id, container, language, initialContent, height, theme, autoFocus, readOnly, textarea) {
    if (!monaco) {
        console.error('Monaco未加载，无法创建编辑器实例');
        return null;
    }
    
    try {
        // 设置编辑器配置
        const editorOptions = {
            value: initialContent,
            language: language,
            theme: theme,
            automaticLayout: true,
            fontSize: window.editorPreferences.fontSize,
            fontFamily: window.editorPreferences.fontFamily,
            tabSize: window.editorPreferences.tabSize,
            minimap: {
                enabled: window.editorPreferences.minimap
            },
            lineNumbers: 'on',
            scrollBeyondLastLine: false,
            wordWrap: window.editorPreferences.wordWrap ? 'on' : 'off',
            autoIndent: window.editorPreferences.autoIndent ? 'advanced' : 'none',
            readOnly: readOnly,
            fixedOverflowWidgets: true
        };
        
        // 创建编辑器实例
        const editor = monaco.editor.create(container, editorOptions);
        
        // 存储实例
        window.editorManager.instances[id] = editor;
        
        // 如果全局codeEditor未设置，设置它（向后兼容）
        if (!window.codeEditor) {
            window.codeEditor = editor;
        }
        
        // 处理编辑器内容变化事件
        if (textarea) {
            editor.onDidChangeModelContent(() => {
                textarea.value = editor.getValue();
            });
        }
        
        // 设置高度
        container.style.height = typeof height === 'number' ? `${height}px` : height;
        
        // 自动聚焦
        if (autoFocus) {
            setTimeout(() => {
                try {
                    editor.focus();
                } catch (e) {
                    console.warn('编辑器自动聚焦失败:', e);
                }
            }, 100);
        }
        
        // 添加额外的命令和功能
        addEditorCommands(editor);
        
        console.log(`编辑器实例 ${id} 创建成功`);
        return editor;
    } catch (e) {
        console.error('创建Monaco编辑器实例失败:', e);
        return null;
    }
}

// 添加编辑器命令
function addEditorCommands(editor) {
    // 添加格式化命令
    if (monaco && editor) {
        editor.addAction({
            id: 'format-code',
            label: '格式化代码',
            keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.KeyF],
            contextMenuGroupId: '1_modification',
            run: function(ed) {
                ed.getAction('editor.action.formatDocument').run();
            }
        });
        
        // 添加切换注释命令
        editor.addAction({
            id: 'toggle-comment',
            label: '切换注释',
            keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.Slash],
            contextMenuGroupId: '1_modification',
            run: function(ed) {
                ed.getAction('editor.action.commentLine').run();
            }
        });
    }
}

// 尝试使用CodeMirror作为备选
function trySwitchToCodeMirror() {
    console.log('尝试加载CodeMirror作为备选编辑器...');
    
    // 检查是否已加载CodeMirror
    if (typeof CodeMirror !== 'undefined') {
        console.log('CodeMirror 已正确加载');
        initCodeMirror();
        return;
    }
    
    // 加载CodeMirror
    const cmScript = document.createElement('script');
    cmScript.src = '/static/vendor/codemirror/5.65.2/codemirror.js';
    cmScript.onload = function() {
        console.log('CodeMirror 核心加载成功');
        
        // 加载C++模式
        const modeScript = document.createElement('script');
        modeScript.src = '/static/vendor/codemirror/5.65.2/mode/clike/clike.js';
        modeScript.onload = function() {
            console.log('C++ 模式加载成功');
            initCodeMirror();
        };
        modeScript.onerror = function() {
            console.log('C++ 模式未加载，尝试加载');
            initCodeMirror();
        };
        document.head.appendChild(modeScript);
        
        // 加载样式
        const style = document.createElement('link');
        style.rel = 'stylesheet';
        style.href = '/static/vendor/codemirror/5.65.2/codemirror.css';
        document.head.appendChild(style);
        
        // 加载主题
        const theme = document.createElement('link');
        theme.rel = 'stylesheet';
        theme.href = '/static/vendor/codemirror/5.65.2/theme/dracula.css';
        document.head.appendChild(theme);
    };
    cmScript.onerror = function() {
        console.error('CodeMirror 加载失败，回退到textarea');
        useTextarea();
    };
    document.head.appendChild(cmScript);
}

// 初始化CodeMirror编辑器
function initCodeMirror() {
    // 获取所有编辑器容器
    const containers = document.querySelectorAll('[id$="-container"]');
    
    containers.forEach(container => {
        const id = container.id.replace('-container', '');
        const textarea = document.querySelector(`textarea[name="${id}"]`);
        
        if (!textarea) return;
        
        try {
            // 创建新的textarea
            const newTextarea = document.createElement('textarea');
            newTextarea.value = textarea.value;
            newTextarea.name = textarea.name;
            newTextarea.id = textarea.id;
            container.innerHTML = '';
            container.appendChild(newTextarea);
            
            // 初始化CodeMirror
            const cm = CodeMirror.fromTextArea(newTextarea, {
                mode: 'text/x-c++src',
                theme: 'dracula',
                lineNumbers: true,
                indentUnit: 4,
                tabSize: 4,
                lineWrapping: true,
                autoCloseBrackets: true,
                matchBrackets: true,
                extraKeys: {
                    "Ctrl-Space": "autocomplete",
                    "Tab": function(cm) {
                        if (cm.somethingSelected()) {
                            cm.indentSelection("add");
                        } else {
                            cm.replaceSelection("    ", "end");
                        }
                    }
                }
            });
            
            // 设置高度
            cm.setSize(null, 400);
            
            // 保存到全局
            if (!window.codeEditor) {
                window.codeEditor = cm;
            }
            window.editorManager.instances[id] = cm;
            
            console.log(`CodeMirror编辑器实例 ${id} 创建成功`);
        } catch (e) {
            console.error(`创建CodeMirror实例失败: ${e}`);
            useTextarea();
        }
    });
}

// 回退到普通textarea
function useTextarea() {
    // 显示所有隐藏的textarea
    const textareas = document.querySelectorAll('textarea[style*="display: none"]');
    textareas.forEach(textarea => {
        textarea.style.display = 'block';
        textarea.style.width = '100%';
        textarea.style.height = '400px';
        textarea.style.fontFamily = 'monospace';
        textarea.style.padding = '10px';
        
        // 清除容器
        const containerId = textarea.name + '-container';
        const container = document.getElementById(containerId);
        if (container) {
            container.innerHTML = '';
            container.appendChild(textarea);
        }
    });
    
    console.warn('已切换到基本文本编辑器模式');
}

// 获取编辑器内容的通用方法（兼容性支持）
function getEditorCode(id) {
    id = id || 'code';
    
    // 尝试从Monaco实例获取
    if (window.editorManager && window.editorManager.instances[id]) {
        const editor = window.editorManager.instances[id];
        if (editor.getValue) {
            return editor.getValue();
        } else if (editor.getDoc && editor.getDoc().getValue) {
            // CodeMirror
            return editor.getDoc().getValue();
        }
    }
    
    // 尝试从全局codeEditor获取
    if (window.codeEditor) {
        if (window.codeEditor.getValue) {
            return window.codeEditor.getValue();
        } else if (window.codeEditor.getDoc && window.codeEditor.getDoc().getValue) {
            // CodeMirror
            return window.codeEditor.getDoc().getValue();
        }
    }
    
    // 回退到textarea
    const textarea = document.querySelector(`textarea[name="${id}"]`);
    if (textarea) {
        return textarea.value;
    }
    
    return '';
}

// 设置编辑器内容的通用方法
function setEditorCode(code, id) {
    id = id || 'code';
    
    // 尝试使用Monaco实例
    if (window.editorManager && window.editorManager.instances[id]) {
        const editor = window.editorManager.instances[id];
        if (editor.setValue) {
            editor.setValue(code);
            return true;
        } else if (editor.getDoc && editor.getDoc().setValue) {
            // CodeMirror
            editor.getDoc().setValue(code);
            return true;
        }
    }
    
    // 尝试使用全局codeEditor
    if (window.codeEditor) {
        if (window.codeEditor.setValue) {
            window.codeEditor.setValue(code);
            return true;
        } else if (window.codeEditor.getDoc && window.codeEditor.getDoc().setValue) {
            // CodeMirror
            window.codeEditor.getDoc().setValue(code);
            return true;
        }
    }
    
    // 回退到textarea
    const textarea = document.querySelector(`textarea[name="${id}"]`);
    if (textarea) {
        textarea.value = code;
        return true;
    }
    
    return false;
}

// 为window暴露接口
window.initEditor = initEditor;
window.getEditorCode = getEditorCode;
window.setEditorCode = setEditorCode;

// 公共API
window.CodeEditor = {
    /**
     * 获取指定编辑器的内容
     * @param {string} id - 编辑器ID
     * @returns {string} 编辑器内容
     */
    getValue(id) {
        if (window.codeEditors[id]) {
            return window.codeEditors[id].getValue();
        }
        const textarea = document.getElementById(id);
        return textarea ? textarea.value : '';
    },
    
    /**
     * 设置指定编辑器的内容
     * @param {string} id - 编辑器ID
     * @param {string} value - 要设置的内容
     */
    setValue(id, value) {
        if (window.codeEditors[id]) {
            window.codeEditors[id].setValue(value);
        } else {
            const textarea = document.getElementById(id);
            if (textarea) {
                textarea.value = value;
            }
        }
    },
    
    /**
     * 切换编辑器的编程语言
     * @param {string} id - 编辑器ID
     * @param {string} language - 要设置的编程语言
     */
    setLanguage(id, language) {
        if (!window.codeEditors[id]) {
            console.warn(`找不到ID为${id}的编辑器实例`);
            return;
        }
        
        // 获取Monaco支持的语言标识
        const getMonacoLanguage = function(lang) {
            const languageMap = {
                'python': 'python',
                'py': 'python',
                'java': 'java',
                'javascript': 'javascript',
                'js': 'javascript',
                'typescript': 'typescript',
                'ts': 'typescript',
                'html': 'html',
                'css': 'css',
                'c': 'c',
                'cpp': 'cpp',
                'c++': 'cpp',
                'csharp': 'csharp',
                'cs': 'csharp',
                'php': 'php',
                'ruby': 'ruby',
                'go': 'go',
                'rust': 'rust',
                'sql': 'sql',
                'markdown': 'markdown',
                'md': 'markdown',
                'json': 'json',
                'xml': 'xml',
                'yaml': 'yaml',
                'yml': 'yaml'
            };
            
            return languageMap[lang.toLowerCase()] || 'plaintext';
        };
        
        const editor = window.codeEditors[id];
        
        if (editor.isMonacoMode && editor.instance) {
            // 获取Monaco编辑器支持的语言ID
            const monacoLanguage = getMonacoLanguage(language);
            
            // 更改Monaco编辑器模型的语言
            const oldModel = editor.instance.getModel();
            const value = oldModel.getValue();
            
            monaco.editor.setModelLanguage(oldModel, monacoLanguage);
            
            // 更新编辑器工具栏显示的语言（如果有）
            const editorEl = document.getElementById(`code-editor-${id}`);
            if (editorEl) {
                const languageDisplay = editorEl.querySelector('.editor-language');
                if (languageDisplay) {
                    let icon = 'code-slash';
                    let displayName = language.charAt(0).toUpperCase() + language.slice(1);
                    
                    // 根据语言设置合适的图标
                    if (language === 'python' || language === 'py') {
                        icon = 'filetype-py';
                        displayName = 'Python';
                    } else if (language === 'java') {
                        icon = 'filetype-java';
                        displayName = 'Java';
                    } else if (language === 'c') {
                        icon = 'filetype-c';
                        displayName = 'C';
                    } else if (language === 'cpp' || language === 'c++') {
                        icon = 'filetype-cpp';
                        displayName = 'C++';
                    }
                    
                    languageDisplay.innerHTML = `<i class="bi bi-${icon}"></i> ${displayName}`;
                }
            }
            
            console.log(`已将编辑器 ${id} 的语言设置为 ${language}`);
        } else if (!editor.isMonacoMode) {
            // 对于简易模式，我们只能更新textarea的类和属性
            const textarea = document.getElementById(id);
            if (textarea) {
                textarea.dataset.language = language;
                console.log(`已将编辑器 ${id} 的语言设置为 ${language}（简易模式）`);
            }
        }
    }
};
