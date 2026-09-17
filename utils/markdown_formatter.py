"""
Markdown 格式化工具
统一处理 Markdown 文本的格式化和代码块增强
"""
import re
from typing import Optional


class MarkdownFormatter:
    """
    Markdown 格式化工具类

    提供统一的 Markdown 文本格式化和代码块增强功能
    """

    # 常见语言简写到标准名称的映射
    LANG_MAP = {
        'c': 'cpp',
        'py': 'python',
        'javascript': 'js',
        'j': 'java',
        'sh': 'bash',
        'shell': 'bash',
    }

    @staticmethod
    def enhance(text: str, default_lang: str = 'cpp') -> str:
        """
        增强 Markdown 文本

        1. 统一换行符
        2. 确保标题格式正确
        3. 确保代码块格式正确
        4. 处理列表格式

        Args:
            text: 原始 Markdown 文本
            default_lang: 默认代码语言

        Returns:
            增强后的 Markdown 文本
        """
        if not text:
            return text

        # 统一换行符
        text = text.replace('\r\n', '\n')

        # 确保标题格式正确（#后有空格）
        text = re.sub(r'(^|\n)(#{1,6})([^#\s])', r'\1\2 \3', text)

        # 确保标题前有空行：标题标记必须出现在物理行首（(?m)^ 的等价写法：
        # 匹配“上一行末字符 + 换行 + 行首标题”）。不得匹配同一行内紧邻的 #，
        # 否则 ## Title 的两个 # 会被当成“前置文本 + 标题”，把 H2–H6 拆成
        # 空 H1 + H1（历史缺陷）。替换只插入一个换行，不搬移字符。
        text = re.sub(r'(?m)([^\n])\n(#{1,6}[ \t])', r'\1\n\n\2', text)
        # 仅在标题行末（字面换行处）插入空行；lookahead 确保下一行非空，
        # 避免重复插入（幂等）。不得用 [^\n] 匹配行尾之后的内容——
        # 那会回溯吞掉标题行内的字符（历史缺陷：标题末字符被拆走）。
        text = re.sub(r'(?m)^(#{1,6}[^\n]+\n)(?=[^\n])', r'\1\n', text)

        # 确保代码块格式正确
        text = MarkdownFormatter._fix_code_blocks(text, default_lang)

        # 确保列表格式正确
        text = MarkdownFormatter._fix_lists(text)

        return text

    @staticmethod
    def enhance_code_blocks(text: str, default_lang: str = 'cpp') -> str:
        """
        增强代码块格式

        1. 修复缺失的语言标记
        2. 处理没有代码块格式的纯文本代码
        3. 确保代码块正确闭合

        Args:
            text: 原始文本
            default_lang: 默认语言

        Returns:
            增强后的文本
        """
        if not text:
            return text

        # 统一换行符
        text = text.replace('\r\n', '\n')

        # 修复代码块语言标记
        text = MarkdownFormatter._fix_code_block_langs(text, default_lang)

        # 处理纯文本代码
        text = MarkdownFormatter._fix_plain_code(text, default_lang)

        # 确保代码块闭合
        text = MarkdownFormatter._ensure_code_block_closed(text)

        return text

    @staticmethod
    def _fix_code_blocks(text: str, default_lang: str) -> str:
        """内部方法：修复代码块"""
        # 检查不完整的代码块标记
        if '```' in text:
            start_count = text.count('```')
            if start_count % 2 != 0:
                text += '\n```'

        return text

    @staticmethod
    def _fix_code_block_langs(text: str, default_lang: str) -> str:
        """内部方法：修复代码块语言标记"""
        pattern = r'```(.*?)\n(.*?)```'

        def replace_match(match):
            lang = match.group(1).strip()
            code = match.group(2)

            if not lang:
                lang = default_lang
            else:
                lang = MarkdownFormatter.LANG_MAP.get(lang.lower(), lang)

            return f'```{lang}\n{code}```'

        return re.sub(pattern, replace_match, text, flags=re.DOTALL)

    @staticmethod
    def _fix_plain_code(text: str, default_lang: str) -> str:
        """内部方法：处理纯文本代码"""
        paragraphs = text.split('\n\n')
        for i, para in enumerate(paragraphs):
            if MarkdownFormatter._looks_like_code(para):
                paragraphs[i] = f'```{default_lang}\n{para.strip()}\n```'

        return '\n\n'.join(paragraphs)

    @staticmethod
    def _looks_like_code(text: str) -> bool:
        """检查文本是否看起来像代码"""
        if '```' in text:
            return False
        if re.match(r'^#{1,3}\s', text, re.MULTILINE):  # 标题
            return False
        if re.match(r'^[*\-+>]\s', text, re.MULTILINE):  # 列表/引用
            return False

        code_markers = [';', '{', '}', '()', 'int ', 'void ', 'for(', 'while(', 'if(', 'else', 'return ', 'def ', 'class ']
        has_marker = any(marker in text for marker in code_markers)
        has_multiple_lines = len(text.strip().split('\n')) >= 2

        return has_marker and has_multiple_lines

    @staticmethod
    def _ensure_code_block_closed(text: str) -> str:
        """确保代码块闭合"""
        if '```' in text:
            start_count = text.count('```')
            if start_count % 2 != 0:
                text += '\n```'
        return text

    @staticmethod
    def _fix_lists(text: str) -> str:
        """修复列表格式"""
        lines = text.split('\n')
        formatted_lines = []
        in_code_block = False

        for line in lines:
            if line.strip().startswith('```'):
                in_code_block = not in_code_block
                formatted_lines.append(line)
                continue

            if not in_code_block:
                # 修复列表标记
                if re.match(r'^[*\-+](?!\s)', line):
                    line = line[0] + ' ' + line[1:]
                elif re.match(r'^\d+\.(?!\s)', line):
                    line = line[:-1] + ' ' + line[-1]

            formatted_lines.append(line)

        return '\n'.join(formatted_lines)

    @staticmethod
    def render_html(text: str, default_lang: str = 'cpp') -> str:
        """
        将 Markdown 转换为 HTML

        注意：这是一个简化实现，生产环境建议使用
        markdown 或 mistune 等库

        Args:
            text: Markdown 文本
            default_lang: 默认语言

        Returns:
            HTML 字符串
        """
        # 增强文本
        text = MarkdownFormatter.enhance(text, default_lang)

        # 简单转换（生产环境应该用 markdown 库）
        html_lines = []
        in_code_block = False

        for line in text.split('\n'):
            if line.strip().startswith('```'):
                in_code_block = not in_code_block
                if in_code_block:
                    lang = line.strip()[3:].strip()
                    html_lines.append(f'<pre><code class="language-{lang or default_lang}">')
                else:
                    html_lines.append('</code></pre>')
            elif in_code_block:
                html_lines.append(line.replace('<', '&lt;').replace('>', '&gt;'))
            elif line.strip().startswith('#'):
                level = len(line) - len(line.lstrip('#'))
                content = line.lstrip('#').strip()
                html_lines.append(f'<h{level}>{content}</h{level}>')
            elif line.strip().startswith('- ') or line.strip().startswith('* '):
                html_lines.append(f'<li>{line[2:].strip()}</li>')
            elif line.strip():
                html_lines.append(f'<p>{line}</p>')

        return '\n'.join(html_lines)


# 全局便捷函数
def enhance_markdown(text: str, default_lang: str = 'cpp') -> str:
    """便捷函数：增强 Markdown"""
    return MarkdownFormatter.enhance(text, default_lang)


def enhance_code_blocks(text: str, default_lang: str = 'cpp') -> str:
    """便捷函数：增强代码块"""
    return MarkdownFormatter.enhance_code_blocks(text, default_lang)
