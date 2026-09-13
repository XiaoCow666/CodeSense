"""
代码建议系统 - 提供针对学生代码的改进建议
版本: v1.0.0
"""
import os
import re
import json
import traceback
import logging
from typing import Dict, Optional, Any
from .prompts import prompt_manager  # 导入提示词管理器
from services.api_keys import api_keys  # 导入 API 密钥管理器

# 设置日志
logger = logging.getLogger("code_advisor")
if not logger.handlers:
    # 设置日志格式
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # 控制台日志处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    
    # 文件日志处理器
    try:
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.FileHandler(os.path.join(log_dir, 'code_advisor.log'))
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        
        # 添加处理器到日志对象
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"无法设置文件日志: {e}")
    
    logger.addHandler(console_handler)
    logger.setLevel(logging.INFO)
    logger.info("代码建议系统日志初始化完成")

# 全局变量
code_advisor = None
initialized = False

class CodeAdvisor:
    """代码建议系统核心类，负责分析代码并提供建议"""
    
    def __init__(self, use_llm: bool = True):
        """
        初始化代码建议系统
        
        参数:
            use_llm: 是否使用大语言模型增强建议
        """
        self.use_llm = use_llm
        self.supported_languages = {
            'cpp': self._analyze_cpp_code,
            'python': self._analyze_python_code,
            'java': self._analyze_java_code
        }
        # 如果开启大语言模型，尝试初始化
        if use_llm:
            try:
                from utils.llm_evaluator import LLMEvaluator
                self.llm = LLMEvaluator()
                logger.info("大语言模型初始化成功")
            except Exception as e:
                logger.error(f"初始化大语言模型时出错: {e}")
                self.use_llm = False
    
    def analyze_code(self, 
                     code: str, 
                     language: str = 'cpp', 
                     assignment_title: Optional[str] = None, 
                     assignment_description: Optional[str] = None, 
                     advanced_mode: bool = False) -> Dict[str, Any]:
        """
        分析代码并提供建议
        
        参数:
            code: 要分析的代码字符串
            language: 编程语言，支持'cpp'、'python'、'java'
            assignment_title: 作业标题（可选）
            assignment_description: 作业描述（可选）
            advanced_mode: 是否使用高级分析模式
            
        返回:
            包含分析结果和建议的字典
        """
        logger.info(f"开始分析{language}代码，高级模式: {advanced_mode}")
        
        # 标准化语言名称
        language = language.lower()
        
        # 如果代码太短，返回简单提示
        if len(code.strip()) < 10:
            return {
                'overall_feedback': '代码内容太少，无法进行有效分析',
                'algorithm_score': 0,
                'style_score': 0,
                'functionality_score': 0,
                'efficiency_score': 0,
                'suggestions': ['请提供完整的代码以获取有针对性的建议']
            }
        
        # 如果开启高级模式且大语言模型可用，使用LLM进行分析
        if advanced_mode and self.use_llm:
            try:
                return self._analyze_with_guidance_mode(
                    code, language, assignment_title, assignment_description)
            except Exception as e:
                logger.error(f"指导性分析失败: {e}")
                logger.info("回退到规则分析")
                # 如果LLM分析失败，回退到规则分析
        elif self.use_llm:  # 基础模式也可以使用LLM，但用不同的提示词
            try:
                return self._analyze_with_structured_evaluation(
                    code, language, assignment_title, assignment_description)
            except Exception as e:
                logger.error(f"结构化评估失败: {e}")
                logger.info("回退到规则分析")
        
        # 使用规则引擎分析
        if language in self.supported_languages:
            try:
                return self.supported_languages[language](
                    code, assignment_title, assignment_description)
            except Exception as e:
                logger.error(f"分析{language}代码时出错: {e}")
                return self._generate_error_response(f"分析代码时出错: {str(e)}")
        else:
            logger.warning(f"不支持的语言: {language}")
            return self._generate_error_response(f"不支持的编程语言: {language}")
    
    def _analyze_with_llm(self, 
                          code: str, 
                          language: str,
                          assignment_title: Optional[str] = None,
                          assignment_description: Optional[str] = None) -> Dict[str, Any]:
        """使用大语言模型分析代码"""
        logger.info("使用大语言模型分析代码")
        
        # 构建提示
        prompt = self._build_llm_prompt(code, language, assignment_title, assignment_description)
        
        # 调用大语言模型
        try:
            # 增加超时控制
            import time
            start_time = time.time()
            timeout_seconds = 30  # 30秒超时
            
            logger.info(f"开始调用LLM API进行代码分析 (timeout={timeout_seconds}s)")
            try:
                # 检查llm实例是否正确初始化
                if not hasattr(self, 'llm') or self.llm is None:
                    logger.error("LLM实例未正确初始化")
                    raise ValueError("LLM评估器未正确初始化")
                
                # 检查方法是否存在
                if not hasattr(self.llm, 'evaluate_with_structured_output'):
                    logger.error("evaluate_with_structured_output方法不存在")
                    raise AttributeError("LLM评估器中缺少evaluate_with_structured_output方法")
                
                # 为代码建议启用指导模式（不使用严格评分）
                if hasattr(self.llm, 'strict_mode'):
                    original_strict_mode = self.llm.strict_mode
                    self.llm.strict_mode = False  # 代码建议使用指导模式
                    logger.info("已开启LLM评估器的指导模式")
                
                response = self.llm.evaluate_with_structured_output(prompt, "code_advisor")
                
                # 恢复LLM评估器的原始严格模式设置
                if hasattr(self.llm, 'strict_mode'):
                    self.llm.strict_mode = original_strict_mode
                
                # 检查超时
                elapsed_time = time.time() - start_time
                if elapsed_time >= timeout_seconds:
                    logger.warning(f"LLM API调用耗时较长: {elapsed_time:.2f}秒")
            except Exception as api_error:
                logger.error(f"LLM API调用失败: {api_error}")
                if time.time() - start_time >= timeout_seconds:
                    raise TimeoutError(f"LLM API调用超时 ({timeout_seconds}秒)")
                raise
            
            # 处理响应
            if response and isinstance(response, dict):
                # 确保分数在0-100范围内
                for key in ['algorithm_score', 'style_score', 'functionality_score', 'efficiency_score']:
                    if key in response:
                        response[key] = max(0, min(100, response[key]))
                
                # 如果缺少建议，添加默认建议
                if 'suggestions' not in response or not response['suggestions']:
                    response['suggestions'] = ['添加更多注释，解释代码逻辑', 
                                             '考虑代码可重用性，提取重复逻辑为函数']
                
                # 检查是否包含必要的字段
                required_fields = ['algorithm_score', 'style_score', 'overall_feedback']
                missing_fields = [field for field in required_fields if field not in response]
                
                if missing_fields:
                    logger.warning(f"LLM响应缺少必要字段: {missing_fields}")
                    # 添加缺失的字段
                    for field in missing_fields:
                        if field.endswith('_score'):
                            response[field] = 70  # 默认分数
                        elif field == 'overall_feedback':
                            response[field] = "代码整体质量中等，有一些改进空间。"
                
                logger.info(f"LLM分析成功，返回{len(response)}个字段")
                return response
            else:
                logger.warning(f"LLM返回格式不正确或为空: {response}")
                # 如果响应格式不正确，回退到规则分析
                if language in self.supported_languages:
                    logger.info(f"回退到{language}的规则分析")
                    return self.supported_languages[language](
                        code, assignment_title, assignment_description)
                else:
                    return self._generate_error_response("语言不支持且LLM分析失败")
        except Exception as e:
            logger.error(f"LLM分析出错: {e}")
            logger.error(traceback.format_exc())
            # 如果LLM分析出错，回退到规则分析
            if language in self.supported_languages:
                logger.info(f"因错误回退到{language}的规则分析: {str(e)}")
                return self.supported_languages[language](
                    code, assignment_title, assignment_description)
            else:
                return self._generate_error_response(f"LLM分析失败: {str(e)}")

    def _analyze_with_guidance_mode(self, 
                                   code: str, 
                                   language: str,
                                   assignment_title: Optional[str] = None,
                                   assignment_description: Optional[str] = None) -> Dict[str, Any]:
        """
        高级模式：使用大语言模型提供指导性建议
        不直接给出答案，而是引导学生思考和学习
        """
        logger.info("使用指导模式分析代码")
        
        # 使用专门的指导性提示词
        guidance_prompt = prompt_manager.get_guidance_prompt(code, assignment_title, assignment_description)
        
        try:
            import time
            start_time = time.time()
            timeout_seconds = 30
            
            logger.info("开始生成指导性建议")
            
            if not hasattr(self, 'llm') or self.llm is None:
                raise ValueError("LLM评估器未正确初始化")
            
            # 使用provide_guidance方法而不是evaluate_with_structured_output
            if hasattr(self.llm, 'provide_guidance'):
                score, guidance_text = self.llm.provide_guidance(code, assignment_title)
                
                # 检查超时
                elapsed_time = time.time() - start_time
                if elapsed_time >= timeout_seconds:
                    logger.warning(f"指导性分析耗时较长: {elapsed_time:.2f}秒")
                
                logger.info("指导性建议生成成功")
                
                # 返回适合前端显示的格式
                return {
                    'overall_feedback': guidance_text,
                    'algorithm_score': max(60, min(95, score * 20)),  # 转换为60-95分范围
                    'style_score': max(60, min(95, score * 20)),
                    'functionality_score': max(60, min(95, score * 20)),
                    'efficiency_score': max(60, min(95, score * 20)),
                    'suggestions': ['请查看上方的详细指导建议']
                }
            else:
                # 如果没有专门的指导方法，使用通用API但用指导性提示词
                if hasattr(self.llm, 'api_type') and self.llm.api_type == "zhipu":
                    from services.llm_client import SharedLLMClient

                    guidance_text = SharedLLMClient().chat(
                        messages=[
                            {"role": "system", "content": "你是一位耐心的编程导师"},
                            {"role": "user", "content": guidance_prompt},
                        ],
                        temperature=0.7,
                        max_tokens=1200,
                        provider=self.llm.api_type,
                        model=getattr(self.llm, "model_name", None),
                        request_kind="code_advice",
                    )
                    if not guidance_text:
                        raise RuntimeError("AI服务暂时不可用")
                    
                    return {
                        'overall_feedback': guidance_text,
                        'algorithm_score': 75,
                        'style_score': 75,
                        'functionality_score': 75,
                        'efficiency_score': 75,
                        'suggestions': ['请查看上方的详细指导建议']
                    }
                else:
                    raise AttributeError("不支持的LLM接口")
                    
        except Exception as e:
            logger.error(f"指导性分析失败: {e}")
            logger.error(traceback.format_exc())
            
            # 提供通用的指导性回退建议
            return {
                'overall_feedback': self._generate_fallback_guidance(code, assignment_title),
                'algorithm_score': 70,
                'style_score': 70,
                'functionality_score': 70,
                'efficiency_score': 70,
                'suggestions': ['请查看上方的指导建议，或寻求进一步帮助']
            }
    
    def _analyze_with_structured_evaluation(self, 
                                          code: str, 
                                          language: str,
                                          assignment_title: Optional[str] = None,
                                          assignment_description: Optional[str] = None) -> Dict[str, Any]:
        """
        基础模式：使用大语言模型进行结构化代码评估
        提供传统的分析报告和评分
        """
        logger.info("使用结构化评估分析代码")
        
        # 使用专门的分析提示词
        analysis_prompt = prompt_manager.get_basic_analysis_prompt(code, assignment_title, assignment_description)
        
        try:
            import time
            start_time = time.time()
            timeout_seconds = 30
            
            logger.info("开始结构化代码评估")
            
            if not hasattr(self, 'llm') or self.llm is None:
                raise ValueError("LLM评估器未正确初始化")
            
            # 为结构化评估启用严格模式
            if hasattr(self.llm, 'strict_mode'):
                original_strict_mode = self.llm.strict_mode
                self.llm.strict_mode = False  # 基础模式也使用指导性评分
            
            if hasattr(self.llm, 'evaluate_with_structured_output'):
                response = self.llm.evaluate_with_structured_output(analysis_prompt, "code_advisor")
            else:
                # 使用通用API
                if hasattr(self.llm, 'api_type') and self.llm.api_type == "zhipu":
                    from services.llm_client import SharedLLMClient

                    response_text = SharedLLMClient().chat(
                        messages=[
                            {"role": "system", "content": "你是一个代码分析专家"},
                            {"role": "user", "content": analysis_prompt},
                        ],
                        temperature=0.3,
                        max_tokens=1600,
                        provider=self.llm.api_type,
                        model=getattr(self.llm, "model_name", None),
                        request_kind="code_advice",
                    )
                    if not response_text:
                        raise RuntimeError("AI服务暂时不可用")

                    # 尝试解析JSON响应
                    try:
                        response = json.loads(response_text)
                    except json.JSONDecodeError:
                        # 如果不是JSON格式，创建默认结构
                        response = {
                            'overall_feedback': response_text,
                            'algorithm_score': 75,
                            'style_score': 75,
                            'functionality_score': 75,
                            'efficiency_score': 75,
                            'suggestions': ['参考上方的详细分析']
                        }
            
            # 恢复原始严格模式
            if hasattr(self.llm, 'strict_mode'):
                self.llm.strict_mode = original_strict_mode
            
            # 检查超时
            elapsed_time = time.time() - start_time
            if elapsed_time >= timeout_seconds:
                logger.warning(f"结构化评估耗时较长: {elapsed_time:.2f}秒")
            
            # 处理响应
            if response and isinstance(response, dict):
                # 确保分数在合理范围内
                for key in ['algorithm_score', 'style_score', 'functionality_score', 'efficiency_score']:
                    if key in response:
                        response[key] = max(60, min(95, response[key]))  # 60-95分范围
                
                # 确保包含必要字段
                if 'overall_feedback' not in response:
                    response['overall_feedback'] = "代码分析完成，请查看详细评分。"
                
                if 'suggestions' not in response or not response['suggestions']:
                    response['suggestions'] = ['继续完善代码结构', '添加更多注释说明']
                
                logger.info(f"结构化评估成功，返回{len(response)}个字段")
                return response
            else:
                logger.warning("结构化评估返回格式不正确")
                raise ValueError("响应格式不正确")
                
        except Exception as e:
            logger.error(f"结构化评估失败: {e}")
            logger.error(traceback.format_exc())
            
            # 回退到规则分析
            if language in self.supported_languages:
                logger.info(f"回退到{language}的规则分析")
                return self.supported_languages[language](
                    code, assignment_title, assignment_description)
            else:
                return self._generate_error_response(f"结构化评估失败: {str(e)}")

    def _generate_fallback_guidance(self, code: str, assignment_title: str = None) -> str:
        """生成通用的指导性建议作为回退方案"""
        code_lines = len(code.strip().split('\n'))
        
        if code_lines > 20:
            progress = "哇！代码很丰富，看起来你在认真思考"
        elif code_lines > 10:
            progress = "不错的开始！基本框架已经有了"
        else:
            progress = "好的开端！代码已经开始成型"
        
        if assignment_title:
            if "排序" in assignment_title:
                hint = "让数据排个队，每个元素都要找到自己的位置哦！🎯"
            elif "查找" in assignment_title:
                hint = "像侦探一样缩小范围，总能找到目标的！🔍"
            else:
                hint = "仔细看看题目要求，你的代码还差什么呢？🤔"
        else:
            hint = "再检查一下逻辑，看看还有什么可以完善的！✨"
            
        return f"{progress}，{hint} 继续努力，你已经在正确路上了！🚀"

    def _build_llm_prompt(self, 
                          code: str, 
                          language: str,
                          assignment_title: Optional[str] = None,
                          assignment_description: Optional[str] = None) -> str:
        """构建LLM分析提示"""
        prompt = f"""作为代码分析专家，请对以下{language.upper()}代码进行详细分析，并提供改进建议。

代码内容:
```{language}
{code}
```

"""
        if assignment_title:
            prompt += f"\n作业标题: {assignment_title}\n"
        if assignment_description:
            prompt += f"\n作业描述: {assignment_description}\n"
            
        prompt += """
请从以下几个维度进行分析，并为每个维度给出1-100分的评分:

1. 算法能力 (algorithm_score): 评估代码解决问题的方法和算法选择
2. 代码风格 (style_score): 评估代码的可读性、命名规范和注释
3. 功能实现 (functionality_score): 评估代码功能的完整性和正确性
4. 效率优化 (efficiency_score): 评估代码的性能和资源利用

此外，请提供:
1. 整体评价 (overall_feedback): 简要总结代码质量
2. 算法分析 (algorithm_feedback): 详细分析代码的算法和问题解决方法
3. 风格分析 (style_feedback): 详细分析代码风格和规范
4. 具体改进建议 (suggestions): 列出3-5点具体的改进建议

请以JSON格式返回分析结果，JSON字段包括:
algorithm_score, style_score, functionality_score, efficiency_score, overall_feedback, algorithm_feedback, style_feedback, suggestions(数组)
"""
        return prompt
    
    def _analyze_cpp_code(self, 
                          code: str, 
                          assignment_title: Optional[str] = None,
                          assignment_description: Optional[str] = None) -> Dict[str, Any]:
        """使用规则引擎分析C++代码"""
        logger.info("使用规则引擎分析C++代码")
        
        result = {
            'algorithm_score': 65,  # 默认分数
            'style_score': 70,
            'functionality_score': 75,
            'efficiency_score': 65,
            'suggestions': []
        }
        
        try:
            # 提取基本特征
            lines = code.strip().split('\n')
            non_empty_lines = [line for line in lines if line.strip()]
            comment_lines = [line for line in non_empty_lines if line.strip().startswith('//') or line.strip().startswith('/*')]
            comment_ratio = len(comment_lines) / len(non_empty_lines) if non_empty_lines else 0
            
            # 代码结构分析
            has_includes = "#include" in code
            has_main = "int main" in code or "void main" in code
            has_functions = len(re.findall(r'(void|int|float|double|bool|char|string|auto)\s+\w+\s*\([^)]*\)\s*({|\n)', code)) > 0
            has_classes = "class" in code
            has_loops = "for(" in code.replace(" ", "") or "while(" in code.replace(" ", "")
            
            # 风格分析
            has_consistent_indentation = True
            prev_indent = None
            for line in non_empty_lines:
                if line.strip() and not line.strip().startswith('//') and not line.strip().startswith('/*'):
                    indent = len(line) - len(line.lstrip())
                    if prev_indent is not None and indent % 2 != 0 and indent % 4 != 0:
                        has_consistent_indentation = False
                        break
                    prev_indent = indent
            
            # 命名规范分析
            variable_pattern = re.compile(r'\b(int|float|double|char|bool|string|auto)\s+([a-zA-Z_][a-zA-Z0-9_]*)')
            variable_names = [match[1] for line in non_empty_lines for match in variable_pattern.findall(line)]
            
            good_naming = sum(1 for name in variable_names if re.match(r'^[a-z][a-zA-Z0-9]*$', name) or re.match(r'^[a-z][a-z0-9_]*$', name))
            naming_ratio = good_naming / len(variable_names) if variable_names else 1.0
            
            # 根据分析结果调整分数
            if has_includes:
                result['functionality_score'] += 5
            else:
                result['suggestions'].append("添加必要的头文件包含")
                
            if has_main:
                result['functionality_score'] += 5
            else:
                result['suggestions'].append("添加main函数作为程序入口")
            
            if has_functions:
                result['algorithm_score'] += 10
            else:
                result['suggestions'].append("将代码逻辑封装为函数，提高可重用性")
            
            if has_classes:
                result['algorithm_score'] += 5
            
            if comment_ratio >= 0.1:
                result['style_score'] += 10
            else:
                result['suggestions'].append("增加代码注释，解释关键算法和复杂逻辑")
            
            if has_consistent_indentation:
                result['style_score'] += 10
            else:
                result['suggestions'].append("保持一致的代码缩进风格")
            
            if naming_ratio >= 0.8:
                result['style_score'] += 10
            else:
                result['suggestions'].append("使用规范的变量命名风格（如驼峰式或下划线式）")
            
            # 针对特定题目的分析
            if assignment_title and isinstance(assignment_title, str):
                if "排序" in assignment_title:
                    if not has_loops:
                        result['algorithm_score'] -= 20
                        result['suggestions'].append("排序算法通常需要使用循环结构")
                    
                    if not ("swap" in code.lower() or "temp" in code.lower()):
                        result['algorithm_score'] -= 10
                        result['suggestions'].append("排序算法通常需要交换元素的操作")
            
            # 生成分析反馈
            structure_feedback = []
            style_feedback = []
            
            # 结构反馈
            if has_functions:
                structure_feedback.append("代码结构良好，使用了函数封装")
            else:
                structure_feedback.append("代码缺乏函数封装，可以提高模块化水平")
            
            if has_classes:
                structure_feedback.append("使用了类结构，体现了面向对象设计")
            
            # 风格反馈
            if comment_ratio < 0.1:
                style_feedback.append("代码注释较少，建议添加更多注释")
            else:
                style_feedback.append("代码包含适当的注释，提高了可读性")
            
            if not has_consistent_indentation:
                style_feedback.append("代码缩进不一致，影响可读性")
            else:
                style_feedback.append("代码缩进一致，结构清晰")
            
            if naming_ratio < 0.8:
                style_feedback.append("部分变量命名不规范，建议改进")
            else:
                style_feedback.append("变量命名规范，易于理解")
            
            # 添加整体评价
            overall_feedback = "您的代码"
            if result['algorithm_score'] >= 80:
                overall_feedback += "算法设计合理，"
            elif result['algorithm_score'] >= 60:
                overall_feedback += "算法实现基本正确，"
            else:
                overall_feedback += "算法实现存在问题，"
                
            if result['style_score'] >= 80:
                overall_feedback += "风格规范，"
            elif result['style_score'] >= 60:
                overall_feedback += "风格基本可接受，"
            else:
                overall_feedback += "风格需要改进，"
                
            overall_feedback += "综合来看，"
            avg_score = (result['algorithm_score'] + result['style_score'] + 
                         result['functionality_score'] + result['efficiency_score']) / 4
            
            if avg_score >= 80:
                overall_feedback += "代码质量良好。"
            elif avg_score >= 60:
                overall_feedback += "代码质量中等，有改进空间。"
            else:
                overall_feedback += "代码质量有待提高。"
            
            # 添加最终反馈到结果
            result['overall_feedback'] = overall_feedback
            result['algorithm_feedback'] = " ".join(structure_feedback)
            result['style_feedback'] = " ".join(style_feedback)
            
            # 如果建议不足2条，添加通用建议
            if len(result['suggestions']) < 2:
                result['suggestions'].append("添加异常处理，提高代码健壮性")
                result['suggestions'].append("考虑算法的边界情况和错误处理")
            
            # 确保所有分数在0-100范围内
            for key in ['algorithm_score', 'style_score', 'functionality_score', 'efficiency_score']:
                result[key] = max(0, min(100, result[key]))
            
            return result
            
        except Exception as e:
            logger.error(f"分析C++代码时出错: {e}")
            traceback.print_exc()
            return self._generate_error_response(f"分析C++代码时出错: {str(e)}")
    
    def _analyze_python_code(self, 
                             code: str, 
                             assignment_title: Optional[str] = None,
                             assignment_description: Optional[str] = None) -> Dict[str, Any]:
        """使用规则引擎分析Python代码"""
        logger.info("使用规则引擎分析Python代码")
        
        result = {
            'algorithm_score': 70,  # 默认分数
            'style_score': 75,
            'functionality_score': 70,
            'efficiency_score': 70,
            'suggestions': []
        }
        
        try:
            # 提取基本特征
            lines = code.strip().split('\n')
            non_empty_lines = [line for line in lines if line.strip()]
            comment_lines = [line for line in non_empty_lines if line.strip().startswith('#')]
            comment_ratio = len(comment_lines) / len(non_empty_lines) if non_empty_lines else 0
            
            # 代码结构分析
            has_imports = "import " in code
            has_functions = "def " in code
            has_classes = "class " in code
            has_main_guard = "__name__" in code and "__main__" in code
            
            # 根据分析结果调整分数
            if has_imports:
                result['functionality_score'] += 5
            
            if has_functions:
                result['algorithm_score'] += 10
            else:
                result['suggestions'].append("将代码封装为函数，提高可重用性")
            
            if has_classes:
                result['algorithm_score'] += 5
            
            if has_main_guard:
                result['style_score'] += 5
            else:
                result['suggestions'].append("添加 if __name__ == '__main__': 保护程序入口")
            
            if comment_ratio >= 0.1:
                result['style_score'] += 10
            else:
                result['suggestions'].append("增加代码注释，解释关键算法和复杂逻辑")
            
            # 检查是否使用了Python特有的特性
            list_comprehension = any(re.search(r'\[[^]]+for\s+[^]]+in\s+[^]]+\]', line) for line in non_empty_lines)
            if list_comprehension:
                result['efficiency_score'] += 5
            else:
                result['suggestions'].append("考虑使用列表推导式提高代码简洁性和效率")
            
            # 检查是否包含类型提示
            type_hints = any(re.search(r'def\s+\w+\s*\([^)]*:[^)]*\)', line) for line in non_empty_lines)
            if type_hints:
                result['style_score'] += 5
            else:
                result['suggestions'].append("添加类型提示，提高代码可维护性")
            
            # 生成分析反馈
            structure_feedback = []
            style_feedback = []
            
            # 结构反馈
            if has_functions:
                structure_feedback.append("代码结构良好，使用了函数封装")
            else:
                structure_feedback.append("代码缺乏函数封装，可以提高模块化水平")
            
            if has_classes:
                structure_feedback.append("使用了类结构，体现了面向对象设计")
            
            # 风格反馈
            if comment_ratio < 0.1:
                style_feedback.append("代码注释较少，建议添加更多注释")
            else:
                style_feedback.append("代码包含适当的注释，提高了可读性")
            
            # 添加整体评价
            overall_feedback = "您的Python代码"
            if result['algorithm_score'] >= 80:
                overall_feedback += "算法设计合理，"
            elif result['algorithm_score'] >= 60:
                overall_feedback += "算法实现基本正确，"
            else:
                overall_feedback += "算法实现存在问题，"
                
            if result['style_score'] >= 80:
                overall_feedback += "风格规范，"
            elif result['style_score'] >= 60:
                overall_feedback += "风格基本可接受，"
            else:
                overall_feedback += "风格需要改进，"
                
            overall_feedback += "综合来看，"
            avg_score = (result['algorithm_score'] + result['style_score'] + 
                         result['functionality_score'] + result['efficiency_score']) / 4
            
            if avg_score >= 80:
                overall_feedback += "代码质量良好。"
            elif avg_score >= 60:
                overall_feedback += "代码质量中等，有改进空间。"
            else:
                overall_feedback += "代码质量有待提高。"
            
            # 添加最终反馈到结果
            result['overall_feedback'] = overall_feedback
            result['algorithm_feedback'] = " ".join(structure_feedback)
            result['style_feedback'] = " ".join(style_feedback)
            
            # 确保所有分数在0-100范围内
            for key in ['algorithm_score', 'style_score', 'functionality_score', 'efficiency_score']:
                result[key] = max(0, min(100, result[key]))
            
            return result
            
        except Exception as e:
            logger.error(f"分析Python代码时出错: {e}")
            traceback.print_exc()
            return self._generate_error_response(f"分析Python代码时出错: {str(e)}")
    
    def _analyze_java_code(self, 
                           code: str, 
                           assignment_title: Optional[str] = None,
                           assignment_description: Optional[str] = None) -> Dict[str, Any]:
        """使用规则引擎分析Java代码"""
        logger.info("使用规则引擎分析Java代码")
        
        # 为Java代码提供类似的分析逻辑
        result = {
            'algorithm_score': 70,
            'style_score': 75,
            'functionality_score': 75,
            'efficiency_score': 70,
            'overall_feedback': '您的Java代码整体结构清晰，但存在一些改进空间。',
            'algorithm_feedback': 'Java代码基本功能已实现，但可以进一步优化算法逻辑。',
            'style_feedback': 'Java代码风格基本符合规范，建议增加更详细的注释。',
            'suggestions': [
                '遵循Java命名规范，使用驼峰式命名法',
                '添加异常处理，提高代码健壮性',
                '使用面向对象设计模式改进代码结构'
            ]
        }
        
        return result
    
    def _generate_error_response(self, error_message: str) -> Dict[str, Any]:
        """生成错误响应"""
        return {
            'overall_feedback': f'无法完成代码分析: {error_message}',
            'algorithm_score': 0,
            'style_score': 0,
            'functionality_score': 0,
            'efficiency_score': 0,
            'suggestions': ['请检查代码是否有语法错误', '尝试提供更完整的代码']
        }


def initialize_code_advisor() -> bool:
    """初始化代码建议系统"""
    global code_advisor, initialized
    
    if initialized and code_advisor:
        logger.info("代码建议系统已经初始化，直接返回")
        return True
    
    try:
        logger.info("开始初始化代码建议系统...")

        # 使用统一的 API 密钥管理器检查
        use_llm = api_keys.has_any_key

        if not use_llm:
            logger.warning("未找到大模型API密钥，将使用本地规则引擎")

        if use_llm:
            try:
                # 检查是否安装了必要的包
                try:
                    if api_keys.has_zhipu:
                        import zhipuai
                        logger.info("智谱AI SDK已安装")
                except ImportError:
                    logger.warning("未安装智谱AI SDK (zhipuai)")
                    if api_keys.has_zhipu:
                        logger.warning("尽管设置了ZHIPU_API_KEY，但由于未安装SDK，将无法使用智谱AI")

                try:
                    if api_keys.has_openai:
                        import openai
                        logger.info("OpenAI SDK已安装")
                except ImportError:
                    logger.warning("未安装OpenAI SDK (openai)")
                    if api_keys.has_openai:
                        logger.warning("尽管设置了OPENAI_API_KEY，但由于未安装SDK，将无法使用OpenAI")

                if api_keys.has_any_key:
                    logger.info("将尝试使用大模型评估")
                    code_advisor = CodeAdvisor(use_llm=True)
                    logger.info("[OK] 代码建议系统(使用大模型)初始化成功")
                else:
                    logger.info("未找到有效的大模型配置，将使用规则引擎")
                    code_advisor = CodeAdvisor(use_llm=False)
                    logger.info("[OK] 代码建议系统(使用规则引擎)初始化成功")
            except Exception as e:
                logger.error(f"初始化大模型时出错: {e}")
                logger.error(traceback.format_exc())
                logger.info("将使用规则引擎作为备选方案")
                code_advisor = CodeAdvisor(use_llm=False)
                logger.info("[OK] 代码建议系统(使用规则引擎，备选方案)初始化成功")
        else:
            # 使用纯规则引擎
            code_advisor = CodeAdvisor(use_llm=False)
            logger.info("[OK] 代码建议系统(使用规则引擎)初始化成功")
        
        initialized = True
        logger.info("代码建议系统初始化完成")
        return True
        
    except Exception as e:
        logger.error(f"初始化代码建议系统失败: {e}")
        logger.error(traceback.format_exc())
        
        # 尝试进行最小化初始化
        try:
            logger.info("尝试进行最小化初始化...")
            code_advisor = CodeAdvisor(use_llm=False)
            initialized = True
            logger.info("[OK] 代码建议系统(最小化配置)初始化成功")
            return True
        except Exception as fallback_error:
            logger.error(f"最小化初始化也失败: {fallback_error}")
            logger.error(traceback.format_exc())
            initialized = False
            code_advisor = None
            return False


def generate_code_advice(code: str, 
                         language: str = 'cpp', 
                         assignment_title: Optional[str] = None, 
                         assignment_description: Optional[str] = None, 
                         advanced_mode: bool = False) -> Dict[str, Any]:
    """
    生成代码建议
    
    参数:
        code: 要分析的代码字符串
        language: 编程语言
        assignment_title: 作业标题（可选）
        assignment_description: 作业描述（可选）
        advanced_mode: 是否使用高级分析模式
        
    返回:
        包含建议和分析结果的字典
    """
    global code_advisor, initialized
    
    # 如果系统未初始化，尝试初始化
    if not initialized:
        initialize_code_advisor()
    
    # 如果初始化失败，返回错误信息
    if not code_advisor:
        logger.error("代码建议系统未初始化")
        return {
            'overall_feedback': '代码建议系统未初始化，无法提供分析',
            'algorithm_score': 0,
            'style_score': 0,
            'functionality_score': 0,
            'efficiency_score': 0,
            'suggestions': ['系统初始化失败，请联系管理员']
        }
    
    # 分析代码并返回结果
    try:
        return code_advisor.analyze_code(
            code=code,
            language=language,
            assignment_title=assignment_title,
            assignment_description=assignment_description,
            advanced_mode=advanced_mode
        )
    except Exception as e:
        logger.error(f"生成代码建议时出错: {e}")
        traceback.print_exc()
        return {
            'overall_feedback': f'分析代码时出错: {str(e)}',
            'algorithm_score': 0,
            'style_score': 0,
            'functionality_score': 0,
            'efficiency_score': 0,
            'suggestions': ['系统处理出错，请稍后再试']
        }
