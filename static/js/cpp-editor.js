/**
 * C++代码编辑器 - 简化版
 * 使用项目同源静态资源中的 Monaco 编辑器
 */

// 全局编辑器实例
window.cppEditor = null;

// 编辑器配置
const editorConfig = {
    theme: 'vs-dark',
    fontSize: 14,
    tabSize: 4,
    language: 'cpp'
};

/**
 * 初始化编辑器
 * @param {string} id - 编辑器容器ID
 */
function initEditor(id) {
    console.log('初始化C++编辑器:', id);
    
    // 获取DOM元素
    const container = document.getElementById(`monaco-${id}`);
    const textarea = document.getElementById(id);
    const editorElement = document.getElementById(`editor-${id}`);
    
    if (!container || !textarea || !editorElement) {
        console.error(`找不到编辑器元素，容器ID: monaco-${id}, textarea ID: ${id}, editor ID: editor-${id}`);
        return;
    }
    
    const loadingElement = editorElement.querySelector('.editor-loading');
    
    // 显示加载状态
    if (loadingElement) loadingElement.style.display = 'flex';
    
    // 获取初始内容
    const initialContent = textarea.value || '';
    
    // 如果Monaco已加载，直接创建编辑器
    if (typeof monaco !== 'undefined') {
        createMonacoEditor(id, container, initialContent);
        return;
    }
    
    // 加载Monaco编辑器
    loadMonaco(() => {
        createMonacoEditor(id, container, initialContent);
    }, () => {
        // 加载失败时使用基本textarea
        console.error('Monaco编辑器加载失败，使用基本文本框');
        if (loadingElement) loadingElement.style.display = 'none';
        textarea.style.display = 'block';
        if (container) container.style.display = 'none';
    });
}

/**
 * 加载Monaco编辑器
 * 只使用单一同源静态资源
 */
function loadMonaco(onSuccess, onError) {
    // 检查是否已加载
    if (typeof monaco !== 'undefined') {
        onSuccess();
        return;
    }
    
    // Monaco 是一套 AMD 模块，必须保留 /vs 目录结构。
    const monacoPath = '/static/vendor/monaco/0.40.0/min';
    
    // 创建加载脚本
    const script = document.createElement('script');
    script.src = `${monacoPath}/vs/loader.js`;
    script.async = true;
    script.onload = () => {
        if (typeof require === 'undefined') {
            console.error('加载脚本成功但require未定义');
            onError();
            return;
        }
        
        // 配置require
        require.config({
            paths: { 'vs': `${monacoPath}/vs` }
        });
        
        // 设置超时
        const timeout = setTimeout(() => {
            console.error('Monaco编辑器加载超时');
            onError();
        }, 10000);
        
        // 加载编辑器主模块
        require(['vs/editor/editor.main'], () => {
            clearTimeout(timeout);
            console.log('Monaco编辑器加载成功');
            onSuccess();
        });
    };
    
    script.onerror = () => {
        console.error('Monaco编辑器加载器脚本加载失败');
        onError();
    };
    
    // 添加到文档
    document.head.appendChild(script);
}

/**
 * 创建Monaco编辑器实例
 */
function createMonacoEditor(id, container, content) {
    console.log('创建Monaco编辑器实例');
    
    const textarea = document.getElementById(id);
    const editorElement = document.getElementById(`editor-${id}`);
    
    if (!textarea || !editorElement) {
        console.error(`找不到必要的编辑器元素，textarea ID: ${id}, editor ID: editor-${id}`);
        return;
    }
    
    const loadingElement = editorElement.querySelector('.editor-loading');
    
    try {
        // 显示Monaco容器
        container.style.display = 'block';
        
        // 创建编辑器
        const editor = monaco.editor.create(container, {
            value: content,
            language: 'cpp',
            theme: editorConfig.theme,
            automaticLayout: true,
            fontSize: editorConfig.fontSize,
            tabSize: editorConfig.tabSize,
            minimap: { enabled: true },
            scrollBeyondLastLine: false,
            lineNumbers: 'on',
            wordWrap: 'on',
            fixedOverflowWidgets: true
        });
        
        // 保存实例
        window.cppEditor = editor;
        
        // 监听内容变化事件，同步到textarea
        editor.onDidChangeModelContent(() => {
            if (textarea) {
                textarea.value = editor.getValue();
                updateCharCount(editor.getValue(), editorElement);
            }
        });
        
        // 监听光标位置
        editor.onDidChangeCursorPosition((e) => {
            const lineNumber = editorElement.querySelector('.line-number');
            const columnNumber = editorElement.querySelector('.column-number');
            
            if (lineNumber) lineNumber.textContent = e.position.lineNumber;
            if (columnNumber) columnNumber.textContent = e.position.column;
        });
        
        // 初始化字符统计
        updateCharCount(content, editorElement);
        
        // 绑定工具栏按钮事件
        bindToolbarActions(editor, editorElement);
        
        // 隐藏加载状态
        if (loadingElement) loadingElement.style.display = 'none';
        
        console.log('编辑器创建成功');
    } catch (error) {
        console.error('创建编辑器失败:', error);
        
        // 显示textarea作为后备
        if (textarea) textarea.style.display = 'block';
        container.style.display = 'none';
        
        // 隐藏加载状态
        if (loadingElement) loadingElement.style.display = 'none';
    }
}

/**
 * 更新字符统计
 */
function updateCharCount(text, editorElement) {
    const charCount = editorElement.querySelector('.char-count');
    if (charCount) {
        charCount.textContent = text.length;
    }
}

/**
 * 绑定工具栏按钮事件
 */
function bindToolbarActions(editor, editorElement) {
    // 格式化代码按钮
    const formatBtn = editorElement.querySelector('[data-action="format"]');
    if (formatBtn) {
        formatBtn.addEventListener('click', () => {
            editor.getAction('editor.action.formatDocument').run();
        });
    }
    
    // 切换主题按钮
    const themeBtn = editorElement.querySelector('[data-action="theme"]');
    if (themeBtn) {
        themeBtn.addEventListener('click', () => {
            const currentTheme = editorConfig.theme;
            const newTheme = currentTheme === 'vs-dark' ? 'vs' : 'vs-dark';
            
            // 更新配置
            editorConfig.theme = newTheme;
            
            // 应用主题
            monaco.editor.setTheme(newTheme);
            
            // 更新图标
            if (newTheme === 'vs-dark') {
                themeBtn.innerHTML = '<i class="bi bi-moon-stars"></i>';
                themeBtn.title = "切换到浅色模式";
            } else {
                themeBtn.innerHTML = '<i class="bi bi-sun"></i>';
                themeBtn.title = "切换到深色模式";
            }
            
            console.log('编辑器主题已切换为:', newTheme);
        });
    }
    const fullscreenBtn = editorElement.querySelector('[data-action="fullscreen"]');
    if (fullscreenBtn) {
        fullscreenBtn.addEventListener('click', () => {
            editorElement.classList.toggle('fullscreen');
            if (editorElement.classList.contains('fullscreen')) {
                fullscreenBtn.innerHTML = '<i class="bi bi-fullscreen-exit"></i>';
            } else {
                fullscreenBtn.innerHTML = '<i class="bi bi-fullscreen"></i>';
            }
            // 通知编辑器调整布局
            setTimeout(() => editor.layout(), 100);
        });
    }
}

/**
 * 获取编辑器内容
 */
function getEditorContent() {
    if (window.cppEditor && window.cppEditor.getValue) {
        return window.cppEditor.getValue();
    }
    
    // 回退到textarea
    const textarea = document.querySelector('.editor-textarea');
    if (textarea) {
        return textarea.value;
    }
    
    return '';
}

/**
 * 设置编辑器内容
 */
function setEditorContent(content) {
    if (window.cppEditor && window.cppEditor.setValue) {
        window.cppEditor.setValue(content);
        return;
    }
    
    // 回退到textarea
    const textarea = document.querySelector('.editor-textarea');
    if (textarea) {
        textarea.value = content;
    }
}

// 暴露API
window.initEditor = initEditor;
window.getEditorContent = getEditorContent;
window.setEditorContent = setEditorContent;
