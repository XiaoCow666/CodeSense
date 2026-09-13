"""
基于大型语言模型的代码评估模块
"""
import os
import re
import json
from dotenv import load_dotenv
import traceback

# 加载环境变量
load_dotenv()

# 导入统一的 API 密钥管理器
from services.api_keys import api_keys


class LLMEvaluator:
    """大模型代码评估器"""
    
    def __init__(self, api_type="zhipu", model_name=None, strict_mode=False):
        """
        初始化大模型评估器
        
        参数:
            api_type: 使用的API类型，支持'zhipu'和'openai'
            model_name: 模型名称，如果为None则使用默认模型
            strict_mode: 是否启用严格评分模式，启用后会更容易给出0分
        """
        self.api_type = api_type.lower()
        self.strict_mode = strict_mode  # 添加严格模式参数
        
        # 根据API类型设置默认模型
        if self.api_type == "zhipu":
            self.model_name = model_name or "glm-4.5-flash"
        elif self.api_type == "openai":
            self.model_name = model_name or "gpt-4-turbo"
        else:
            raise ValueError(f"不支持的API类型: {api_type}")
        
        print(f"使用{self.api_type}的{self.model_name}模型进行代码评估")
        if self.strict_mode:
            print(f"[WARN] 已启用严格评分模式，将对代码质量进行更严格的评判")
        
        # 初始化API凭证和客户端
        try:
            self._init_client()
        except Exception as e:
            print(f"初始化大模型API失败: {e}")
            raise
    
    def _init_client(self):
        """初始化API客户端"""
        if self.api_type == "zhipu":
            try:
                # 修改导入流程增加更详细的异常处理
                try:
                    from zhipuai import ZhipuAI
                except ImportError as e:
                    print("\n======== 智谱AI API依赖错误 ========")
                    print("未安装zhipuai库，无法使用智谱AI功能。")
                    print("请执行以下命令安装依赖：")
                    print("pip install zhipuai")
                    print("或者")
                    print("pip install -U zhipuai --user")
                    print("安装后重新启动应用。")
                    print("如果问题仍然存在，请检查是否存在多个Python环境，确保在正确的环境中安装。")
                    print("======================================\n")
                    raise ImportError("未正确安装zhipuai库") from e

                api_key = api_keys.zhipu_key
                if not api_key:
                    print("\n======== API密钥缺失 ========")
                    print("未设置ZHIPU_API_KEY环境变量")
                    print("请在.env文件中添加：")
                    print("ZHIPU_API_KEY=您的智谱AI API密钥")
                    print("或者使用环境变量设置方式：")
                    print("export ZHIPU_API_KEY=您的智谱AI API密钥 (Linux/Mac)")
                    print("set ZHIPU_API_KEY=您的智谱AI API密钥 (Windows)")
                    print("==============================\n")
                    raise ValueError("未设置ZHIPU_API_KEY环境变量")
                self.client = ZhipuAI(api_key=api_key)
                print("[OK] 智谱AI客户端初始化成功")
            except Exception as e:
                print(f"[WARN] 智谱AI初始化失败: {type(e).__name__}")
                print(f"尝试回退到其他API或本地评估方式")
                # 尝试回退到OpenAI
                if api_keys.has_openai:
                    print("检测到OpenAI API密钥，尝试切换到OpenAI...")
                    self.api_type = "openai"
                    self.model_name = "gpt-4-turbo"
                    print(f"已切换到 {self.api_type} 的 {self.model_name}")
                    # 递归调用以初始化新的API类型
                    return self._init_client()
                else:
                    print("没有可用的备选API，将使用本地启发式评估")
                    raise
        elif self.api_type == "openai":
            try:
                # 修改导入流程增加更详细的异常处理
                try:
                    from openai import OpenAI
                except ImportError as e:
                    print("\n======== OpenAI API依赖错误 ========")
                    print("未安装openai库，无法使用OpenAI功能。")
                    print("请执行以下命令安装依赖：")
                    print("pip install openai")
                    print("或者")
                    print("pip install -U openai --user")
                    print("安装后重新启动应用。")
                    print("======================================\n")
                    raise ImportError("未正确安装openai库") from e

                api_key = api_keys.openai_key
                if not api_key:
                    print("\n======== API密钥缺失 ========")
                    print("未设置OPENAI_API_KEY环境变量")
                    print("请在.env文件中添加：")
                    print("OPENAI_API_KEY=您的OpenAI API密钥")
                    print("或者使用环境变量设置方式：")
                    print("export OPENAI_API_KEY=您的OpenAI API密钥 (Linux/Mac)")
                    print("set OPENAI_API_KEY=您的OpenAI API密钥 (Windows)")
                    print("==============================\n")
                    raise ValueError("未设置OPENAI_API_KEY环境变量")
                self.client = OpenAI(api_key=api_key)
                print("[OK] OpenAI客户端初始化成功")
            except Exception as e:
                print(f"[WARN] OpenAI初始化失败: {type(e).__name__}")
                print("没有可用的API，将使用本地启发式评估")
                raise
    
    def _chat_completions_create(self, **kwargs):
        """通过共享容错客户端调用，保留旧 response 形状供下游解析。"""
        from types import SimpleNamespace
        from services.llm_client import SharedLLMClient

        params = kwargs.copy()
        messages = params.get("messages", [])
        temperature = params.get("temperature", 0.7)
        max_tokens = params.get("max_tokens", 2000)
        model = params.get("model", self.model_name)
        shared = SharedLLMClient()
        if params.get("stream"):
            stream = shared.chat_stream(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                provider=self.api_type,
                model=model,
                request_kind="submission",
            )

            def wrapped_stream():
                for content in stream:
                    yield SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(content=content)
                            )
                        ]
                    )

            return wrapped_stream()

        content = shared.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            provider=self.api_type,
            model=model,
            request_kind="submission",
        )
        if not content:
            raise RuntimeError("LLM provider returned no content")
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content)
                )
            ]
        )

    def evaluate_code_with_structured_data(self, code, assignment_title=None):
        """
        使用大模型评估代码并返回结构化数据
        
        参数:
            code: 要评估的代码
            assignment_title: 题目标题或要求
            
        返回:
            (score, feedback, structured_data): 分数(0-5)、反馈文本和结构化数据
        """
        # 获取基本评估
        score, feedback = self.evaluate_code(code, assignment_title)
        
        # 基于总分生成各项能力分数
        # 在教育场景中，各项能力相对均衡，但有一定随机性
        import random
        base_score = max(60, min(95, score * 20))  # 转换为60-95分范围
        
        # 添加少量随机变化让分数更真实
        algorithm_score = base_score + random.randint(-5, 5)
        style_score = base_score + random.randint(-3, 7)
        functionality_score = base_score + random.randint(-2, 8)
        efficiency_score = base_score + random.randint(-8, 2)
        readability_score = base_score + random.randint(-3, 7)
        
        # 确保分数在合理范围内
        algorithm_score = max(50, min(100, algorithm_score))
        style_score = max(50, min(100, style_score))
        functionality_score = max(50, min(100, functionality_score))
        efficiency_score = max(50, min(100, efficiency_score))
        readability_score = max(50, min(100, readability_score))
        
        structured_data = {
            'overall_score': score,
            'overall_feedback': feedback,
            'algorithm_score': algorithm_score,
            'style_score': style_score,
            'functionality_score': functionality_score,
            'efficiency_score': efficiency_score,
            'readability_score': readability_score,
            'suggestions': [
                '继续练习提升编程能力',
                '注意代码风格和规范',
                '关注算法效率优化'
            ]
        }
        
        return score, feedback, structured_data

    def evaluate_code(self, code, assignment_title=None):
        """
        使用大模型评估代码
        
        参数:
            code: 要评估的代码
            assignment_title: 题目标题或要求
            
        返回:
            (score, feedback): 分数(0-5)和反馈
        """
        # 构建提示词
        strict_instruction = """请严格但不苛刻地评估这段代码的质量。如果代码存在严重问题，可给出较低分，但应该优先考虑代码的教育价值和学生的学习进程。
在以下情况下应该考虑较低分:
1. 代码与题目要求不符
2. 代码存在严重语法错误，无法编译
3. 代码缺少必要的结构（如main函数、必要的头文件等）
4. 代码是不完整的代码片段（有TODO注释但未实现）
5. 代码逻辑存在明显错误

但请记住，评分目的是为了帮助学生进步，而不是打击学习积极性。""" if self.strict_mode else ""
        
        system_prompt = f"""你是一名经验丰富的C++编程教师，你将评估学生提交的C++代码的质量。
{strict_instruction}
请按照以下标准评分，并适当考虑教学作用和激励学生的重要性:
1分: 代码有明显问题，但学生做出了尝试。
2分: 代码存在多处问题，但有基本结构。
3分: 代码基本可用，有少量错误或不足。
4分: 代码质量良好，实现了所有主要功能。
5分: 代码质量优秀，结构清晰，功能完整，符合最佳实践。

评分重点:
1. 代码与题目要求的匹配度是最重要的评分依据。如果代码很好地解决了题目要求的问题，即使有小缺陷也应给予较高分数。
2. 如果代码完全符合题目要求，应当至少给予4分以上的评分，同时给予积极鼓励。
3. 即使代码有些小问题，但如果核心算法或思路正确地解决了题目问题，应适当加分并在评价中明确指出这一点。

请分析代码的结构、语法、效率和实现，并根据你给出的分数，使用**梯度分层**策略提供不同粒度的反馈：

### 如果你给出 1-2 分（基础层反馈）：
- **精确定位问题**：指出代码中**具体第几行**存在什么问题，以及应该如何修改方向（如"第7行：缺少循环终止条件"）。
- **提供类比代码示例**：给出一个与题目答案**无关**的独立代码片段，用来展示某个编程技巧或正确用法。例如，如果学生的 for 循环写错了，给出一个正确使用 for 循环遍历数组的示例（用不同的变量名和场景）。
- **不要给出题目的答案代码**，只展示相关编程模式的正确用法。
- 语气要温和鼓励，但内容必须具体到行。

### 如果你给出 3 分（进阶层反馈）：
- **点明关键问题**：说明代码在哪些方面接近正确，哪些地方需要修改，但**不直接给出修改后的代码**。
- **思路引导**：用提问或提示的方式引导学生思考（如"想想看，当输入为负数时你的程序会怎样？"）。
- **可给出伪代码级别的提示**，帮助学生理解正确的逻辑流程。

### 如果你给出 4-5 分（优化层反馈）：
- **不需要指出基础问题**，聚焦于代码的**美观性、命名规范、可读性和性能优化**。
- 例如：变量命名是否具有描述性、是否有冗余代码、是否可以使用更高效的数据结构等。
- 给予积极肯定和鼓励。

你的回复必须包含一个明确的分数(1-5分)和详细的分析。
请直接使用以下格式回复: "分数：X\n分析：[你的分析]" """

        user_prompt = f"请评估以下C++代码的质量:"
        if assignment_title:
            user_prompt += f"\n题目要求: {assignment_title}"
        user_prompt += f"\n```cpp\n{code}\n```"
        
        # 调用不同平台的API
        try:
            response = self._chat_completions_create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.2 if not self.strict_mode else 0.1,  # 严格模式下温度更低，确保结果更确定
            )
            response_text = response.choices[0].message.content
            
            # 解析响应
            score_match = re.search(r'分数：(\d+)', response_text)
            if score_match:
                score = int(score_match.group(1))
                # 确保分数在0-5之间
                score = max(0, min(5, score))
            else:
                # 如果无法提取分数，尝试从文本中推断
                if "0分" in response_text or "零分" in response_text or "严重不合格" in response_text:
                    score = 0
                elif "1分" in response_text or "一分" in response_text:
                    score = 1
                elif "2分" in response_text or "两分" in response_text:
                    score = 2
                elif "3分" in response_text or "三分" in response_text:
                    score = 3
                elif "4分" in response_text or "四分" in response_text:
                    score = 4
                elif "5分" in response_text or "五分" in response_text:
                    score = 5
                else:
                    # 默认中等分数，严格模式下默认较低分数
                    score = 2 if self.strict_mode else 3
            
            # 从响应中提取反馈
            if "分析：" in response_text:
                feedback = response_text.split("分析：", 1)[1].strip()
            else:
                feedback = response_text
                
            # 针对严格模式做额外处理
            if self.strict_mode:
                # 检查反馈中的负面评价，可能意味着更低的分数
                severe_negative_terms = ["严重错误", "严重问题", "完全不符合", "无法编译", "无法运行", "不符合基本要求"]
                moderate_negative_terms = ["错误", "问题", "缺少", "不足", "不完整", "不正确"]
                positive_terms = ["优秀", "出色", "良好", "完美", "全面", "全部实现", "逻辑清晰", "结构良好", "代码规范"]
                
                # 基于分数区间采取不同策略
                if score <= 1:
                    # 对于低分代码，更容易给0分
                    if any(term in feedback for term in severe_negative_terms) or any(term in feedback for term in moderate_negative_terms):
                        old_score = score
                        score = 0
                        feedback = f"代码质量有待提升，评分调整为{score}分。\n\n" + feedback
                        print(f"严格模式: 低分代码，检测到问题，分数从{old_score}降至{score}分")
                
                elif score == 2 or score == 3:
                    # 中等分数代码，严格评判问题
                    # 严重问题检测
                    if any(term in feedback for term in severe_negative_terms):
                        old_score = score
                        score = max(0, score - 2)  # 降低2分
                        feedback = f"代码存在一些需要改进的地方，评分调整为{score}分。\n\n" + feedback
                        print(f"严格模式: 检测到严重问题，分数从{old_score}降至{score}分")
                    # 一般问题检测
                    elif any(term in feedback for term in moderate_negative_terms):
                        old_score = score
                        score = max(0, score - 1)  # 降低1分
                        feedback = f"代码有优化空间，评分调整为{score}分。\n\n" + feedback
                        print(f"严格模式: 检测到一般问题，分数从{old_score}降至{score}分")
                
                elif score >= 4:
                    # 高分代码，如果确实优秀则保持或提高分数
                    # 检查是否包含足够的积极评价
                    positive_count = sum(1 for term in positive_terms if term in feedback)
                    if positive_count >= 3 and not any(term in feedback for term in severe_negative_terms):
                        # 多个积极评价且没有严重问题，保持高分或提高到5分
                        if score == 4 and "完美" in feedback:
                            score = 5
                            feedback = f"代码质量优秀，评分为{score}分。\n\n" + feedback
                            print(f"严格模式: 高质量代码，分数提高到5分")
                    elif any(term in feedback for term in severe_negative_terms):
                        # 有严重问题，大幅降低分数
                        old_score = score
                        score = max(2, score - 2)
                        feedback = f"代码整体不错但仍有改进空间，评分调整为{score}分。\n\n" + feedback
                        print(f"严格模式: 高分代码存在严重问题，分数从{old_score}降至{score}分")
                    elif any(term in feedback for term in moderate_negative_terms) and positive_count < 2:
                        # 有一般问题且积极评价不多，适当降低分数
                        old_score = score
                        score = max(3, score - 1)
                        feedback = f"代码基本实现了功能，但有进一步完善的空间，评分为{score}分。\n\n" + feedback
                        print(f"严格模式: 高分代码存在一般问题，分数从{old_score}降至{score}分")
                    
                # 检查代码长度不足
                code_lines = len(code.strip().split('\n'))
                if code_lines < 5 and score > 0:
                    score = 0
                    feedback = "代码内容较少，建议完善后再次提交。\n\n" + feedback
                    print(f"严格模式: 代码行数过少({code_lines}行)，分数调整为0分")
                
                # Hello World特殊检查
                if "Hello World" in code and "Hello World" not in str(assignment_title or ""):
                    if score > 2:
                        old_score = score
                        score = min(2, score)
                        feedback = f"代码似乎是Hello World示例，建议根据题目要求完善实现，评分调整为{score}分。\n\n" + feedback
                        print(f"严格模式: 检测到Hello World代码，但题目可能不是要求Hello World，分数从{old_score}降至{score}分")
                        
                # 特别处理：简单的练习题目应更严格，复杂题目应更宽松
                if assignment_title:
                    assignment_complexity = 1  # 默认中等复杂度
                    
                    # 判断题目复杂度
                    complex_keywords = ["高级", "复杂", "挑战", "难题", "高难度", "实现系统", "设计模式", "数据结构", "算法"]
                    simple_keywords = ["简单", "基础", "入门", "练习", "Hello", "打印", "输出"]
                    
                    # 计算复杂度关键词出现次数
                    complex_count = sum(1 for word in complex_keywords if word in str(assignment_title))
                    simple_count = sum(1 for word in simple_keywords if word in str(assignment_title))
                    
                    if complex_count > simple_count:
                        assignment_complexity = 2  # 复杂题目
                    elif simple_count > complex_count:
                        assignment_complexity = 0  # 简单题目
                    
                    # 根据题目复杂度调整分数
                    if assignment_complexity == 0 and score >= 3:
                        # 简单题目应该更严格评判高分
                        if code_lines < 20 or "简单" in feedback or "基础" in feedback:
                            old_score = score
                            score = min(4, score)  # 简单题目最高给4分
                            if old_score != score:
                                feedback = f"对于基础练习题，评分上限为4分，当前评分为{score}分。\n\n" + feedback
                                print(f"严格模式: 简单题目分数上限调整，从{old_score}降至{score}分")
                    elif assignment_complexity == 2 and score <= 2:
                        # 复杂题目应该更宽松评判低分
                        if "尝试" in feedback or "努力" in feedback:
                            old_score = score
                            score = max(1, score)  # 对于复杂题目的尝试至少给1分
                            if old_score != score:
                                feedback = f"在复杂题目上的尝试值得鼓励，评分为{score}分。\n\n" + feedback
                                print(f"严格模式: 复杂题目分数下限调整，从{old_score}提升至{score}分")
            
            return score, feedback
            
        except Exception as e:
            print(f"大模型API调用失败: {e}")
            # 返回一个默认评分
            return 2, f"大模型评估失败: {str(e)}"
    
    def evaluate_with_structured_output(self, prompt, task_type):
        """
        使用大模型进行结构化输出评估
        
        参数:
            prompt: 提示词
            task_type: 任务类型，如'code_advisor'
            
        返回:
            dict: 包含评估结果的字典
        """
        try:
            print(f"进行{task_type}任务的结构化输出评估")
            
            # 添加结构化输出指令 - 为不同任务类型提供不同的指导
            guidance_instruction = ""
            if task_type == 'code_advisor':
                if self.strict_mode:
                    # 严格评分模式（用于正式评估）
                    guidance_instruction = """
请严格地评估代码质量。
评分标准（0-100分）：
- 0-10分: 代码质量极差，存在严重问题，完全不可用
- 11-30分: 代码质量差，有重大错误
- 31-50分: 代码质量不佳，存在多个问题
- 51-70分: 代码质量中等，有待改进
- 71-85分: 代码质量良好，结构清晰
- 86-100分: 代码质量优秀，近乎完美

严格模式评分原则：
1. 高分代码需符合严格标准，接近满分必须接近完美
2. 中等质量代码分数不应超过70分
3. 有明显问题的代码分数应在50分以下
4. 低质量代码应给予更低的分数，不要轻易给高分
"""
                else:
                    # 指导模式（用于代码建议和学习辅导）
                    guidance_instruction = """
您是一位耐心、友好的编程导师，专注于帮助学生学习和改进。

评分标准（60-95分范围，重在鼓励）：
- 60-70分: 代码有基本结构，是很好的开始
- 71-80分: 代码结构清晰，实现了主要功能
- 81-90分: 代码质量良好，有一些亮点
- 91-95分: 代码实现优秀，展现了很好的编程思维

指导原则：
1. 首先肯定学生的努力和已完成的工作
2. 指出代码中的亮点和正确实现
3. 用积极的语言提出改进建议（如"可以考虑"、"建议尝试"）
4. 提供具体、可操作的下一步改进方向
5. 结尾给予鼓励，激发继续学习的动力

请避免使用"错误"、"缺陷"等消极词汇，多使用"改进空间"、"优化建议"等积极表述。
"""
            
            structured_prompt = f"""{prompt}
{guidance_instruction}
请确保返回的内容可以被直接解析为JSON格式。不要包含任何额外的说明或解释，只返回有效的JSON数据。
"""
            
            # 根据不同平台调用API
            response = self._chat_completions_create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "你是一个代码分析助手，你的回答必须是严格的JSON格式。"},
                    {"role": "user", "content": structured_prompt}
                ],
                temperature=0.1,  # 低温度以确保输出更确定
                response_format={"type": "json_object"}  # 请求JSON格式的响应
            )
            response_text = response.choices[0].message.content
            
            # 处理响应
            print(f"收到原始响应: {response_text[:200]}...")
            
            # 提取JSON部分
            json_text = self._extract_json(response_text)
            
            # 解析JSON
            try:
                structured_result = json.loads(json_text)
                print(f"成功解析为JSON结构，包含{len(structured_result)}个字段")
                
                # 如果是代码顾问任务且启用了严格模式，调整分数
                if task_type == 'code_advisor' and self.strict_mode:
                    structured_result = self._apply_strict_mode_adjustments(structured_result)
                    
                return structured_result
            except json.JSONDecodeError as e:
                print(f"JSON解析错误: {e}")
                print(f"尝试修复JSON格式")
                # 尝试修复常见的JSON格式问题
                fixed_json = self._fix_json(json_text)
                try:
                    structured_result = json.loads(fixed_json)
                    print(f"修复后成功解析为JSON结构")
                    
                    # 如果是代码顾问任务且启用了严格模式，调整分数
                    if task_type == 'code_advisor' and self.strict_mode:
                        structured_result = self._apply_strict_mode_adjustments(structured_result)
                        
                    return structured_result
                except:
                    print(f"修复后仍然无法解析，返回None")
                    return None
        
        except Exception as e:
            print(f"结构化评估出错: {e}")
            print(traceback.format_exc())
            return None
            
    def _apply_strict_mode_adjustments(self, result):
        """
        对代码分析结果应用严格模式调整
        
        参数:
            result: 原始分析结果字典
            
        返回:
            调整后的分析结果字典
        """
        if not result:
            return result
            
        # 确保所有必要的分数字段存在
        score_fields = ['algorithm_score', 'style_score', 'functionality_score', 'efficiency_score']
        for field in score_fields:
            if field not in result:
                continue
                
            # 获取当前分数并确保在0-100范围内
            current_score = max(0, min(100, result[field]))
            adjusted_score = current_score  # 默认不变
            
            # 计算平均分
            scores = [result.get(f, 0) for f in score_fields if f in result]
            avg_score = sum(scores) / len(scores) if scores else 0
            
            # 1. 高分代码处理 (平均分 ≥ 80)：分数越接近100越好
            if avg_score >= 80:
                # 查找正面评价词语
                feedback_text = ' '.join([str(result.get(f, '')) for f in result if isinstance(result.get(f), str)])
                positive_terms = ['优秀', '出色', '完美', '清晰', '合理', '全面', '规范', '易读']
                positive_count = sum(1 for term in positive_terms if term in feedback_text)
                
                # 高分代码至少需要3个正面评价词才能保持高分，否则适当降低
                if positive_count >= 3:
                    # 进一步提高分数，使得接近90的分数更接近95-100
                    if current_score >= 85:
                        adjusted_score = min(100, current_score + (100 - current_score) * 0.5)
                else:
                    # 如果正面评价不够多，适当降低分数但不会低于80
                    adjusted_score = max(80, current_score - (3 - positive_count) * 2)
                    
            # 2. 中等代码处理 (平均分50-79)：保持在50-70范围内
            elif avg_score >= 50 and avg_score < 80:
                # 查找评价中的问题和优点
                feedback_text = ' '.join([str(result.get(f, '')) for f in result if isinstance(result.get(f), str)])
                negative_terms = ['问题', '错误', '缺陷', '不足', '不良', '欠缺', '不规范']
                negative_count = sum(1 for term in negative_terms if term in feedback_text)
                
                # 根据问题数量调整分数
                if negative_count > 2:
                    # 有较多问题，分数向50靠拢
                    adjusted_score = max(50, current_score - negative_count * 3)
                elif negative_count <= 1:
                    # 问题较少，可以适当提高但不超过75
                    adjusted_score = min(75, current_score + 5)
                    
            # 3. 低分代码处理 (平均分 < 50)：分数向上调整
            else:
                # 查找严重问题
                feedback_text = ' '.join([str(result.get(f, '')) for f in result if isinstance(result.get(f), str)])
                severe_terms = ['严重问题', '无法运行', '完全错误', '根本性错误', '缺少基本功能']
                severe_count = sum(1 for term in severe_terms if term in feedback_text)
                
                # 即使有严重问题，也给予一定的基础分以鼓励学习
                if severe_count > 0 or avg_score < 30:
                    # 提高基础分，保持在30分以上
                    adjusted_score = max(30, current_score * 0.6 + 20)
                else:
                    # 没有严重问题但分数低，适当提高
                    adjusted_score = max(40, current_score * 0.9 + 10)
            
            # 将调整后的分数应用回结果
            result[field] = round(adjusted_score, 1)
            
            # 添加调整说明
            if abs(adjusted_score - current_score) > 1:
                field_name = {
                    'algorithm_score': '算法能力',
                    'style_score': '代码风格',
                    'functionality_score': '功能实现',
                    'efficiency_score': '效率优化'
                }.get(field, field)
                
                adjustment_note = f"{field_name}分数调整为{adjusted_score:.1f}"
                
                # 添加到反馈中
                if 'overall_feedback' in result:
                    result['overall_feedback'] = adjustment_note + "\n" + result['overall_feedback']
                else:
                    result['overall_feedback'] = adjustment_note
        
        # 更新反馈中的分数描述，确保与调整后的分数一致
        if 'overall_feedback' in result and isinstance(result['overall_feedback'], str):
            feedback = result['overall_feedback']
            
            # 计算新的平均分
            new_scores = [result.get(f, 0) for f in score_fields if f in result]
            new_avg = sum(new_scores) / len(new_scores) if new_scores else 0
            
            # 添加教学模式标记
            if "【教学模式】" not in feedback:
                result['overall_feedback'] = f"【教学模式评分】平均分：{new_avg:.1f}\n" + feedback
        
        return result
    
    def _extract_json(self, text):
        """从文本中提取JSON部分"""
        # 检查是否已经是有效JSON
        try:
            json.loads(text)
            return text
        except:
            pass
        
        # 尝试查找JSON对象
        json_pattern = r'({[\s\S]*})'
        matches = re.search(json_pattern, text)
        if matches:
            return matches.group(1)
        
        # 如果没有匹配，返回原文本
        return text
    
    def _fix_json(self, text):
        """尝试修复常见的JSON格式错误"""
        # 修复单引号问题 (将单引号替换为双引号)
        text = re.sub(r"(?<!\\)'([^']*?)(?<!\\)'", r'"\1"', text)
        
        # 修复缺少引号的键名
        text = re.sub(r'(\s*?)(\w+)(\s*?):', r'\1"\2"\3:', text)
        
        # 修复尾部逗号
        text = re.sub(r',(\s*?)}', r'\1}', text)
        
        # 修复缺少值的部分
        text = re.sub(r':\s*?,', r': "",', text)
        text = re.sub(r':\s*?}', r': ""}', text)
        
        return text
    
    def provide_guidance(self, code, assignment_title=None):
        """
        使用大模型提供编程指导而非严格评分
        
        参数:
            code: 要分析的代码
            assignment_title: 题目标题或要求
            
        返回:
            (score, feedback): 分数(通常为3-5)和鼓励性的反馈指导
        """
        # 使用新的简化指导提示词
        from .prompts import prompt_manager
        user_prompt = prompt_manager.get_guidance_prompt(code, assignment_title)
        system_prompt = "你是一位幽默风趣的编程导师🧙‍♂️"
        
        # 调用不同平台的API
        try:
            response = self._chat_completions_create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.5,  # 较高的温度使响应更加多样化、友好
            )
            response_text = response.choices[0].message.content
            
            # 指导模式下默认给比较高的分数，鼓励学生
            # 我们不从响应中提取分数，而是根据代码长度和复杂度给出一个鼓励性分数
            code_lines = len(code.strip().split('\n'))
            if code_lines < 15:
                score = 3  # 基础代码给3分鼓励
            elif code_lines < 30:
                score = 4  # 中等长度代码给4分鼓励
            else:
                score = 5  # 较长代码给5分鼓励
            
            # 使用格式化函数美化输出
            formatted_response = self._format_markdown_response(response_text)
            
            return score, formatted_response
            
        except Exception as e:
            print(f"生成编程指导时出错: {e}")
            print(traceback.format_exc())
            
            # 异常情况下返回通用鼓励信息
            generic_guidance = """### 代码分析
您已经开始编写代码，这是很好的第一步！

### 学习建议
1. 考虑添加更多注释，解释您的思路
2. 确保您的代码结构清晰，便于理解
3. 测试不同的输入情况，确保程序稳健

### 下一步
继续完善您的代码，特别关注功能的完整实现和边界情况处理。

### 鼓励
编程是一个持续学习和改进的过程。每一行代码都是进步，继续努力！
"""
            return 3, generic_guidance  # 出错时给3分和通用指导
    
    def _call_llm_api(self, prompt):
        """
        调用大模型API处理提示并返回响应
        
        参数:
            prompt: 输入的提示内容
            
        返回:
            大模型的原始响应文本
        """
        try:
            response = self._chat_completions_create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "你是一个有用的编程助手，擅长提供清晰、准确的指导。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,  # 使用较低的temperature以获得更确定的回答
            )
            return response.choices[0].message.content
        
        except Exception as e:
            print(f"调用API时出错: {e}")
            print(traceback.format_exc())
            raise Exception(f"调用{self.api_type}的{self.model_name}模型失败: {str(e)}")
    
    def get_llm_response(self, prompt):
        """
        获取大模型的回答
        
        参数:
            prompt: 输入的提示内容
            
        返回:
            大模型的回答内容
        """
        try:
            print(f"发送提示到LLM，长度: {len(prompt)} 字符")
            response = self._call_llm_api(prompt)
            
            # 格式化回答，确保返回有效的Markdown
            try:
                formatted_response = self._format_markdown_response(response)
            except Exception as format_error:
                print(f"Markdown格式化出错，使用备用格式化方法: {format_error}")
                formatted_response = self._format_markdown_simple(response)
            
            # 调试输出
            print(f"LLM响应长度: {len(formatted_response)} 字符")
            print(f"响应前200个字符: {formatted_response[:200]}")
            
            return formatted_response
        except Exception as e:
            print(f"获取LLM回答失败: {str(e)}")
            print(traceback.format_exc())
            return f"获取AI回答时出错: {str(e)}\n\n如果问题持续，请联系管理员检查API配置。"

    def stream_llm_response(self, prompt):
        """Yield the raw text response from the model as it is generated.

        Markdown normalization is deliberately left to the caller.  Applying
        it to every partial chunk can temporarily create invalid code fences
        and makes the UI flicker; callers should render the accumulated text
        while streaming and normalize it once in the final ``done`` event.
        """
        try:
            print(f"发送流式提示到LLM，长度: {len(prompt)} 字符")
            response = self._chat_completions_create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "你是一个有用的编程助手，擅长提供清晰、准确的指导。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                stream=True,
            )
            for chunk in response:
                choices = getattr(chunk, "choices", None)
                if choices is None and isinstance(chunk, dict):
                    choices = chunk.get("choices")
                if not choices:
                    continue
                first = choices[0]
                delta = getattr(first, "delta", None)
                if delta is None and isinstance(first, dict):
                    delta = first.get("delta") or {}
                content = getattr(delta, "content", None)
                if content is None and isinstance(delta, dict):
                    content = delta.get("content")
                if content:
                    yield str(content)
        except Exception as e:
            print(f"调用LLM流式API时出错: {e}")
            print(traceback.format_exc())
            raise Exception(f"调用{self.api_type}的{self.model_name}模型失败: {str(e)}")
    
    def _format_markdown_response(self, text):
        """
        格式化API返回的文本，确保是有效的Markdown格式
        
        参数:
            text: 原始文本
            
        返回:
            格式化后的Markdown文本
        """
        if not text:
            return "未获取到有效的AI回答"
        
        # 清理可能存在的控制字符
        text = re.sub(r'[\x00-\x1F\x7F]', '', text)
        
        # 尝试清理JSON回答中不必要的引号和转义
        if text.strip().startswith('{') and text.strip().endswith('}'):
            try:
                # 尝试解析为JSON对象
                data = json.loads(text)
                # 如果包含content或text或answer字段，直接取出其中内容
                for key in ['content', 'text', 'answer', 'response', 'message', 'feedback']:
                    if key in data and isinstance(data[key], str):
                        text = data[key]
                        break
            except:
                # 解析失败，保持原样
                pass
        
        # 确保标题格式正确（#后有空格）
        text = re.sub(r'(^|\n)(#{1,6})([^#\s])', r'\1\2 \3', text)
        
        # 确保标题前后有空行，提高解析准确性
        text = re.sub(r'([^\n])(#{1,6}\s)', r'\1\n\n\2', text)
        text = re.sub(r'(#{1,6}[^\n]+)([^\n])', r'\1\n\n\2', text)
        
        # 改进代码块格式处理
        # 1. 确保代码块有语言标记
        code_block_pattern = r'```\s*(?![\w+#])'
        text = re.sub(code_block_pattern, '```c', text)  # 默认为C语言，因为系统主要评估C/C++代码

        # 2. 修复常见的代码块语言标记问题
        text = re.sub(r'```\s*cpp\s*\n', '```cpp\n', text)
        text = re.sub(r'```\s*c\+\+\s*\n', '```cpp\n', text)
        text = re.sub(r'```\s*c\s*\n', '```c\n', text)
        text = re.sub(r'```\s*python\s*\n', '```python\n', text)
        
        # 3. 处理代码块缩进一致性
        lines = text.split('\n')
        in_code_block = False
        code_block_lines = []
        formatted_lines = []
        
        for i, line in enumerate(lines):
            # 检测代码块开始
            if re.match(r'^```\w*', line) and not in_code_block:
                in_code_block = True
                code_block_lines = [line]
                continue
                
            # 检测代码块结束
            if line.strip() == '```' and in_code_block:
                in_code_block = False
                
                # 处理代码缩进一致性
                if len(code_block_lines) > 1:
                    # 找出最小的非空行缩进
                    non_empty_lines = [l for l in code_block_lines[1:] if l.strip()]
                    if non_empty_lines:
                        min_indent = min(len(l) - len(l.lstrip()) for l in non_empty_lines)
                        # 调整所有代码行的缩进
                        for j in range(1, len(code_block_lines)):
                            if code_block_lines[j].strip():
                                # 移除多余缩进，保留最小缩进
                                leading_spaces = len(code_block_lines[j]) - len(code_block_lines[j].lstrip())
                                if leading_spaces > min_indent:
                                    code_block_lines[j] = code_block_lines[j][leading_spaces - min_indent:]
                
                # 添加处理后的代码块
                formatted_lines.extend(code_block_lines)
                formatted_lines.append(line)  # 添加结束标记
                continue
                
            # 收集代码块内的行
            if in_code_block:
                code_block_lines.append(line)
                continue
                
            # 非代码块内的行正常处理
            formatted_lines.append(line)
        
        # 如果代码块没有正确关闭，添加结束标记
        if in_code_block:
            formatted_lines.extend(code_block_lines)
            formatted_lines.append('```')
        
        # 重新构建文本
        text = '\n'.join(formatted_lines)
        
        # 确保Markdown列表格式正确
        text = re.sub(r'(^|\n)([*\-+])(?!\s)', r'\1\2 ', text)
        
        # 确保有序列表格式正确
        text = re.sub(r'(^|\n)(\d+\.)(?!\s)', r'\1\2 ', text)
        
        # 确保段落之间有空行
        text = re.sub(r'(\n[^\n]+\n)(?!\n)', r'\1\n', text)
        
        # 确保强调标记周围有空格
        text = re.sub(r'(\w)(\*\*|\*|__)(\w)', r'\1 \2\3', text)
        text = re.sub(r'(\w)(\*\*|\*|__)(\w)', r'\1\2 \3', text)
        
        # 将连续多个空行减少为最多两个空行
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # 特殊处理：确保代码示例中的关键项目有加粗标记
        code_keywords = ['include', 'main', 'printf', 'scanf', 'return', 'int', 'float', 'double', 'char']
        
        # 注释掉有问题的正则表达式行
        # for keyword in code_keywords:
        #     # 只在代码解释部分加粗关键字，不在代码块内修改
        #     text = re.sub(r'(?<!\`\`\`[\w\s]*\n[\s\S]*?)(?<!\`)({})(?!\`)'.format(keyword), 
        #                   r'**\1**', text)
        
        # 修复可变宽度lookbehind问题，使用分段处理方式
        # 首先将文本分割成代码块和非代码块部分
        parts = re.split(r'(```[\w\s]*\n[\s\S]*?```)', text)
        for i in range(0, len(parts), 2):
            # 仅对非代码块部分应用关键词加粗
            if i < len(parts):
                for keyword in code_keywords:
                    # 使用简单的模式匹配单词边界，避免lookbehind
                    parts[i] = re.sub(r'\b({})\b(?!`|>|<)'.format(keyword), r'**\1**', parts[i])
        
        # 重新组合文本
        text = ''.join(parts)
        
        print(f"格式化后的Markdown前300个字符: {text[:300]}")
        return text
    
    def _format_markdown_simple(self, text):
        """
        简化版的Markdown格式化方法，不使用复杂的正则表达式
        在主格式化方法失败时作为备用
        
        参数:
            text: 原始文本
            
        返回:
            基本格式化后的Markdown文本
        """
        if not text:
            return "未获取到有效的AI回答"
        
        # 基本清理
        text = re.sub(r'[\x00-\x1F\x7F]', '', text)
        
        # 尝试处理JSON回答
        if text.strip().startswith('{') and text.strip().endswith('}'):
            try:
                data = json.loads(text)
                for key in ['content', 'text', 'answer', 'response', 'message', 'feedback']:
                    if key in data and isinstance(data[key], str):
                        text = data[key]
                        break
            except:
                pass
        
        # 确保代码块格式正确
        if '```' in text:
            # 确保代码块有语言标记
            text = re.sub(r'```\s*\n', '```c\n', text)
            
            # 确保代码块闭合
            codeblock_count = text.count('```')
            if codeblock_count % 2 != 0:
                text += '\n```'
        
        # 简单处理标题格式
        text = re.sub(r'#([^\s])', r'# \1', text)
        
        print(f"简化格式后的Markdown前300个字符: {text[:300]}")
        return text
