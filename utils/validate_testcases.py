"""
测试用例验证器
在 AI 生成作业后，自动生成多套解题代码并通过沙箱验证测试用例的正确性。
"""
import json
import logging
from typing import List, Dict

from utils.sandbox_runner import run_test_cases

logger = logging.getLogger(__name__)


def _generate_solution_code(description: str, solution_index: int, api_key: str, error_feedback: str = "") -> str:
    """
    调用 AI 生成一套 C++ 解题代码。
    solution_index 用于引导 AI 生成不同风格的代码。
    """
    style_hints = [
        "请使用简洁直接的实现方式，优先使用标准库函数。",
        "请使用详细、带注释的实现方式，变量命名清晰易懂。",
        "请使用高效的实现方式，注意边界条件处理。",
    ]
    style = style_hints[solution_index % len(style_hints)]

    base_prompt = f"""你是一位C++编程专家。请根据以下题目描述，编写一个完整的、可编译运行的 C++ 解题程序。

{style}

## 重要要求
1. 程序必须通过 stdin 读取输入，通过 stdout 输出结果
2. 必须包含 `#include` 和 `int main()` 
3. 只输出纯 C++ 代码，不要输出任何解释文字、Markdown 标记或代码块标记（如 ```）
4. 确保程序能处理题目中描述的所有边界情况。如果遇到题目未定义输出的边界异常情况（如空队列出队等），请务必防御性地输出 "None" 或 "-1" 并继续运行，绝对不要使用 throw、assert 导致程序崩溃或段错误！

## 题目描述
{description}
"""

    if error_feedback:
        prompt = base_prompt + f"\n## 注意：上次生成的代码测试失败！\n错误反馈如下：\n{error_feedback}\n\n请仔细分析错误原因，修正代码并输出正确的完整代码。"
    else:
        prompt = base_prompt

    try:
        from services.llm_client import SharedLLMClient

        content = SharedLLMClient().chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一个C++编程专家。你只输出纯C++源代码，"
                        "不添加任何Markdown标记、代码块标记或解释文字。"
                        "确保代码可以直接用g++编译运行。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.5 + solution_index * 0.15 if not error_feedback else 0.3,
            max_tokens=2000,
            provider="zhipu",
            request_kind="batch",
        )
        if not content:
            return ""
        # 清理可能的 Markdown 代码块标记
        content = content.strip()
        if content.startswith("```cpp"):
            content = content[6:]
        elif content.startswith("```c++"):
            content = content[6:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        return content.strip()
    except Exception as e:
        logger.error(f"AI生成代码异常: {type(e).__name__}")
        return ""


def validate_test_cases(
    description: str,
    test_cases: List[Dict],
    num_solutions: int = 2
) -> Dict:
    """
    验证测试用例的正确性。

    流程：
    1. 调用 AI 生成 num_solutions 套 C++ 解题代码
    2. 逐套使用沙箱执行，验证是否全部通过测试用例
    3. 返回验证结果

    参数：
        description: 题目描述（Markdown）
        test_cases: 测试用例列表 [{'input_data': str, 'expected_output': str, 'is_public': bool}]
        num_solutions: 生成的解题代码数量（默认2）

    返回：
        {
            'valid': bool,              # 是否全部通过
            'solutions': [              # 每套代码的验证详情
                {
                    'index': int,
                    'code': str,         # 生成的代码
                    'passed': int,
                    'total': int,
                    'status': str,       # passed/partial/failed/compile_error
                    'compile_error': str,
                    'details': [...]
                }
            ],
            'summary': str              # 简要说明
        }
    """
    if not test_cases:
        return {
            'valid': False,
            'solutions': [],
            'summary': '没有测试用例可供验证'
        }

    from services.llm_client import SharedLLMClient
    shared_client = SharedLLMClient()
    if not shared_client.is_available():
        return {
            'valid': False,
            'solutions': [],
            'summary': 'AI服务未配置，无法生成验证代码'
        }

    solutions = []
    all_passed = True

    for i in range(num_solutions):
        logger.info(f"正在生成第 {i + 1}/{num_solutions} 套验证代码...")
        code = _generate_solution_code(description, i, "")

        if not code:
            solutions.append({
                'index': i + 1,
                'code': '',
                'passed': 0,
                'total': len(test_cases),
                'status': 'error',
                'compile_error': 'AI 未能生成有效代码',
                'details': []
            })
            all_passed = False
            continue

        # 使用沙箱运行测试
        logger.info(f"正在沙箱中验证第 {i + 1} 套代码...")
        sandbox_result = run_test_cases(code, test_cases)

        solution_info = {
            'index': i + 1,
            'code': code,
            'passed': sandbox_result.get('passed', 0),
            'total': sandbox_result.get('total', len(test_cases)),
            'status': sandbox_result.get('status', 'error'),
            'compile_error': sandbox_result.get('compile_error', ''),
            'details': sandbox_result.get('details', [])
        }
        solutions.append(solution_info)

        if sandbox_result.get('status') != 'passed':
            all_passed = False

    # 生成摘要
    passed_count = sum(1 for s in solutions if s['status'] == 'passed')
    if all_passed:
        summary = f'验证通过！{num_solutions} 套 AI 生成的代码均通过了所有 {len(test_cases)} 个测试用例。'
    elif passed_count > 0:
        summary = (
            f'部分通过：{passed_count}/{num_solutions} 套代码通过了全部测试用例，'
            f'请检查未通过的代码和测试用例是否正确。'
        )
    else:
        summary = (
            f'验证失败：{num_solutions} 套 AI 生成的代码均未能通过全部测试用例。'
            f'测试用例可能存在错误，请检查后重新验证。'
        )

    return {
        'valid': all_passed,
        'solutions': solutions,
        'summary': summary
    }


def auto_generate_expected_outputs(
    description: str,
    test_inputs: List[Dict],
    max_retries: int = 2
) -> Dict:
    """
    自动生成测试用例的期望输出（带自纠错重试）。

    流程（稳妥模式）：
    1. 调用 AI 生成 1 套 C++ 官方参考解题代码。
    2. 用沙箱运行这套代码，对每个测试输入取输出。
    3. 如果编译失败或输出崩溃报错 → 带入错误信息让 AI 重试（最多 max_retries 次）。
    4. 只要有 1 套代码成功执行所有用例，直接采纳其输出作为标准期望输出，不再要求两套代码共识。
    """
    if not test_inputs:
        return {'success': False, 'test_cases': [], 'solutions': [], 'summary': '没有测试输入'}

    from services.llm_client import SharedLLMClient
    shared_client = SharedLLMClient()
    if not shared_client.is_available():
        return {'success': False, 'test_cases': [], 'solutions': [], 'summary': 'AI服务未配置'}

    # 伪装测试用例，不比对期望输出
    dummy_cases = [
        {
            'id': idx + 1,
            'input_data': tc.get('input_data', ''),
            'expected_output': '', 
            'is_public': tc.get('is_public', False),
        }
        for idx, tc in enumerate(test_inputs)
    ]

    # 我们现在只用 1 套代码
    state = {'index': 1, 'code': '', 'compiled': False, 'outputs': [None]*len(test_inputs), 'error': ''}

    for attempt in range(max_retries + 1):
        if attempt > 0:
            logger.info(f"== 期望输出生成：第 {attempt} 次纠错重试 ==")

        if state['error'] or not state['code']:
            logger.info(f"正在生成标准解题代码 (尝试 {attempt+1})...")
            code = _generate_solution_code(description, 0, "", state['error'])
            if not code:
                state['error'] = 'AI未能生成代码'
                continue

            state['code'] = code
            logger.info(f"正在沙箱运行解题代码...")
            result = run_test_cases(code, dummy_cases)

            if not result.get('compile_success', False):
                state['compiled'] = False
                state['error'] = f"编译失败：\n{result.get('compile_error', '未知编译错误')}"
                continue

            state['compiled'] = True
            state['error'] = '' # 清除错误
            
            # 提取输出并检查是否有运行时错误
            outputs = []
            has_runtime_error = False
            for detail in result.get('details', []):
                if detail.get('error'):
                    state['error'] = f"测试用例 {detail.get('case_id')} 运行时错误：\n{detail.get('error')}"
                    outputs.append(None)
                    has_runtime_error = True
                else:
                    outputs.append(detail.get('actual_output', '').strip())
            # 补齐
            while len(outputs) < len(test_inputs):
                outputs.append(None)
            state['outputs'] = outputs

            # 如果没有运行时错误，直接成功跳出！
            if not has_runtime_error:
                logger.info("标准代码成功运行所有用例，验证成功！")
                break

    # ---------- 总结摘要 ----------
    validated_cases = []
    success = state['compiled'] and not state['error']

    for i, tc in enumerate(test_inputs):
        validated_cases.append({
            'input_data': tc.get('input_data', ''),
            'expected_output': state['outputs'][i] if state['outputs'][i] is not None else '',
            'is_public': tc.get('is_public', False),
            'consensus': success, # 单套代码只要成功，就是 true
        })
    
    solutions_for_frontend = [
        {
            'index': state['index'], 
            'code': state['code'], 
            'compiled': state['compiled'], 
            'code_preview': state['code'][:500] + ('...' if len(state['code'])>500 else '') if state['code'] else ''
        }
    ]

    total = len(test_inputs)
    if not success:
        summary = f'验证失败！AI代码在重试 {max_retries} 次后依然无法通过（编译失败或运行出错）。请手动检查。'
    else:
        summary = f'验证完成！已自动生成解题代码并为您填充了 {total} 个用例的期望输出。'

    return {
        'success': success,
        'test_cases': validated_cases,
        'solutions': solutions_for_frontend,
        'summary': summary,
    }
