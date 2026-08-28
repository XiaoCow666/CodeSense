from typing import Dict, List, Generator
import os
import json
import requests
from dotenv import load_dotenv
import re

# 加载环境变量
load_dotenv()

# 导入统一的 API 密钥管理器
from services.api_keys import api_keys


class AIEvaluator:
    def __init__(self, api_key: str = None):
        """初始化智谱AI评估器"""
        # 优先使用传入的api_key，如果没有则使用统一的 API 密钥管理器
        if api_key:
            self.api_key = api_key
        else:
            self.api_key = api_keys.get_key('zhipu')
        
    def evaluate_code(self, code: str, assignment_title: str) -> Dict:
        """使用智谱大模型评估代码"""
        prompt = f"""请分析以下代码的编程能力水平，从以下维度进行评估：
1. 算法能力：评估算法设计、逻辑思维、问题求解能力
2. 代码风格：评估代码可读性、命名规范、注释质量
3. 功能实现：评估功能完整性、正确性、健壮性
4. 效率优化：评估时间复杂度、空间复杂度、资源利用
5. 代码可读性：评估代码的易读性和可维护性

作业标题：{assignment_title}
代码：
{code}

请以 JSON 格式返回评估结果，包含以下字段：
- algorithm_score: 算法能力得分(0-100)
- style_score: 代码风格得分(0-100)
- functionality_score: 功能实现得分(0-100)
- efficiency_score: 效率优化得分(0-100)
- readability_score: 代码可读性得分(0-100)
- feedback: 详细的评估反馈和建议。具体要求：
    1. 使用标准的 **Markdown** 格式。
    2. 使用 `###` 标题进行分段（例如：### 算法逻辑、### 改进建议）。
    3. 使用有序列表 `1. 2. 3.` 或无序列表 `-`。
    4. 适当使用 **加粗** 强调关键点。
    5. 确保内容分段清晰，易于阅读。
"""

        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            data = {
                "model": "glm-4.5-flash",
                "messages": [
                    {"role": "system", "content": "你是一个专业的代码评估专家，擅长分析代码质量和编程能力。"},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,
                "max_tokens": 1000
            }
            from services.llm_client import safe_zhipu_post
            response = safe_zhipu_post(
                "https://open.bigmodel.cn/api/paas/v4/chat/completions",
                headers=headers,
                json_data=data,
                timeout=30
            )
            if response.status_code == 200:
                result = response.json()
                result_content = result["choices"][0]["message"]["content"]
                result_json = json.loads(result_content)
                return result_json
            else:
                print(f"智谱API请求失败: {response.status_code} - {response.text}")
                return {
                    "algorithm_score": 60, "style_score": 60,
                    "functionality_score": 60, "efficiency_score": 60,
                    "readability_score": 60, "feedback": "评估过程中出现错误，请稍后重试。"
                }
        except Exception as e:
            print(f"AI评估出错: {str(e)}")
            return {
                "algorithm_score": 60, "style_score": 60,
                "functionality_score": 60, "efficiency_score": 60,
                "readability_score": 60, "feedback": "评估过程中出现错误，请稍后重试。"
            }

    def format_assignment_text(self, raw_text: str) -> Generator[str, None, None]:
        """
        将原始作业文本通过 LLM 解析或根据简短指令生成完整作业，流式返回 JSON 字符串。
        JSON 包含字段：suggested_id (int)、title (str)、description (Markdown str)、test_cases (array)。
        调用方收集所有 chunk 拼接后再解析 JSON。
        """
        prompt = f"""你是一位资深计算机科学教授和出题专家。请根据用户输入，以**严格 JSON** 格式输出一道完整的编程作业题。

## 绝对禁止（违反任何一条都是不合格的出题）
1. **禁止模糊描述**：不能出现"根据题目要求"、"按实际情况"等含糊措辞。每一行输入/输出必须精确定义：数据类型、取值范围、分隔符。
2. **禁止自创非标准算法题**：只能出**经典、有明确定义的编程题**，例如：两数之和、斐波那契数列、最长递增子序列、最短路径(Dijkstra)、0-1背包问题、排序算法、二叉树遍历、最大子数组和、编辑距离、最长公共子序列等。不要自创模糊的算法变体。
3. **禁止输入格式与题目脱节**：输入格式必须与该经典问题的标准定义完全匹配。
4. **禁止占位符**：test_cases 中的 input/output 必须是真实数据。
5. **禁止省略号和缩写**：test_cases 中的 input 和 output 数据绝对不允许出现 "..."、"…"、"省略"、"以此类推"、"etc" 等任何形式的省略或截断。每个测试用例的输入输出必须是**完整的、可直接喂给程序stdin的真实数据**。如果数据行数多，就老老实实写完所有行，不要偷懒缩写。
6. **测试数据规模要小**：为避免数据过长，每个测试用例的输入数据不要超过20行。设计题目时就应控制好数据规模（例如n≤20），这样测试用例才能完整写出。
7. **输出必须是纯粹的结果数据**：绝对禁止要求输出中间过程、调试信息或复杂的提示文字（如禁止输出"构建过程："、"节点加入"等）。只输出最终的计算结果（例如纯数字、纯字符串），以保证答案的唯一性和可判定性。
8. **必须在题目描述中明确边界情况的输出**：如果题目涉及可能导致错误的操作（如空队列执行出队或查看队首、数组越界等），必须在题目描述的【输出格式】中**明确规定**此时应输出什么（例如"如果队列为空，输出 None"）。绝对不能让边界情况处于未定义状态，否则将导致自动沙箱运行崩溃！

## 自检规则（生成后必须在心里验证）
- 拿到你写的题目描述，任何一个合格的程序员都应该能**无歧义地**写出正确程序，且清楚边界条件怎么输出。
- 你自己要能对每个 test_case 的 input **手动推演**得出对应的 output。
- 如果你无法手动验证，说明题目定义有问题，必须重新设计。

## 输出格式（严格 JSON，不得在 JSON 外附加任何文字）
{{
  "suggested_id": <建议的整数作业ID，范围101-999>,
  "title": "<简洁的中文标题>",
  "description": "<Markdown 格式，必须包含：\\n### 作业描述\\n（题目背景和明确要求，不少于80字）\\n\\n### 输入格式\\n（逐行说明数据类型、取值范围、分隔符）\\n\\n### 输出格式\\n（精确说明输出内容和格式）\\n\\n### 输入样例\\n```\\n（真实数据）\\n```\\n\\n### 输出样例\\n```\\n（你手动推演过的正确结果）\\n```>",
  "test_cases": [
    {{"input": "<测试输入>", "output": "<你手动推演过的正确输出>", "is_public": true}},
    {{"input": "<测试输入>", "output": "<你手动推演过的正确输出>", "is_public": false}}
  ]
}}

## test_cases 要求
- 生成 4-6 个测试用例，至少 2 个公开、2 个隐藏
- **你必须能对每个用例手动推演出正确答案**
- 隐藏用例应包含边界情况（最小输入、最大值、全相同元素等）

## 示例
当用户输入"出一道动态规划的题"时：
{{
  "suggested_id": 305,
  "title": "最长递增子序列",
  "description": "### 作业描述\\n给定一个整数序列，找到其中最长的严格递增子序列的长度。\\n\\n子序列是指从原序列中删除若干（可以为零）个元素后，剩余元素保持原有先后顺序所组成的序列。\\n\\n请使用动态规划方法求解此问题。\\n\\n### 输入格式\\n第一行包含一个正整数 n（1 ≤ n ≤ 1000），表示序列的长度。\\n第二行包含 n 个整数 a₁, a₂, ..., aₙ（-10000 ≤ aᵢ ≤ 10000），用空格分隔。\\n\\n### 输出格式\\n输出一个整数，表示最长严格递增子序列的长度。\\n\\n### 输入样例\\n```\\n8\\n10 9 2 5 3 7 101 18\\n```\\n\\n### 输出样例\\n```\\n4\\n```\\n\\n### 提示\\n最长递增子序列为 [2, 3, 7, 101] 或 [2, 5, 7, 101]，长度为 4。",
  "test_cases": [
    {{"input": "8\\n10 9 2 5 3 7 101 18", "output": "4", "is_public": true}},
    {{"input": "5\\n1 2 3 4 5", "output": "5", "is_public": true}},
    {{"input": "5\\n5 4 3 2 1", "output": "1", "is_public": false}},
    {{"input": "1\\n42", "output": "1", "is_public": false}},
    {{"input": "6\\n3 1 4 1 5 9", "output": "4", "is_public": false}}
  ]
}}

错误做法（绝对禁止）：自创"矩阵链乘的起始和结束位置"这种非标准输入格式。

现在请处理以下用户输入：
\"\"\"
{raw_text}
\"\"\""""
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            data = {
                "model": "glm-4.5-flash",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是一个严谨的编程作业出题专家。你的核心原则是：题目必须定义明确、无歧义，"
                            "任何合格的程序员看到题目后都能写出唯一正确的程序。"
                            "只出经典的、有标准解法的编程题（如两数之和、斐波那契、LIS、背包、排序、二叉树遍历等）。"
                            "绝对不要自创模糊的算法变体。"
                            "输入格式必须逐行精确定义数据类型和取值范围。"
                            "你必须能对每个测试用例手动推演出正确答案。"
                            "test_cases的input和output中绝对禁止出现省略号(...)、省略、以此类推等缩写，必须写出完整数据。"
                            "为确保数据完整，测试用例的输入规模要小（如n≤20）。"
                            "你必须且只能输出合法的 JSON，不得在 JSON 前后添加任何解释文字或 Markdown 代码块标记。"
                        )
                    },
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.4,
                "max_tokens": 3000,
                "stream": True
            }
            from services.llm_client import safe_zhipu_post
            response = safe_zhipu_post(
                "https://open.bigmodel.cn/api/paas/v4/chat/completions",
                headers=headers,
                json_data=data,
                timeout=90,
                stream=True
            )
            response.raise_for_status()

            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    if decoded_line.startswith('data:'):
                        json_str = decoded_line[len('data:'):].strip()
                        if json_str and json_str != '[DONE]':
                            try:
                                chunk = json.loads(json_str)
                                if chunk.get('choices'):
                                    content = chunk['choices'][0]['delta'].get('content', '')
                                    if content:
                                        yield content
                            except json.JSONDecodeError:
                                print(f"Skipping non-JSON SSE line: {json_str}")
                                continue
        except requests.exceptions.RequestException as e:
            print(f"API request failed: {e}")
            yield json.dumps({"error": f"API请求失败: {str(e)}"})
        except Exception as e:
            print(f"An exception occurred during streaming: {e}")
            yield json.dumps({"error": f"发生错误: {str(e)}"})

    def analyze_ability_trend(self, submissions: List[Dict]) -> Dict:
        """分析编程能力发展趋势"""
        if not submissions:
            return {
                "trend": "暂无数据",
                "improvement": "请提交更多代码以获取分析",
                "suggestions": []
            }
            
        prompt = f"""请分析以下代码提交记录，评估编程能力的发展趋势和改进建议：

提交记录：
{json.dumps(submissions, ensure_ascii=False, indent=2)}

重要提示：请严格按照JSON格式返回分析结果，不要添加任何其他文本或格式标记。

必须返回如下格式的JSON：
{{
  "trend": "能力发展趋势的详细描述",
  "improvement": "具体的改进建议",
  "suggestions": [
    "具体改进措施1",
    "具体改进措施2",
    "具体改进措施3"
  ]
}}

请确保返回的是纯JSON格式，不要包含markdown代码块标记或其他格式。
"""

        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            data = {
                "model": "glm-4.5-flash",
                "messages": [
                    {"role": "system", "content": "你是一个专业的编程教育专家，擅长分析学习趋势和提供改进建议。请严格按照JSON格式返回结果。"},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,
                "max_tokens": 2000
            }
            from services.llm_client import safe_zhipu_post
            response = safe_zhipu_post(
                "https://open.bigmodel.cn/api/paas/v4/chat/completions",
                headers=headers,
                json_data=data,
                timeout=30
            )
            if response.status_code == 200:
                result = response.json()
                print(f"🔍 完整API响应: {json.dumps(result, ensure_ascii=False, indent=2)}")
                if "choices" not in result or len(result["choices"]) == 0:
                    raise Exception("API响应格式错误：缺少choices字段")
                if "message" not in result["choices"][0]:
                    raise Exception("API响应格式错误：缺少message字段")
                message = result["choices"][0]["message"]
                result_content = message.get("content", "") or message.get("reasoning_content", "")
                print(f"📄 API返回内容长度: {len(result_content) if result_content else 0}")
                print(f"📄 API返回内容前200字符: {result_content[:200] if result_content else '(空内容)'}")
                if not result_content or not result_content.strip():
                    raise Exception("API返回空内容")
                if result["choices"][0].get("finish_reason") == "length":
                    reasoning_content = message.get("reasoning_content", "")
                    if reasoning_content:
                        return self._extract_from_natural_language(reasoning_content)
                content_trimmed = result_content.strip()
                if not content_trimmed.startswith('{'):
                    return self._extract_from_natural_language(content_trimmed)
                cleaned_content = content_trimmed
                if cleaned_content.startswith('```json'):
                    cleaned_content = cleaned_content[7:]
                    if cleaned_content.endswith('```'):
                        cleaned_content = cleaned_content[:-3]
                elif cleaned_content.startswith('```'):
                    lines = cleaned_content.split('\n')
                    if len(lines) > 1:
                        cleaned_content = '\n'.join(lines[1:])
                        if cleaned_content.endswith('```'):
                            cleaned_content = cleaned_content[:-3]
                cleaned_content = cleaned_content.strip()
                try:
                    result_dict = json.loads(cleaned_content)
                    if 'suggestions' in result_dict and isinstance(result_dict['suggestions'], list):
                        result_dict['suggestions'] = [self._clean_suggestion(s) for s in result_dict['suggestions']]
                    return result_dict
                except Exception as e:
                    json_match = re.search(r'({.*})', cleaned_content.replace('\n', ''), re.DOTALL)
                    if json_match:
                        try:
                            result_dict = json.loads(json_match.group(1))
                            if 'suggestions' in result_dict and isinstance(result_dict['suggestions'], list):
                                result_dict['suggestions'] = [self._clean_suggestion(s) for s in result_dict['suggestions']]
                            return result_dict
                        except Exception:
                            pass
                    return {
                        "trend": f"分析过程中出现解析错误: {str(e)[:100]}",
                        "improvement": "请检查API返回格式或稍后重试",
                        "suggestions": ["检查网络连接", "确认API密钥有效", "稍后重试"]
                    }
            else:
                print(f"智谱API请求失败: {response.status_code} - {response.text}")
                return {"trend": "分析过程中出现错误", "improvement": "请稍后重试", "suggestions": []}
        except Exception as e:
            print(f"能力趋势分析出错: {str(e)}")
            return {"trend": "分析过程中出现错误", "improvement": "请稍后重试", "suggestions": []}

    def _clean_suggestion(self, suggestion: str) -> str:
        """清理建议文本中的格式标记"""
        if not suggestion:
            return ""
        cleaned = re.sub(r'\{+[a-zA-Z0-9_]+\}+', '', suggestion)
        cleaned = re.sub(r'```[\s\S]*?```', '', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned
        
    def _extract_from_natural_language(self, content: str) -> Dict:
        """从自然语言响应中提取结构化信息"""
        try:
            trend_text = "从提交记录分析，编程能力呈现良好发展趋势"
            trend_patterns = [
                r'编程能力[呈现展示表明]*([^。]{20,80})',
                r'([^。]{10,80}趋势[^。]{5,40})',
                r'从[^。]{5,15}来看[^。]*([^。]{20,80})',
                r'学生[^。]*能力[^。]*([^。]{15,60})'
            ]
            for pattern in trend_patterns:
                matches = re.findall(pattern, content)
                if matches:
                    clean_matches = [m.strip() for m in matches[:2] if len(m.strip()) > 10]
                    if clean_matches:
                        trend_text = "从提交记录分析，" + "，".join(clean_matches)
                        break

            improvement_text = "建议继续加强基础算法练习，提高代码质量和规范性"
            improvement_patterns = [
                r'### 改进建议\s*([^#]{100,300})',
                r'改进建议[：:]\s*([^。]{50,150})',
                r'建议([^。]{30,100})',
                r'需要([^。]{20,80})'
            ]
            for pattern in improvement_patterns:
                matches = re.findall(pattern, content, re.DOTALL)
                if matches:
                    match_text = re.sub(r'\s+', ' ', matches[0].strip())
                    if len(match_text) > 20:
                        improvement_text = match_text[:200] + ("..." if len(match_text) > 200 else "")
                        break

            suggestions = []
            numbered_patterns = [
                r'\d+\.\s*\*\*([^*]+)\*\*[：:]?\s*([^。\n]{15,100})',
                r'\d+\.\s*([^。\n：:]{20,120})[。\n]',
            ]
            for pattern in numbered_patterns:
                matches = re.findall(pattern, content)
                if matches:
                    if isinstance(matches[0], tuple):
                        suggestions = [f"{m[0]}：{m[1]}" if len(m) > 1 and m[1] else m[0] for m in matches[:6]]
                    else:
                        suggestions = list(matches[:6])
                    suggestions = [s.strip() for s in suggestions if len(s.strip()) > 15]
                    if suggestions:
                        break

            if not suggestions:
                suggestion_keywords = ['可以', '应该', '尝试', '学习', '练习', '增加', '提高', '避免']
                for line in content.split('\n'):
                    line = line.strip()
                    if (any(kw in line for kw in suggestion_keywords) and
                            20 < len(line) < 150 and not line.startswith('#')):
                        suggestions.append(line)
                        if len(suggestions) >= 6:
                            break

            if not suggestions:
                suggestions = [
                    "加强基础算法练习，重点掌握排序和查找算法的原理和实现",
                    "提高代码提交的准确性，避免重复提交和错误提交",
                    "增加代码测试覆盖率，为每个算法编写完整的测试用例",
                    "学习算法优化技巧，关注时间和空间复杂度的改进",
                    "扩展数据结构知识，学习树、图等高级数据结构"
                ]

            return {"trend": trend_text, "improvement": improvement_text, "suggestions": suggestions[:8]}

        except Exception as e:
            print(f"❌ 从自然语言中提取信息失败: {e}")
            return {
                "trend": "AI分析显示您的编程能力正在稳步提升",
                "improvement": "建议继续保持良好的编程习惯，加强基础算法练习",
                "suggestions": [
                    "多练习基础算法，特别是排序和查找算法的变种实现",
                    "注重代码规范，提高变量命名和注释的质量",
                    "增加边界条件测试，确保代码在各种输入下的健壮性",
                    "学习算法复杂度分析，理解时间和空间效率的权衡",
                    "练习代码重构，提高代码的可维护性和可读性"
                ]
            }

    def analyze_ability_trend_stream(self, submissions: List[Dict]) -> Generator[str, None, None]:
        """流式分析编程能力发展趋势，使用SSE方式实时返回分析结果"""
        if not submissions:
            yield "### 暂无提交数据\n\n请提交更多代码以获取详细分析。"
            return

        prompt = f"""请分析以下代码提交记录，详细评估学生的编程能力发展趋势。

提交记录数量：{len(submissions)}条

提交详情：
{json.dumps(submissions[:10], ensure_ascii=False, indent=2)}

请从能力发展趋势、改进建议、具体行动措施三个方面进行深入分析。
用中文输出，语言简洁专业，直接输出分析内容，不要JSON格式。
"""
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            data = {
                "model": "glm-4.5-flash",
                "messages": [
                    {"role": "system", "content": "你是一个专业的编程教育专家，擅长分析学生的学习趋势和提供有针对性的改进建议。请用简洁专业的中文直接输出分析内容。"},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,
                "max_tokens": 2000,
                "stream": True
            }
            from services.llm_client import safe_zhipu_post
            response = safe_zhipu_post(
                "https://open.bigmodel.cn/api/paas/v4/chat/completions",
                headers=headers, json_data=data, stream=True, timeout=(10, 120)
            )
            if response.status_code == 200:
                chunk_count = 0
                for line in response.iter_lines():
                    if line:
                        line_str = line.decode('utf-8')
                        if line_str.startswith('data: '):
                            data_str = line_str[6:].strip()
                            if data_str == '[DONE]':
                                break
                            try:
                                chunk_data = json.loads(data_str)
                                if 'choices' in chunk_data and chunk_data['choices']:
                                    content = chunk_data['choices'][0].get('delta', {}).get('content', '')
                                    if content:
                                        chunk_count += 1
                                        yield content
                            except json.JSONDecodeError:
                                continue
            else:
                raise RuntimeError(
                    f"能力分析 API 请求失败: HTTP {response.status_code}"
                )
        except Exception as e:
            print(f"流式分析出错: {str(e)}")
            raise RuntimeError("能力分析 AI 服务调用失败") from e

    def detect_code_knowledge_points(self, code: str, assignment_title: str) -> List[Dict]:
        """使用AI自动检测代码涉及的C语言知识点"""
        prompt = f"""请分析以下C语言代码，识别其中涉及的主要知识点。

作业标题：{assignment_title}

代码：
```c
{code[:1000]}
```

请从以下知识点中选择最相关的3-5个：
basic_syntax, pointer, function, array, string, struct, file_io,
dynamic_memory, linked_list, tree, sorting, searching, recursion

对于每个知识点，评估 weight(0.5-2.0) 和 difficulty(0.5-2.0)。

请以JSON格式返回：
[
  {{"knowledge_point": "pointer", "weight": 1.5, "difficulty": 1.2}}
]
"""
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            data = {
                "model": "glm-4.5-flash",
                "messages": [
                    {"role": "system", "content": "你是一个C语言专家，擅长识别代码中的知识点。请严格按照JSON格式返回结果。"},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 500
            }
            from services.llm_client import safe_zhipu_post
            response = safe_zhipu_post(
                "https://open.bigmodel.cn/api/paas/v4/chat/completions",
                headers=headers, json_data=data, timeout=15
            )
            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content'].strip()
                if content.startswith('```json'):
                    content = content[7:]
                if content.startswith('```'):
                    content = content[3:]
                if content.endswith('```'):
                    content = content[:-3]
                return json.loads(content.strip())
            return []
        except Exception as e:
            print(f"知识点检测失败: {str(e)}")
            return self._infer_knowledge_points_from_title(assignment_title)

    def _infer_knowledge_points_from_title(self, title: str) -> List[Dict]:
        """基于标题关键词推断知识点"""
        title_lower = title.lower()
        keyword_map = {
            'pointer': ['指针', 'pointer', '*'],
            'array': ['数组', 'array', '[]'],
            'function': ['函数', 'function'],
            'string': ['字符串', 'string', 'str'],
            'struct': ['结构体', 'struct'],
            'linked_list': ['链表', 'list', '节点'],
            'tree': ['树', 'tree', '二叉'],
            'sorting': ['排序', 'sort'],
            'searching': ['查找', '搜索', 'search'],
            'recursion': ['递归', 'recursion'],
            'dynamic_memory': ['malloc', 'free', '动态'],
            'file_io': ['文件', 'file']
        }
        knowledge_points = []
        for kp, keywords in keyword_map.items():
            if any(kw in title_lower for kw in keywords):
                knowledge_points.append({'knowledge_point': kp, 'weight': 1.0, 'difficulty': 1.0})
        if not knowledge_points:
            knowledge_points.append({'knowledge_point': 'basic_syntax', 'weight': 1.0, 'difficulty': 1.0})
        return knowledge_points

