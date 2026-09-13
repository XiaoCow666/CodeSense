"""
代码评估模块 - 使用启发式评分和大模型评估
"""
import re

# 评分权重常量
SCORE_WEIGHTS_WITH_REQUIREMENT = {
    'basic': 0.4,
    'quality': 0.2,
    'complexity': 0.1,
    'requirement': 1.2
}
SCORE_WEIGHTS_WITHOUT_REQUIREMENT = {
    'basic': 1.0,
    'quality': 0.8,
    'complexity': 0.6
}
MATURITY_WEIGHTS = {
    'phi_avg': 0.4,
    'phi_grad': 0.3,
    'phi_freq': 0.15,
    'phi_std': 0.15
}

from config import Config

# 导入大模型评估器
from utils.llm_evaluator import LLMEvaluator

# 导入统一的 API 密钥管理器
from services.api_keys import api_keys

cfg = None
llm_evaluator = None
use_llm = False
ai_initialized = False


def initialize_ai_evaluator():
    """初始化可选的 AI 评估器；未配置密钥时使用启发式评估。"""
    global cfg, llm_evaluator, use_llm, ai_initialized

    if ai_initialized:
        return

    ai_initialized = True
    cfg = Config()

    try:
        if not api_keys.has_any_key:
            print("未配置 AI API 密钥，将使用启发式评分")
            return

        if api_keys.has_zhipu:
            print("正在初始化智谱 AI 评估器...")
            llm_evaluator = LLMEvaluator(api_type="zhipu", strict_mode=False)
        elif api_keys.has_openai:
            print("正在初始化 OpenAI 评估器...")
            llm_evaluator = LLMEvaluator(api_type="openai", strict_mode=False)

        use_llm = llm_evaluator is not None
        if use_llm:
            print("✓ AI 评估功能已启用")
    except ImportError as exc:
        print(f"AI 评估依赖未安装，将使用启发式评分: {type(exc).__name__}")
        use_llm = False
    except Exception as exc:
        print(f"AI 评估器初始化失败，将使用启发式评分: {type(exc).__name__}")
        use_llm = False


def calculate_heuristic_score(code, assignment_title=None):
    """基于启发式规则计算代码质量得分（作为备用评分方式）"""
    print("使用改进的启发式评分算法...")
    
    # 初始化评分项
    basic_score = 0
    quality_score = 0
    complexity_score = 0
    requirement_score = 0  # 题目要求匹配度得分
    
    # 检查代码是否为空或几乎为空
    if len(code.strip()) < 10:
        print("× 代码几乎为空，直接评为最低分")
        return 1, "【基础级】代码几乎为空，需要添加实际内容。"  # 修改：最低分为1分而非0分
    
    # 检查代码长度 - 过短的代码通常不是有效解决方案
    code_lines = len(code.split('\n'))
    if code_lines < 5:
        print(f"× 代码行数过少 ({code_lines}行)")
        basic_score = max(0.5, basic_score)  # 确保至少有一点基础分
    elif 5 <= code_lines < 20:
        basic_score += 1
        print(f"✓ 代码长度适中 ({code_lines}行)")
    else:
        basic_score += 1.5
        print(f"✓ 代码较长 ({code_lines}行)")
    
    # 检查基本结构 - C/C++
    valid_structure = 0
    total_structure_items = 4
    
    if "#include" in code:
        basic_score += 0.5
        valid_structure += 1
        print("✓ 包含头文件")
    else:
        print("× 未包含头文件")
    
    if "using namespace std" in code or "std::" in code:
        basic_score += 0.5
        valid_structure += 1
        print("✓ 使用std命名空间")
    else:
        print("× 未使用std命名空间")
    
    if "int main" in code or "void main" in code:
        basic_score += 0.5
        valid_structure += 1
        print("✓ 包含main函数")
    else:
        print("× 未找到main函数")
        
    if "return" in code:
        basic_score += 0.5
        valid_structure += 1
        print("✓ 函数有返回值")
    else:
        print("× 未找到返回语句")
    
    # 计算结构完整性比例
    structure_ratio = valid_structure / total_structure_items
    if structure_ratio < 0.5:
        print(f"× 代码结构不完整 (符合项: {valid_structure}/{total_structure_items})")
    elif structure_ratio < 1.0:
        print(f"△ 代码结构部分完整 (符合项: {valid_structure}/{total_structure_items})")
    else:
        print(f"✓ 代码结构完整 (符合项: {valid_structure}/{total_structure_items})")
    
    # 检查代码格式和一致性
    indentation_pattern = re.compile(r'^(\s+)\S', re.MULTILINE)
    indentations = indentation_pattern.findall(code)
    if indentations:
        # 检查缩进是否一致
        indent_types = set(len(indent) for indent in indentations)
        if len(indent_types) <= 2:  # 允许不同层级的缩进
            quality_score += 0.5
            print("✓ 代码缩进一致")
        else:
            print("× 代码缩进不一致")
    
    # 检查括号配对 - 这是格式良好代码的标志
    opening_brackets = code.count('{')
    closing_brackets = code.count('}')
    if opening_brackets == closing_brackets and opening_brackets > 0:
        quality_score += 0.5
        print(f"✓ 括号配对正确 ({opening_brackets}对)")
    elif opening_brackets != closing_brackets:
        print(f"× 括号不匹配 (开括号:{opening_brackets}, 闭括号:{closing_brackets})")
    
    # 检查语法错误的常见迹象
    syntax_error_score = 0
    if code.count('(') != code.count(')'):
        syntax_error_score += 1
        print("× 圆括号不匹配")
        
    if code.count('[') != code.count(']'):
        syntax_error_score += 1
        print("× 方括号不匹配")
        
    if code.count('"') % 2 != 0:
        syntax_error_score += 1
        print("× 引号不匹配")
        
    if code.count(';') < 3 and code_lines > 5:
        syntax_error_score += 1
        print("× 缺少分号")
        
    missing_semicolon = re.search(r'(\w+\s*=\s*[\w"\']+)\s*$', code, re.MULTILINE)
    if missing_semicolon:
        syntax_error_score += 1
        print("× 可能缺少分号")
    
    # 如果存在语法错误，降低质量分
    if syntax_error_score > 0:
        quality_score = max(0, quality_score - 0.5)
        print(f"× 检测到 {syntax_error_score} 个可能的语法问题")
    
    # 检查题目要求关键词 - 非常重要
    if assignment_title:
        print("正在检查题目要求")
        
        # 将SQLAlchemy对象转换为字符串
        try:
            title_str = str(assignment_title)
        except:
            title_str = ""
            print("× 无法获取题目标题")
        
        # 冒泡排序检测
        if "冒泡排序" in title_str:
            print("题目要求实现冒泡排序算法")
            
            # 检查代码是否符合冒泡排序的关键特征
            has_array = "int " in code and ("[" in code and "]" in code) or "array" in code.lower() or "vector" in code.lower()
            has_nested_loops = code.count("for") >= 2 or (code.count("for") >= 1 and code.count("while") >= 1)
            has_swap_operation = "swap" in code.lower() or ("><" in code and "=" in code) or "temp" in code.lower()
            has_comparison = code.count(">") + code.count("<") >= 2
            
            # 添加：如果完全不符合冒泡排序特征，给低分但不是0分
            if not has_array and not has_nested_loops and not has_swap_operation:
                print("× 代码不符合冒泡排序的基本特征，评为基础分")
                return 1, "【基础级】代码不完全符合冒泡排序的基本要求。建议添加数组定义、嵌套循环和元素交换操作，符合冒泡排序算法的基本结构。"
            
            if has_array:
                requirement_score += 1
                print("✓ 包含数组定义")
            else:
                print("× 缺少数组定义")
            
            if has_nested_loops:
                requirement_score += 1.5
                print("✓ 包含嵌套循环（冒泡排序的典型特征）")
            else:
                print("× 缺少嵌套循环（冒泡排序必备）")
            
            if has_swap_operation:
                requirement_score += 1.5
                print("✓ 包含元素交换操作")
            else:
                print("× 缺少元素交换操作（冒泡排序必备）")
                
            if has_comparison:
                requirement_score += 1
                print("✓ 包含元素比较操作")
            else:
                print("× 缺少元素比较操作（冒泡排序必备）")
                
            # 匹配度奖励: 如果代码特别符合冒泡排序特征，给予额外奖励
            if has_array and has_nested_loops and has_swap_operation and has_comparison:
                bonus = 0.5  # 额外奖励0.5分
                requirement_score += bonus
                print(f"✓ 完美符合冒泡排序特征！奖励{bonus}分")
        
        # 快速排序检测
        elif "快速排序" in title_str:
            print("题目要求实现快速排序算法")
            
            has_array = "int " in code and ("[" in code and "]" in code) or "array" in code.lower() or "vector" in code.lower()
            has_recursion = "(" in code and ")" in code and "{" in code and "}" in code and code.count("{") >= 3
            has_pivot = "pivot" in code.lower() or "基准" in code or "中枢" in code
            has_partition = code.count("for") >= 1 and code.count("if") >= 1 and code.count("<") + code.count(">") >= 2
            
            # 添加：如果完全不符合快速排序特征，给低分但不是0分
            if not has_array and not has_recursion and not has_pivot:
                print("× 代码不符合快速排序的基本特征，评为基础分")
                return 1, "【基础级】代码不完全符合快速排序的基本要求。建议添加数组定义、递归结构和基准点定义，符合快速排序算法的基本结构。"
            
            if has_array:
                requirement_score += 1
                print("✓ 包含数组定义")
            else:
                print("× 缺少数组定义")
                
            if has_recursion:
                requirement_score += 1.5
                print("✓ 包含递归结构（快速排序的典型特征）")
            else:
                print("× 缺少递归结构（快速排序必备）")
                
            if has_pivot:
                requirement_score += 1
                print("✓ 定义了基准点/pivot")
            else:
                print("× 缺少基准点定义（快速排序必备）")
                
            if has_partition:
                requirement_score += 1.5
                print("✓ 包含分区操作（快速排序的典型特征）")
            else:
                print("× 缺少分区操作（快速排序必备）")
                
            # 匹配度奖励: 如果代码特别符合快速排序特征，给予额外奖励
            if has_array and has_recursion and has_pivot and has_partition:
                bonus = 0.5  # 额外奖励0.5分
                requirement_score += bonus
                print(f"✓ 完美符合快速排序特征！奖励{bonus}分")
        
        # 通用算法题目检测
        elif "算法" in title_str:
            print("题目要求实现算法")
            
            has_io = "cin" in code or "cout" in code or "scanf" in code or "printf" in code
            has_logic = code.count("if") + code.count("for") + code.count("while") >= 2
            
            # 添加：如果完全没有算法逻辑，给0分
            if not has_logic and not (code.count("if") + code.count("for") + code.count("while") >= 1):
                print("× 代码完全没有算法逻辑，评为0分")
                return 0, "【严重不合格】代码中完全没有算法逻辑，没有任何条件判断或循环结构。"
            
            if has_io:
                requirement_score += 1
                print("✓ 包含输入输出")
            else:
                print("× 缺少输入输出")
                
            if has_logic:
                requirement_score += 2
                print("✓ 包含算法逻辑")
            else:
                print("× 缺少算法逻辑")
        
        # Hello World特殊处理
        elif "Hello" in title_str or "hello" in title_str:
            has_hello = "Hello World" in code or "Hello, World" in code
            has_io = "cout" in code or "printf" in code
            
            # 添加：如果Hello World题目中没有相关输出，给0分
            if not has_hello and not has_io:
                print("× Hello World题目中没有相关输出，评为0分")
                return 0, "【严重不合格】Hello World题目中没有包含任何输出语句或相关文本。"
            
            if has_hello:
                requirement_score += 3
                print("✓ Hello World程序（符合题目要求）")
            else:
                print("× 缺少Hello World输出")
                
            if has_io:
                requirement_score += 1
                print("✓ 包含输出语句")
            else:
                print("× 缺少输出语句")
        
        # 惩罚Hello World代码 - 当题目不是要求Hello World但用户提交了Hello World代码
        if "Hello World" in code or "Hello, World" in code:
            if not ("Hello" in title_str or "hello" in title_str):
                requirement_score = max(0, requirement_score - 2)
                print("× 包含Hello World代码，与题目要求不符")
                
                # 添加：如果代码只是简单的Hello World但题目要求不是Hello World，给0分
                if code_lines < 10 and ("cout << \"Hello" in code or "printf(\"Hello" in code):
                    print("× 代码仅为简单Hello World，与题目要求完全不符，评为0分")
                    return 0, "【严重不合格】提交的代码仅为简单的Hello World程序，与题目要求完全不符。"
    
    # 检查注释的存在和质量
    comment_count = code.count("//") + code.count("/*")
    if comment_count > 0:
        if comment_count >= 5:
            quality_score += 1.5
            print(f"✓ 优秀的注释数量 ({comment_count}条)")
        elif comment_count >= 3:
            quality_score += 1
            print(f"✓ 良好的注释 ({comment_count}条)")
        else:
            quality_score += 0.5
            print(f"✓ 包含注释 ({comment_count}条)")
    else:
        print("× 没有注释")
    
    # 代码复杂度评估 - 改进版
    # 检查循环
    loop_count = 0
    for_count = (code.count("for(") + code.count("for ("))
    while_count = (code.count("while(") + code.count("while ("))
    do_count = (code.count("do {") + code.count("do{"))
    loop_count = for_count + while_count + do_count
    
    # 检查条件语句
    if_count = (code.count("if(") + code.count("if ("))
    switch_count = (code.count("switch(") + code.count("switch (")) * 2  # switch通常更复杂
    condition_count = if_count + switch_count
    
    # 检查函数定义 (更精确的模式)
    function_pattern = r'\b(?:int|void|char|float|double|long|bool|auto|string)\s+\w+\s*\([^)]*\)\s*{' 
    function_matches = re.findall(function_pattern, code)
    function_count = len(function_matches)
    
    if function_count > 1:  # 不算main函数
        complexity_score += 1.5
        print(f"✓ 包含 {function_count} 个函数定义")
    elif function_count == 1 and "main" not in function_matches[0]:
        complexity_score += 1.0
        print("✓ 包含1个自定义函数")
    
    # 根据循环和条件语句的数量评分
    if loop_count > 0:
        if loop_count >= 3:
            complexity_score += 1.5
            print(f"✓ 复杂循环结构 ({loop_count}个)")
        else:
            complexity_score += 1
            print(f"✓ 包含循环 ({loop_count}个)")
    else:
        print("× 没有循环结构")
    
    if condition_count > 0:
        if condition_count >= 3:
            complexity_score += 1
            print(f"✓ 复杂条件逻辑 ({condition_count}个)")
        else:
            complexity_score += 0.5
            print(f"✓ 包含条件语句 ({condition_count}个)")
    else:
        print("× 没有条件语句")
    
    # 检查数据结构的使用
    data_structure_score = 0
    if "vector" in code or "list" in code or "map" in code or "set" in code:
        data_structure_score += 1
        print("✓ 使用了STL容器")
    
    if "struct" in code or "class" in code:
        data_structure_score += 1
        print("✓ 定义了自定义数据类型")
    
    complexity_score += data_structure_score
    
    # 代码简洁性评估
    repeated_code_patterns = re.findall(r'(\w+\s*=\s*\w+\s*;[\s\n]*\w+\s*=\s*\w+\s*;[\s\n]*\w+\s*=\s*\w+\s*;)', code)
    if repeated_code_patterns:
        quality_score = max(0, quality_score - 0.5)
        print("× 存在重复代码模式")
    
    # 空格和命名风格一致性
    if re.search(r'\w+\(\w', code):  # 函数调用没有空格
        quality_score = max(0, quality_score - 0.5)
        print("× 函数调用格式不一致")
        
    if re.search(r'if\(', code) and re.search(r'if\s\(', code):  # if风格不一致
        quality_score = max(0, quality_score - 0.5)
        print("× 条件语句格式不一致")
    
    # 检查抄袭或模板代码的迹象
    if "TODO" in code or "FIXME" in code or "template" in code.lower():
        quality_score = max(0, quality_score - 1.0)
        print("× 检测到可能的模板代码")
        
        # 添加：如果代码中有明显的TODO注释且没有实际实现，给0分
        if "TODO" in code and code_lines < 20:
            todo_pattern = re.findall(r'//\s*TODO.*', code)
            if len(todo_pattern) >= 2:
                print("× 代码中有多处TODO注释但没有实际实现，评为0分")
                return 0, "【严重不合格】代码似乎是未完成的模板，包含多处TODO注释但没有实际实现。"
    
    # 计算总分，做加权
    # 如果题目有特殊要求，优先考虑题目要求得分
    if requirement_score > 0:
        # 使用更优的加权方案
        total_score = (
            SCORE_WEIGHTS_WITH_REQUIREMENT['basic'] * basic_score +
            SCORE_WEIGHTS_WITH_REQUIREMENT['quality'] * quality_score +
            SCORE_WEIGHTS_WITH_REQUIREMENT['complexity'] * complexity_score +
            SCORE_WEIGHTS_WITH_REQUIREMENT['requirement'] * requirement_score
        )
        print(f"分数明细: 基础结构({basic_score:.1f}) + 代码质量({quality_score:.1f}) + 复杂度({complexity_score:.1f}) + 题目要求({requirement_score:.1f}) × 1.2")
    else:
        # 如果没有特定要求，基础结构分变得更重要
        total_score = (
            SCORE_WEIGHTS_WITHOUT_REQUIREMENT['basic'] * basic_score +
            SCORE_WEIGHTS_WITHOUT_REQUIREMENT['quality'] * quality_score +
            SCORE_WEIGHTS_WITHOUT_REQUIREMENT['complexity'] * complexity_score
        )
        print(f"分数明细: 基础结构({basic_score:.1f}) × 1.0 + 代码质量({quality_score:.1f}) × 0.8 + 复杂度({complexity_score:.1f}) × 0.6")
    
    # 根据代码行数适当调整分数
    if code_lines > 50:
        total_score *= 1.1
        print(f"✓ 较长代码 ({code_lines}行), 得分乘以1.1")
    
    # 如果代码有明显语法问题，限制总分最高为3
    if syntax_error_score > 1:
        total_score = min(total_score, 3.0)
        print(f"× 由于存在可能的语法问题，总分上限设为3")
        
    # 添加：当存在严重缺陷时直接给0分
    if basic_score < 1 and requirement_score < 1:
        print("× 代码基础结构和题目要求得分都极低，评为0分")
        return 0, "【严重不合格】代码基础结构严重不足且不符合题目基本要求。"
    
    # 如果没有基本的C++结构但代码行数大于10，可能是其他语言的代码
    c_cpp_features = "#include" in code or "int main" in code or "void main" in code or "cout" in code or "cin" in code or "printf" in code or "scanf" in code
    if not c_cpp_features and code_lines > 10:
        print("× 可能提交了非C/C++代码")
        # 检查是否是Python代码
        if "def " in code or "import " in code or "print(" in code or ":" in code and code.count(":") > code.count(";"):
            print("× 检测到可能是Python代码，不符合C/C++题目要求，评为0分")
            return 0, "【严重不合格】提交的似乎是Python代码，而不是要求的C/C++代码。"
        
        # 添加：降低分数但不一定给0分
        total_score = min(total_score, 2.0)
        print("× 代码不符合C/C++特征，分数上限设为2")
    
    # 转换为0-5分制（包含0分）
    normalized_score = min(5, max(0, round(total_score)))
    
    # 添加：对极低分进一步判断是否应该为0分
    if normalized_score == 1 and (basic_score < 1.5 or (syntax_error_score > 2 and requirement_score < 2)):
        normalized_score = 0
        print("× 综合评分极低，调整为0分")
    
    print(f"启发式评分: 原始得分 {total_score:.1f}, 转换为0-5分制: {normalized_score}")
    
    # 生成反馈信息
    feedback = generate_feedback(code, normalized_score, assignment_title)
    return normalized_score, feedback




def generate_feedback(code, score, assignment_title=None):
    """根据代码和评分生成人类可读的反馈"""
    # 兼容分值范围：如果传入的是 0-5 分制，将其乘以 20 转换为 0-100 分制
    if score <= 5.0:
        score = score * 20.0
        
    feedback = ""
    
    # 评估代码与题目的匹配度
    requirement_match = ""
    if assignment_title:
        title_str = str(assignment_title)
        
        # 检查冒泡排序
        if "冒泡排序" in title_str:
            has_array = "int " in code and ("[" in code and "]" in code) or "array" in code.lower() or "vector" in code.lower()
            has_nested_loops = code.count("for") >= 2 or (code.count("for") >= 1 and code.count("while") >= 1)
            has_swap_operation = "swap" in code.lower() or ("><" in code and "=" in code) or "temp" in code.lower()
            has_comparison = code.count(">") + code.count("<") >= 2
            
            if has_array and has_nested_loops and has_swap_operation and has_comparison:
                requirement_match = "👍 代码完全符合冒泡排序的核心要求，实现了所有必要的算法特征！"
            elif (has_array and has_nested_loops and has_swap_operation) or (has_array and has_nested_loops and has_comparison):
                requirement_match = "👍 代码基本符合冒泡排序的核心要求，实现了大部分算法特征。"
        
        # 检查快速排序
        elif "快速排序" in title_str:
            has_array = "int " in code and ("[" in code and "]" in code) or "array" in code.lower() or "vector" in code.lower()
            has_recursion = "(" in code and ")" in code and "{" in code and "}" in code and code.count("{") >= 3
            has_pivot = "pivot" in code.lower() or "基准" in code or "中枢" in code
            has_partition = code.count("for") >= 1 and code.count("if") >= 1 and code.count("<") + code.count(">") >= 2
            
            if has_array and has_recursion and has_pivot and has_partition:
                requirement_match = "👍 代码完全符合快速排序的核心要求，实现了所有必要的算法特征！"
            elif (has_array and has_recursion and has_pivot) or (has_array and has_recursion and has_partition):
                requirement_match = "👍 代码基本符合快速排序的核心要求，实现了大部分算法特征。"
        
        # 检查其他常见算法
        elif "排序" in title_str:
            has_array = "int " in code and ("[" in code and "]" in code) or "array" in code.lower() or "vector" in code.lower()
            has_loop = "for" in code or "while" in code
            has_comparison = code.count(">") + code.count("<") >= 2
            
            if has_array and has_loop and has_comparison:
                requirement_match = "👍 代码实现了排序算法的基本要求，包含数组、循环和比较操作。"
                
        elif "二分" in title_str or "折半" in title_str:
            has_array = "int " in code and ("[" in code and "]" in code) or "array" in code.lower() or "vector" in code.lower()
            has_mid = "mid" in code.lower() or "middle" in code.lower() or "中间" in code
            has_comparison = code.count(">") + code.count("<") >= 2
            
            if has_array and has_mid and has_comparison:
                requirement_match = "👍 代码很好地实现了二分查找算法的核心逻辑！"
                
        # 检查链表相关
        elif "链表" in title_str:
            has_node = "node" in code.lower() or "Node" in code or "节点" in code
            has_pointer = "->" in code or "*" in code
            has_structure = "struct" in code or "class" in code
            
            if has_node and has_pointer and has_structure:
                requirement_match = "👍 代码很好地实现了链表的核心结构和操作！"

        # 检查计算器程序
        elif "计算器" in title_str:
            has_input = "cin" in code or "scanf" in code or "gets" in code
            has_operation = "+" in code and "-" in code and "*" in code and "/" in code
            has_output = "cout" in code or "printf" in code
            
            if has_input and has_operation and has_output:
                requirement_match = "👍 代码很好地实现了计算器的基本功能，包含输入、计算和输出！"
    
    # 根据分数决定总体评价
    if score >= 90:
        overall = f"代码质量优秀，完全符合期望要求！{requirement_match}"
    elif score >= 80:
        overall = f"代码质量良好，实现了主要功能。{requirement_match}"
    elif score >= 60:
        overall = f"代码基本可用，有少量问题需要改进。{requirement_match}"
    elif score >= 40:
        overall = f"代码结构已具备，但存在多处需要改进的地方。{requirement_match}"
    elif score >= 20:
        overall = f"代码有一定的基础，但需要全面改进。{requirement_match}"
    else:
        overall = f"代码存在严重问题，需要重新设计。{requirement_match}"
    
    # 根据评分生成总体评价
    if score < 20:
        feedback += "【严重不合格】代码存在严重缺陷，完全不符合基本要求。\n\n"
    elif score >= 90:
        feedback += f"【优秀代码】代码质量非常高，结构清晰，功能完整。\n\n{overall}\n\n"
    elif score >= 80:
        feedback += f"【良好代码】代码质量良好，基本结构完整，实现了主要功能。\n\n{overall}\n\n"
    elif score >= 60:
        feedback += f"【合格代码】代码基本可用，但存在一些结构或实现上的问题。\n\n{overall}\n\n"
    elif score >= 40:
        feedback += f"【不足代码】代码存在较多问题，需要进行改进。\n\n{overall}\n\n"
    else:
        feedback += f"【不合格代码】代码存在严重问题，无法正常工作。\n\n{overall}\n\n"
    
    # 特殊处理0分反馈
    if score == 0:
        feedback += "代码分析：\n"
        
        # 检查代码长度
        code_lines = len(code.split('\n'))
        if code_lines < 5:
            feedback += "- 代码行数过少，几乎没有实质内容。\n"
        
        # 检查基本结构
        if "#include" not in code:
            feedback += "- 缺少必要的头文件引用。\n"
        
        if "using namespace std" not in code and "std::" not in code:
            feedback += "- 未使用std命名空间。\n"
        
        if "int main" not in code and "void main" not in code:
            feedback += "- 缺少main函数，程序无法独立运行。\n"
            
        # 检查是否为Hello World
        if "Hello World" in code or "Hello, World" in code:
            if assignment_title and not ("Hello" in str(assignment_title) or "hello" in str(assignment_title)):
                feedback += "- 提交的是简单的Hello World代码，与题目要求不符。\n"
        
        # 检查是否可能是其他语言代码
        c_cpp_features = "#include" in code or "int main" in code or "void main" in code or "cout" in code or "cin" in code or "printf" in code or "scanf" in code
        if not c_cpp_features and code_lines > 10:
            if "def " in code or "import " in code or "print(" in code:
                feedback += "- 提交的似乎是Python代码，而不是要求的C/C++代码。\n"
            else:
                feedback += "- 代码不符合C/C++语法特征。\n"
        
        # 检查常见错误
        if code.count('{') != code.count('}'):
            feedback += "- 括号不匹配，存在语法错误。\n"
            
        if "TODO" in code:
            feedback += "- 代码包含TODO注释，似乎是未完成的模板。\n"
        
        # 针对题目要求的反馈
        if assignment_title:
            title_str = str(assignment_title)
            if "冒泡排序" in title_str:
                feedback += "- 代码缺少冒泡排序的基本特征（数组定义、嵌套循环、比较交换操作）。\n"
            elif "快速排序" in title_str:
                feedback += "- 代码缺少快速排序的基本特征（递归结构、划分操作、基准点）。\n"
            elif "算法" in title_str:
                feedback += "- 代码缺少必要的算法逻辑和结构。\n"
        
        feedback += "\n改进建议：\n"
        feedback += "- 请完全重写代码，确保符合C/C++语法和题目要求。\n"
        feedback += "- 确保包含所有必要的结构元素（头文件、main函数、必要的语法结构）。\n"
        feedback += "- 仔细阅读题目要求，实现所有必需的功能。\n"
        feedback += "- 添加注释解释代码逻辑和实现思路。\n"
        
        return feedback
    
    # 非0分的常规反馈生成
    feedback += "代码分析：\n"
    
    # 代码长度分析
    code_lines = len(code.split('\n'))
    if code_lines < 5:
        feedback += "- 代码行数过少，可能未完整实现所需功能。\n"
    elif code_lines > 50:
        feedback += "- 代码行数较多，注意检查是否有冗余部分。\n"
    else:
        feedback += "- 代码长度适中。\n"
    
    # 基本结构分析
    if "#include" in code:
        feedback += "- 包含了必要的头文件。\n"
    else:
        feedback += "- 缺少必要的头文件引用。\n"
    
    if "using namespace std" in code or "std::" in code:
        feedback += "- 正确使用了std命名空间。\n"
    else:
        feedback += "- 未使用std命名空间，可能导致标准库函数无法正常使用。\n"
    
    if "int main" in code or "void main" in code:
        feedback += "- 包含main函数，程序入口正确。\n"
    else:
        feedback += "- 缺少main函数，程序无法独立运行。\n"
    
    # 检查核心语法特性
    features = []
    if "for" in code or "while" in code:
        features.append("循环")
    if "if" in code or "switch" in code:
        features.append("条件判断")
    if "[]" in code or "vector" in code.lower():
        features.append("数组/容器")
    if "class" in code or "struct" in code:
        features.append("自定义类型")
    if "=" in code and ("+" in code or "-" in code or "*" in code or "/" in code):
        features.append("算术运算")
    if "++" in code or "--" in code:
        features.append("自增/自减")
    
    if features:
        feedback += f"- 使用了以下编程特性：{', '.join(features)}。\n"
    else:
        feedback += "- 缺少基本的编程特性，代码功能可能不完整。\n"
    
    # 根据分数给出改进建议
    feedback += "\n改进建议：\n"
    if score <= 40:
        # 基础层：给出精确到行的具体建议 + 类比代码示例
        if "#include" not in code:
            feedback += "- **第1行**：缺少头文件引用。C++程序通常需要 `#include <iostream>` 来使用输入输出功能。\n"
        if "using namespace std" not in code and "std::" not in code:
            feedback += "- **命名空间**：未声明 `using namespace std;`，这会导致 `cout`、`cin` 等标准函数无法直接使用。\n"
        if "int main" not in code and "void main" not in code:
            feedback += "- **程序入口**：缺少 `int main()` 函数。每个C++程序必须有一个 main 函数作为起点。\n"
        if code_lines < 10:
            feedback += "- **代码量不足**：当前代码过短，可能未实现题目要求的核心逻辑。请先理清思路，再逐步补充代码。\n"
        
        # 检查常见语法错误并给出具体行号
        lines = code.split('\n')
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped and not stripped.startswith('//') and not stripped.startswith('#'):
                # 检查缺少分号
                if stripped.endswith(')') and not stripped.startswith('if') and not stripped.startswith('for') and not stripped.startswith('while') and not stripped.startswith('else'):
                    if '{' not in stripped and '//' not in stripped:
                        feedback += f"- **第{i}行**：该语句可能缺少分号 `;`。\n"
                        break  # 只报告第一个问题，避免信息过载
        
        feedback += "\n💡 **类比示例**（展示基本程序结构，非题目答案）：\n"
        feedback += "```cpp\n"
        feedback += "#include <iostream>\n"
        feedback += "using namespace std;\n"
        feedback += "int main() {\n"
        feedback += "    int x;\n"
        feedback += "    cin >> x;          // 读取输入\n"
        feedback += "    cout << x * 2;     // 处理并输出\n"
        feedback += "    return 0;\n"
        feedback += "}\n"
        feedback += "```\n"
        feedback += "上面的示例展示了一个完整C++程序的基本框架：头文件→命名空间→main函数→输入→处理→输出。请参考此结构来组织你的代码。\n"
        
    elif score <= 60:
        # 进阶层：引导思考
        feedback += "- 你的代码已经具备基本框架，离正确答案不远了！👍\n"
        if "#include" not in code:
            feedback += "- 检查一下头文件引用是否完整。\n"
        feedback += "- 💭 **思考**：试着用几组不同的输入手动运行你的程序，看看输出是否符合预期。\n"
        feedback += "- 💭 **思考**：特别注意边界情况——当输入为0或负数时，你的程序表现如何？\n"
        feedback += "- 添加注释说明代码功能和实现逻辑，这有助于你自己理清思路。\n"
    
    if score <= 85:
        if score > 60:
            # 优化层：高级建议
            feedback += "- ✨ 考虑给变量起更有描述性的名字（如用 `sum` 代替 `s`，用 `count` 代替 `n`）。\n"
            feedback += "- ✨ 检查缩进是否一致，代码风格统一能大幅提升可读性。\n"
            if code.count('//') < 3 and code_lines > 15:
                feedback += "- ✨ 建议在关键逻辑处添加注释，便于他人（和未来的你）理解代码意图。\n"
    
    return feedback


def evaluate_cpp_code(code_str, model=None, assignment_title=None, preview_only=False, guidance_mode=False):
    """
    评估C++代码的质量
    
    参数:
        code_str: 要评估的代码字符串
        model: 兼容旧调用的参数；标准版不加载本地模型
        assignment_title: 作业标题，用于提供给大模型进行评估
        preview_only: 是否仅进行预览评估，如果为True则只调用大模型评估
        guidance_mode: 是否是指导模式，如果为True则生成更鼓励和指导性的内容
        
    返回:
        (score, feedback): 分数（0-100）和反馈信息的元组
    """
    global use_llm, llm_evaluator, ai_initialized

    if not ai_initialized:
        initialize_ai_evaluator()
    
    # 如果是指导模式，必定使用大模型
    if guidance_mode:
        use_llm_local = True
        preview_only = True
    else:
        # 使用配置中的大模型权重
        use_llm_local = use_llm and cfg.use_llm if cfg else False
    
    # 如果预览模式并且大模型评估器可用，直接使用大模型评估
    if (preview_only or guidance_mode) and use_llm and llm_evaluator:
        prompt_type = "guidance" if guidance_mode else "evaluation"
        print(f"{'指导' if guidance_mode else '预览'}模式：直接使用大模型{prompt_type}")
        try:
            if guidance_mode:
                # 指导模式：使用更鼓励和指导性的语言
                score, feedback = llm_evaluator.provide_guidance(code_str, assignment_title)
                # 指导模式下不强调分数
                return max(3, score), feedback  # 基础分至少为3分，以示鼓励
            else:
                # 评分模式：正常评估
                score, feedback = llm_evaluator.evaluate_code(code_str, assignment_title)
                # 修改：不允许大模型给出0分，最低给1分
                if score <= 0:
                    score = 20
                    feedback = "【基础级】" + feedback
                elif score <= 5: # 兼容 5 分制输入
                    score = score * 20
                return score, feedback
        except Exception as e:
            print(
                f"大模型{'指导' if guidance_mode else '预览'}评估失败: "
                f"{type(e).__name__}"
            )
            if guidance_mode:
                # 指导模式下失败时提供通用的指导
                return 3, "很遗憾，AI助手无法分析您的代码。建议您检查代码格式是否正确，确保语法没有明显错误，并尝试添加更多注释说明您的思路。如果您遇到特定问题，可以直接在问答区提问。"
            else:
                return 3, "大模型评估失败，请稍后重试"
    
    # 大模型结果优先，启发式结果作为兜底
    llm_weight = 0.9 if use_llm_local and cfg else 0
    heuristic_weight = 0.1 if use_llm_local and cfg else 1.0
    
    # 检查代码长度是否太短
    if len(code_str.strip()) < 10:
        print("代码太短，无法进行有效评估")
        if guidance_mode:
            return 3, "您的代码太少，无法提供具体的编程指导。建议您先尝试编写更多代码，或者在问答区详细描述您的思路和遇到的问题。"
        else:
            return 20, "代码太短，无法进行有效评估。请提供更完整的代码。"  # 修改：将最低分改为20分而非0分，更友好
    
    # 如果大模型评估可用，先进行大模型评估
    if use_llm_local and llm_evaluator:
        try:
            print("使用大模型评估代码...")
            if guidance_mode:
                # 指导模式
                llm_score, llm_feedback = llm_evaluator.provide_guidance(code_str, assignment_title)
                # 指导模式下不给低分，保持积极性
                llm_score = max(3, llm_score)
            else:
                # 评分模式 - 使用结构化评估
                llm_score, llm_feedback, structured_data = llm_evaluator.evaluate_code_with_structured_data(code_str, assignment_title)
                
                # 将结构化数据附加到返回值中，以便调用者可以保存到数据库
                if hasattr(llm_evaluator, '_last_structured_data'):
                    llm_evaluator._last_structured_data = structured_data
                else:
                    setattr(llm_evaluator, '_last_structured_data', structured_data)
                
            if llm_score <= 5: # 兼容 5 分制
                llm_score = llm_score * 20

            if llm_score <= 0:
                llm_score = 20
                llm_feedback = "【基础级】" + llm_feedback
            
            print(f"✓ 大模型{'指导' if guidance_mode else '评分'}结果: {llm_score}/100")
            
            # 如果是预览模式、指导模式或大模型权重极高，直接返回大模型结果
            if preview_only or guidance_mode or llm_weight >= 0.9:
                return llm_score, llm_feedback
            
            # 否则继续进行启发式评估，最终结果将综合两种评估
        except Exception as e:
            print(
                f"大模型{'指导' if guidance_mode else '评估'}失败，将仅使用启发式评分: "
                f"{type(e).__name__}"
            )
            llm_score = None
            llm_feedback = None
            # 如果大模型评估失败，使用启发式评分
            llm_weight = 0
            heuristic_weight = 1.0
            
            # 指导模式下，如果大模型失败，提供通用指导
            if guidance_mode:
                return 3, "很遗憾，AI助手无法分析您的代码。建议您检查代码格式是否正确，确保语法没有明显错误，并尝试添加更多注释说明您的思路。如果您遇到特定问题，可以直接在问答区提问。"
    else:
        llm_score = None
        llm_feedback = None
        # 不使用大模型时，启发式评分权重为100%
        llm_weight = 0
        heuristic_weight = 1.0
        
        # 指导模式下，如果没有大模型，提供通用指导
        if guidance_mode:
            # 使用启发式方法
            score, basic_feedback = calculate_heuristic_score(code_str, assignment_title)
            # 转换为更鼓励的语言
            encouragement = """
您已经取得了很好的开始！以下是一些建议，帮助您进一步完善代码：

1. 继续完善代码的基础结构，确保包含所有必要的函数和变量。
2. 添加详细的注释，解释您的思路和代码逻辑。
3. 测试代码的不同部分，确保它们按预期工作。
4. 如果遇到困难，可以查询相关文档或在问答区提问。

记住，编程是一个不断尝试和改进的过程。每次修改都是进步！
"""
            return max(3, score), basic_feedback + "\n\n" + encouragement
    
    # 使用启发式规则评估代码
    print("使用启发式规则评估代码...")
    score, feedback = calculate_heuristic_score(code_str, assignment_title)

    if guidance_mode:
        score = max(3, score)
        feedback = feedback.replace("改进建议", "学习建议")
        feedback = feedback.replace("缺少", "可以添加")
        feedback = feedback.replace("代码质量很差", "代码有提升空间")
        feedback = feedback.replace("需要全面改进", "可以进一步完善")
        feedback += "\n\n别灰心！每个程序员都是从基础开始的。继续练习，您会越来越好！"

    heuristic_score = score if 'score' in locals() else None
    
    # 加权计算最终分数
    final_score = 0
    
    if llm_score is not None:
        # 如果使用了大模型评估，进行加权平均
        if heuristic_score is not None:
            # 综合两种评分
            final_score = llm_score * llm_weight + heuristic_score * heuristic_weight
            print(f"计算最终分数: {llm_score} × {llm_weight} + {heuristic_score} × {heuristic_weight} = {final_score}")
            
            # 检查是否需要题目匹配度加分
            if assignment_title:
                title_str = str(assignment_title)
                code_matches_requirement = False
                
                # 检查冒泡排序的关键特征
                if "冒泡排序" in title_str:
                    has_array = "int " in code_str and ("[" in code_str and "]" in code_str) or "array" in code_str.lower() or "vector" in code_str.lower()
                    has_nested_loops = code_str.count("for") >= 2 or (code_str.count("for") >= 1 and code_str.count("while") >= 1)
                    has_swap_operation = "swap" in code_str.lower() or ("><" in code_str and "=" in code_str) or "temp" in code_str.lower()
                    has_comparison = code_str.count(">") + code_str.count("<") >= 2
                    
                    if has_array and has_nested_loops and has_swap_operation and has_comparison:
                        code_matches_requirement = True
                
                # 检查快速排序的关键特征
                elif "快速排序" in title_str:
                    has_array = "int " in code_str and ("[" in code_str and "]" in code_str) or "array" in code_str.lower() or "vector" in code_str.lower()
                    has_recursion = "(" in code_str and ")" in code_str and "{" in code_str and "}" in code_str and code_str.count("{") >= 3
                    has_pivot = "pivot" in code_str.lower() or "基准" in code_str or "中枢" in code_str
                    has_partition = code_str.count("for") >= 1 and code_str.count("if") >= 1 and code_str.count("<") + code_str.count(">") >= 2
                    
                    if has_array and has_recursion and has_pivot and has_partition:
                        code_matches_requirement = True
                
                # 检查二分查找的关键特征
                elif "二分" in title_str or "折半" in title_str:
                    has_array = "int " in code_str and ("[" in code_str and "]" in code_str) or "array" in code_str.lower() or "vector" in code_str.lower()
                    has_mid = "mid" in code_str.lower() or "middle" in code_str.lower() or "中间" in code_str
                    has_comparison = code_str.count(">") + code_str.count("<") >= 2
                    
                    if has_array and has_mid and has_comparison:
                        code_matches_requirement = True
                
                # 检查链表的关键特征
                elif "链表" in title_str:
                    has_node = "node" in code_str.lower() or "Node" in code_str or "节点" in code_str
                    has_pointer = "->" in code_str or "*" in code_str
                    has_structure = "struct" in code_str or "class" in code_str
                    
                    if has_node and has_pointer and has_structure:
                        code_matches_requirement = True
                
                # 如果代码特别符合题目要求，给予额外加分
                if code_matches_requirement and final_score < 5:
                    old_score = final_score
                    if final_score >= 3.5:
                        # 高分段：提高到接近满分
                        final_score = min(5, final_score + 0.5)
                    else:
                        # 低分段：提升20%但不超过4分
                        final_score = min(4, final_score * 1.2)
                    print(
                        f"题目匹配度加分: {old_score} → {final_score}"
                    )
        else:
            # 只有大模型评分
            final_score = llm_score
            print(f"使用大模型分数作为最终分数: {final_score}")
    else:
        # 只有启发式评分
        if heuristic_score is not None:
            final_score = heuristic_score
            print(f"使用启发式评分作为最终分数: {final_score}")
        else:
            # 没有任何有效评分，给出警告默认分数
            final_score = 1
            feedback = "无法使用任何评估模型，请尝试重新提交或联系管理员。"
            print("警告: 所有评估模型都失败，使用默认分数")
    
    # 确保最终分数在0-5之间
    final_score = max(0, min(5, final_score))
    
    # 生成反馈
    if 'feedback' not in locals() or feedback is None:
        feedback = generate_feedback(code_str, final_score, assignment_title)
        
    print(f"最终评分: {final_score}/5")
    return final_score, feedback


def analyze_code_quality(code_str):
    """
    分析代码质量，提供多维度评估
    
    参数:
        code_str: 要分析的代码字符串
        
    返回:
        dict: 包含各项评估指标和反馈的字典
    """
    result = {}
    
    # 初始化默认分数
    result['algorithm_score'] = 65  # 算法能力得分
    result['style_score'] = 70      # 代码风格得分
    result['functionality_score'] = 75  # 功能实现得分
    result['efficiency_score'] = 65  # 效率优化得分
    result['suggestions'] = []      # 改进建议
    
    try:
        # 代码长度检查
        code_length = len(code_str.strip())
        if code_length < 50:
            result['structure_feedback'] = "代码较短，难以进行全面的结构分析。"
            result['style_feedback'] = "代码长度不足，难以评估代码风格。"
            result['suggestions'].append("编写更完整的代码，包含必要的结构和功能实现。")
            return result
            
        # 提取代码结构特征
        lines = code_str.strip().split('\n')
        non_empty_lines = [line for line in lines if line.strip()]
        comment_lines = [line for line in non_empty_lines if line.strip().startswith('//') or line.strip().startswith('/*')]
        
        # 计算注释比例
        comment_ratio = len(comment_lines) / len(non_empty_lines) if non_empty_lines else 0
        
        # 代码缩进分析
        indentation_consistency = True
        indentation_pattern = None
        for line in non_empty_lines:
            if line.strip() and not line.strip().startswith('//') and not line.strip().startswith('/*'):
                spaces = len(line) - len(line.lstrip())
                if spaces > 0:
                    if indentation_pattern is None:
                        indentation_pattern = spaces
                    elif spaces % indentation_pattern != 0:
                        indentation_consistency = False
                        break
        
        # 函数和类分析
        function_count = 0
        class_count = 0
        long_lines_count = 0
        max_line_length = 0
        
        # 函数和长行检测
        for line in non_empty_lines:
            # 检测函数定义
            if re.search(r'(void|int|float|double|bool|char|string|auto)\s+\w+\s*\([^)]*\)\s*({|\n)', line):
                function_count += 1
                
            # 检测类定义
            if re.search(r'class\s+\w+', line):
                class_count += 1
                
            # 检测长行
            line_length = len(line.rstrip())
            max_line_length = max(max_line_length, line_length)
            if line_length > 80:  # 标准行长度限制
                long_lines_count += 1
        
        # 变量命名分析
        variable_pattern = re.compile(r'\b(int|float|double|char|bool|string|auto)\s+([a-zA-Z_][a-zA-Z0-9_]*)')
        variable_names = []
        
        for line in non_empty_lines:
            matches = variable_pattern.findall(line)
            for match in matches:
                variable_names.append(match[1])
        
        # 检查变量命名是否遵循命名规范（驼峰或下划线）
        good_naming = 0
        for name in variable_names:
            if re.match(r'^[a-z][a-zA-Z0-9]*$', name) or re.match(r'^[a-z][a-z0-9_]*$', name):
                good_naming += 1
        
        naming_ratio = good_naming / len(variable_names) if variable_names else 1.0
        
        # 算法评分
        if function_count > 2:
            result['algorithm_score'] += 10
        
        if class_count > 0:
            result['algorithm_score'] += 5
            
        # 代码风格评分
        if comment_ratio >= 0.1:
            result['style_score'] += 5
        
        if indentation_consistency:
            result['style_score'] += 10
        
        if naming_ratio > 0.8:
            result['style_score'] += 10
        
        if long_lines_count <= len(non_empty_lines) * 0.1:
            result['style_score'] += 5
        
        # 功能实现评分 (这需要更深入的分析，这里只是基于结构特征简单估计)
        if function_count > 0:
            result['functionality_score'] += 5
        
        if class_count > 0:
            result['functionality_score'] += 5
        
        # 效率评分
        # 这通常需要更深入的分析，这里简单估计
        if max_line_length <= 100:
            result['efficiency_score'] += 5
            
        # 生成反馈
        # 结构反馈
        structure_feedback = []
        if function_count == 0:
            structure_feedback.append("代码没有定义函数，缺乏模块化结构。")
        else:
            structure_feedback.append(f"代码定义了{function_count}个函数，具有一定的模块化水平。")
            
        if class_count == 0:
            structure_feedback.append("代码没有使用类，缺乏面向对象设计。")
        else:
            structure_feedback.append(f"代码定义了{class_count}个类，应用了面向对象设计。")
            
        # 风格反馈
        style_feedback = []
        if comment_ratio < 0.1:
            style_feedback.append("代码注释较少，建议添加更多注释以提高可读性。")
            result['suggestions'].append("增加代码注释，解释关键算法和复杂逻辑。")
        else:
            style_feedback.append("代码包含适当的注释，有助于理解代码逻辑。")
            
        if not indentation_consistency:
            style_feedback.append("代码缩进不一致，影响可读性。")
            result['suggestions'].append("统一代码缩进风格，提高代码整洁度。")
        else:
            style_feedback.append("代码缩进一致，结构清晰。")
            
        if naming_ratio < 0.8:
            style_feedback.append("部分变量命名不规范，建议改进。")
            result['suggestions'].append("使用更有意义的变量名，遵循命名规范。")
        else:
            style_feedback.append("变量命名规范，易于理解。")
            
        if long_lines_count > len(non_empty_lines) * 0.1:
            style_feedback.append(f"代码中有{long_lines_count}行过长（超过80字符），影响可读性。")
            result['suggestions'].append("避免过长的代码行，适当拆分复杂语句。")
        
        # 组合反馈
        result['structure_feedback'] = " ".join(structure_feedback)
        result['style_feedback'] = " ".join(style_feedback)
        
        # 如果建议不足3条，添加通用建议
        if len(result['suggestions']) < 1:
            result['suggestions'].append("考虑添加异常处理，提高代码健壮性。")
            
        # 确保分数在合理范围内
        for key in ['algorithm_score', 'style_score', 'functionality_score', 'efficiency_score']:
            result[key] = max(0, min(100, result[key]))
            
    except Exception as e:
        print(f"分析代码质量时出错: {type(e).__name__}")
        
        # 设置默认反馈
        result['structure_feedback'] = "无法分析代码结构。"
        result['style_feedback'] = "无法分析代码风格。"
        if not result['suggestions']:
            result['suggestions'].append("确保代码语法正确，并包含必要的结构。")
    
    return result
