"""Seed a complete demo workspace inside the current temporary database."""

import json
from dataclasses import dataclass
from datetime import datetime as dt, timedelta

from models import (
    AbilityTrend,
    Assignment,
    AssignmentKnowledgePoint,
    AssignmentThinkingPreset,
    Class,
    KnowledgePointScore,
    StudentRoster,
    Submission,
    TeacherAISuggestion,
    TestCase,
    User,
    db,
)
from services.demo_database import (
    DEMO_STUDENT_ID,
    DEMO_TEACHER_ID,
    DemoRun,
    _db_path,
    current_demo_run_id,
)


DEMO_TEACHER_USERNAME = 'teacher_demo'
DEMO_TEACHER_PASSWORD = '123456'
DEMO_STUDENT_USERNAME = 'student_demo_good'
DEMO_STUDENT_PASSWORD = '123456'
DEMO_CLASS_NAME = '软件工程24-演示班'
DEMO_ASSIGNMENT_TITLE = '演示作业一：循环与斐波那契数列'
DEMO_SECOND_ASSIGNMENT_TITLE = '演示作业二：二叉树遍历与归并算法'


@dataclass(frozen=True)
class DemoExperience:
    """初始化后的演示体验关键记录。"""

    teacher_id: str
    student_id: str
    class_id: int
    assignment_id: int
    second_assignment_id: int


def _json(value):
    return json.dumps(value, ensure_ascii=False)


def _ensure_user(student_id, username, usertype, full_name, password, **attrs):
    user = User.query.filter_by(student_id=student_id).first()
    is_new = user is None
    if not user:
        user = User(
            student_id=student_id,
            username=username,
            usertype=usertype,
            full_name=full_name,
        )
        db.session.add(user)

    # 演示账号的登录凭据需要始终可用，但不触碰提交、能力分析等体验状态。
    user.username = username
    user.usertype = usertype
    user.full_name = full_name
    user.password = password
    for key, value in attrs.items():
        if value is not None and (is_new or getattr(user, key, None) in (None, '')):
            setattr(user, key, value)
    return user


def _set_unique_email(user, email):
    if not email:
        return
    owner = User.query.filter(User.email == email, User.student_id != user.student_id).first()
    if not owner:
        user.email = email


def _ensure_class(teacher):
    demo_class = Class.query.filter_by(name=DEMO_CLASS_NAME).first()
    if not demo_class:
        demo_class = Class(name=DEMO_CLASS_NAME)
        db.session.add(demo_class)
    demo_class.school = '酷森思大学'
    demo_class.college = '计算机学院'
    demo_class.major = '软件工程'
    demo_class.grade = '2024'
    demo_class.teacher_id = teacher.student_id
    db.session.flush()
    return demo_class


def _ensure_roster(student_id, full_name, demo_class, registered_user_id=None):
    roster = StudentRoster.query.filter_by(student_id=student_id).first()
    if not roster:
        roster = StudentRoster(student_id=student_id, full_name=full_name)
        db.session.add(roster)
    roster.full_name = full_name
    roster.class_id = demo_class.id
    roster.class_name_snapshot = demo_class.name
    roster.imported_by = DEMO_TEACHER_ID
    roster.is_registered = registered_user_id is not None
    roster.registered_user_id = registered_user_id
    return roster


def _ensure_assignment(title, description, difficulty, demo_class):
    assignment = Assignment.query.filter_by(
        title=title,
        creator_id=DEMO_TEACHER_ID,
    ).first()
    if not assignment:
        assignment = Assignment(title=title, creator_id=DEMO_TEACHER_ID)
        db.session.add(assignment)
    assignment.description = description
    assignment.target_classes = demo_class.name
    assignment.difficulty_level = difficulty
    return assignment


def _ensure_assignment_knowledge(assignment, knowledge_point, weight, difficulty):
    record = AssignmentKnowledgePoint.query.filter_by(
        assignment_id=assignment.id,
        knowledge_point=knowledge_point,
    ).first()
    if not record:
        record = AssignmentKnowledgePoint(
            assignment_id=assignment.id,
            knowledge_point=knowledge_point,
        )
        db.session.add(record)
    record.weight = weight
    record.difficulty = difficulty
    record.auto_detected = False


def _ensure_test_case(assignment, input_data, expected_output, is_public, order_index):
    test_case = TestCase.query.filter_by(
        assignment_id=assignment.id,
        input_data=input_data,
        expected_output=expected_output,
    ).first()
    if not test_case:
        test_case = TestCase(
            assignment_id=assignment.id,
            input_data=input_data,
            expected_output=expected_output,
        )
        db.session.add(test_case)
    test_case.is_public = is_public
    test_case.order_index = order_index


def _ensure_submission(student_id, assignment_id, code, score, status, feedback, ai_feedback,
                       sandbox_status, sandbox_passed, sandbox_total, submitted_at=None):
    submission = Submission.query.filter_by(
        student_id=student_id,
        assignment_id=assignment_id,
    ).order_by(Submission.id.asc()).first()
    if not submission:
        submission = Submission(
            student_id=student_id,
            assignment_id=assignment_id,
            code=code,
        )
        db.session.add(submission)
    # 只维护演示样例提交的内容；后续用户新增提交会获得自己的新记录。
    submission.code = code
    submission.score = score
    submission.status = status
    submission.feedback = feedback
    submission.ai_feedback = ai_feedback
    submission.sandbox_status = sandbox_status
    submission.sandbox_passed = sandbox_passed
    submission.sandbox_total = sandbox_total
    if submitted_at and not submission.submitted_at:
        submission.submitted_at = submitted_at
    return submission


def _ensure_knowledge_score(student_id, knowledge_point, score, attempts, correct, difficulty):
    record = KnowledgePointScore.query.filter_by(
        student_id=student_id,
        knowledge_point=knowledge_point,
    ).first()
    if not record:
        record = KnowledgePointScore(
            student_id=student_id,
            knowledge_point=knowledge_point,
        )
        db.session.add(record)
    record.score = score
    record.total_attempts = attempts
    record.correct_attempts = correct
    record.average_difficulty = difficulty
    if not record.last_updated:
        record.last_updated = dt.utcnow()
    return record


def _ensure_preset(assignment):
    key_steps = [
        '先读入 N，并明确需要输出前 N 项斐波那契数列。',
        '用两个变量保存相邻的两个数，循环中根据前两项得到下一项。',
        '每次得到新项后更新两个变量并输出，注意 N 为 0 或 1 的边界。',
    ]
    code_blocks = [
        {
            'id': 'fib-include',
            'code': '#include <iostream>\n#include <vector>',
            'label': '引入输入输出与动态数组',
            'indent': 0,
            'phase': 1,
            'part_name': '主程序',
            'part_header': '',
            'part_footer': '',
        },
        {
            'id': 'fib-main',
            'code': 'int main() {',
            'label': '定义主函数',
            'indent': 0,
            'phase': 1,
            'part_name': '主程序',
            'part_header': '',
            'part_footer': '    return 0;\n}',
        },
        {
            'id': 'fib-input',
            'code': 'int n; std::cin >> n;\nstd::vector<long long> fib(n);',
            'label': '读入 N 并准备存储空间',
            'indent': 1,
            'phase': 1,
            'part_name': '主程序',
            'part_header': 'int main() {',
            'part_footer': '    return 0;\n}',
        },
        {
            'id': 'fib-base',
            'code': 'if (n > 0) fib[0] = 0;\nif (n > 1) fib[1] = 1;',
            'label': '处理前两项和边界情况',
            'indent': 1,
            'phase': 1,
            'part_name': '主程序',
            'part_header': 'int main() {',
            'part_footer': '    return 0;\n}',
        },
        {
            'id': 'fib-loop',
            'code': 'for (int i = 2; i < n; ++i) {\n    fib[i] = fib[i - 1] + fib[i - 2];\n}',
            'label': '循环计算当前项：前两项相加',
            'indent': 1,
            'phase': 2,
            'part_name': '主程序',
            'part_header': 'int main() {',
            'part_footer': '    return 0;\n}',
        },
        {
            'id': 'fib-output',
            'code': 'for (int i = 0; i < n; ++i) {\n    if (i) std::cout << " ";\n    std::cout << fib[i];\n}',
            'label': '按顺序输出结果',
            'indent': 1,
            'phase': 2,
            'part_name': '主程序',
            'part_header': 'int main() {',
            'part_footer': '    return 0;\n}',
        },
    ]
    noise_blocks = [
        {
            'id': 'noise-fib-sort',
            'code': 'std::sort(fib.begin(), fib.end());',
            'label': '先排序再输出（干扰项）',
            'indent': 1,
            'phase': 2,
            'part_name': '主程序',
            'part_header': 'int main() {',
            'part_footer': '    return 0;\n}',
        },
    ]
    quiz_steps = [
        {
            'step_id': 1,
            'part_name': '主程序',
            'type': 'choice',
            'question': '当 N 大于 1 时，第 i 项应由哪两项计算得到？',
            'options': ['fib[i - 1] + fib[i - 2]', 'fib[i] + fib[i + 1]', 'fib[i - 1] * 2'],
            'correct_answer': 'fib[i - 1] + fib[i - 2]',
            'explanation': '斐波那契数列的当前项等于前两项之和。',
        },
        {
            'step_id': 2,
            'part_name': '主程序',
            'type': 'fill',
            'question': '补全循环条件，确保从第三项计算到第 N 项。',
            'context_before': 'for (int i = 2; i <',
            'context_after': '; ++i) { ... }',
            'blank_hint': '输入循环上界',
            'correct_answer': 'n',
            'code_line': 'for (int i = 2; i < n; ++i) {',
            'indent': 1,
            'explanation': 'i 从 2 开始，直到 i 小于 n，正好覆盖剩余项。',
        },
        {
            'step_id': 3,
            'part_name': '主程序',
            'type': 'choice',
            'question': '为什么要先判断 N 是否大于 0 和 1？',
            'options': ['避免访问不存在的数组位置', '为了让排序更快', '因为循环不能使用整数'],
            'correct_answer': '避免访问不存在的数组位置',
            'explanation': 'N 为 0 或 1 时，数组中可用的位置不同，需要先处理边界。',
        },
    ]
    difficulty_config = {
        'feynman_rounds': 2,
        'student_persona': 'curious',
        'guided_questions': [
            '如果 N 等于 0，程序应该输出什么？',
            '循环从第几项开始，为什么？',
            '如何保证输出顺序与数列顺序一致？',
        ],
    }
    reference_code = """#include <iostream>
#include <vector>

int main() {
    int n;
    std::cin >> n;
    std::vector<long long> fib(n);
    if (n > 0) fib[0] = 0;
    if (n > 1) fib[1] = 1;
    for (int i = 2; i < n; ++i) {
        fib[i] = fib[i - 1] + fib[i - 2];
    }
    for (int i = 0; i < n; ++i) {
        if (i) std::cout << ' ';
        std::cout << fib[i];
    }
    return 0;
}"""

    preset = AssignmentThinkingPreset.query.filter_by(assignment_id=assignment.id).first()
    if not preset:
        preset = AssignmentThinkingPreset(assignment_id=assignment.id)
        db.session.add(preset)
    preset.reference_code = reference_code
    preset.key_steps = _json(key_steps)
    preset.code_blocks = _json(code_blocks)
    preset.noise_blocks = _json(noise_blocks)
    preset.quiz_steps = _json(quiz_steps)
    preset.difficulty_config = _json(difficulty_config)
    preset.algorithm_summary = (
        '算法流程：先读取 N 并处理 N 为 0 或 1 的边界；然后从第三项开始，'
        '用前两项之和计算当前项；最后按下标顺序输出全部结果。'
    )
    preset.status = 'ready'
    preset.error_message = None
    return preset


def _ensure_tree_preset(assignment):
    """Create a deterministic teaching preset for the second demo assignment."""
    key_steps = [
        '先确认二叉树的根节点，并理解中序遍历的访问顺序。',
        '递归处理左子树，再访问当前节点，最后处理右子树。',
        '将遍历结果按顺序输出，并比较递归与显式栈的空间开销。',
    ]
    code_blocks = [
        {
            'id': 'tree-include',
            'code': '#include <iostream>\n#include <vector>\n#include <stack>',
            'label': '引入输入输出、数组与栈',
            'indent': 0,
            'phase': 1,
            'part_name': '遍历函数',
            'part_header': '',
            'part_footer': '',
        },
        {
            'id': 'tree-node',
            'code': 'struct Node { int value; Node* left; Node* right; };',
            'label': '定义二叉树节点结构',
            'indent': 0,
            'phase': 1,
            'part_name': '遍历函数',
            'part_header': '',
            'part_footer': '',
        },
        {
            'id': 'tree-base',
            'code': 'void inorder(Node* root) {\n    if (!root) return;',
            'label': '处理空节点并进入遍历函数',
            'indent': 0,
            'phase': 1,
            'part_name': '遍历函数',
            'part_header': '',
            'part_footer': '\n}',
        },
        {
            'id': 'tree-left',
            'code': 'inorder(root->left);',
            'label': '先遍历左子树',
            'indent': 1,
            'phase': 2,
            'part_name': '遍历函数',
            'part_header': 'void inorder(Node* root) {',
            'part_footer': '}',
        },
        {
            'id': 'tree-visit',
            'code': 'std::cout << root->value << " ";',
            'label': '访问并输出当前节点',
            'indent': 1,
            'phase': 2,
            'part_name': '遍历函数',
            'part_header': 'void inorder(Node* root) {',
            'part_footer': '}',
        },
        {
            'id': 'tree-right',
            'code': 'inorder(root->right);\n}',
            'label': '最后遍历右子树并结束函数',
            'indent': 1,
            'phase': 2,
            'part_name': '遍历函数',
            'part_header': 'void inorder(Node* root) {',
            'part_footer': '}',
        },
    ]
    noise_blocks = [
        {
            'id': 'noise-tree-root',
            'code': 'std::cout << root->value << " ";',
            'label': '进入函数后立即输出根节点（干扰项）',
            'indent': 1,
            'phase': 1,
            'part_name': '遍历函数',
            'part_header': 'void inorder(Node* root) {',
            'part_footer': '}',
        },
    ]
    quiz_steps = [
        {
            'step_id': 1,
            'part_name': '遍历函数',
            'type': 'choice',
            'question': '中序遍历访问节点的顺序是什么？',
            'options': ['左子树、当前节点、右子树', '当前节点、左子树、右子树', '右子树、当前节点、左子树'],
            'correct_answer': '左子树、当前节点、右子树',
            'explanation': '中序遍历的核心顺序是 Left-Root-Right。',
        },
        {
            'step_id': 2,
            'part_name': '遍历函数',
            'type': 'fill',
            'question': '递归函数的终止条件应检查指针是否为？',
            'context_before': 'if (!root) ',
            'context_after': 'return;',
            'blank_hint': '输入布尔条件',
            'correct_answer': 'return',
            'code_line': 'if (!root) return;',
            'indent': 1,
            'explanation': '遇到空节点时立即返回，避免访问空指针。',
        },
        {
            'step_id': 3,
            'part_name': '遍历函数',
            'type': 'choice',
            'question': '递归中序遍历的额外空间主要来自哪里？',
            'options': ['递归调用栈', '输入数组的排序', '输出流缓冲区'],
            'correct_answer': '递归调用栈',
            'explanation': '递归深度与树高相关，显式栈可以把它转换为可见的数据结构。',
        },
    ]
    difficulty_config = {
        'feynman_rounds': 3,
        'student_persona': 'curious',
        'guided_questions': [
            '为什么中序遍历在二叉搜索树上会得到有序序列？',
            '最坏情况下递归深度是多少？',
            '如何用显式栈改写递归遍历？',
        ],
    }
    reference_code = """#include <iostream>

struct Node {
    int value;
    Node* left;
    Node* right;
};

void inorder(Node* root) {
    if (!root) return;
    inorder(root->left);
    std::cout << root->value << ' ';
    inorder(root->right);
}

int main() {
    return 0;
}"""

    preset = AssignmentThinkingPreset.query.filter_by(assignment_id=assignment.id).first()
    if not preset:
        preset = AssignmentThinkingPreset(assignment_id=assignment.id)
        db.session.add(preset)
    preset.reference_code = reference_code
    preset.key_steps = _json(key_steps)
    preset.code_blocks = _json(code_blocks)
    preset.noise_blocks = _json(noise_blocks)
    preset.quiz_steps = _json(quiz_steps)
    preset.difficulty_config = _json(difficulty_config)
    preset.algorithm_summary = (
        '算法流程：从根节点开始，先递归访问左子树，再输出当前节点，最后访问右子树；'
        '遇到空节点立即返回，并比较递归调用栈与显式栈的空间开销。'
    )
    preset.status = 'ready'
    preset.error_message = None
    return preset


def _ensure_trend(student_id):
    trend_data = {
        'trend': '基础算法理解较稳定，循环控制与边界处理表现较好。',
        'improvement': '下一步可尝试减少额外存储，并解释空间复杂度。',
        'suggestions': [
            '继续练习循环不变量和边界条件。',
            '尝试用 O(1) 额外空间保存相邻两项。',
            '完成演示作业二，巩固树遍历思路。',
        ],
    }
    trend = AbilityTrend.query.filter_by(student_id=student_id).first()
    if not trend:
        trend = AbilityTrend(student_id=student_id)
        db.session.add(trend)
    if not trend.analysis_markdown:
        trend.analysis_markdown = (
            '## 能力概览\n\n'
            '你已经能够把题目拆成“输入、循环计算、输出”三个模块。\n\n'
            '## 下一步建议\n\n'
            '- 继续关注 `N=0`、`N=1` 等边界情况。\n'
            '- 尝试比较数组方案与滚动变量方案的空间复杂度。'
        )
    if not trend.trend_data:
        trend.trend_data = _json(trend_data)
    trend.submissions_count = max(trend.submissions_count or 0, 12)
    if trend.status in (None, 'pending', 'processing', 'outdated', 'failed'):
        trend.status = 'completed'
    if not trend.last_updated:
        trend.last_updated = dt.utcnow()
    return trend


def _ensure_teacher_suggestion(demo_class):
    suggestion = TeacherAISuggestion.query.filter_by(class_id=demo_class.id).first()
    if not suggestion:
        suggestion = TeacherAISuggestion(
            class_id=demo_class.id,
            teacher_id=DEMO_TEACHER_ID,
        )
        db.session.add(suggestion)
    suggestion.teacher_id = DEMO_TEACHER_ID
    suggestion.status = 'completed'
    suggestion.suggestion_markdown = """# 软件工程24-演示班学情建议

## 需要优先关注

- **孙三（风险）**：循环控制与二叉树知识点得分偏低，最近一次提交未通过全部测试。
- **李四（未注册）**：已在花名册中，但还没有登录系统，建议提醒完成注册。

## 课堂建议

1. 用斐波那契作业演示边界条件和循环不变量。
2. 让学生比较数组方案与滚动变量方案的空间复杂度。
3. 下一次课安排一次二叉树遍历的分步练习。
"""
    suggestion.suggestion_json = _json({
        'focus_students': [
            {'student_id': 'demo_s_003', 'name': '孙三（风险）', 'reason': '循环控制与二叉树得分偏低'},
            {'student_id': 'demo_s_004', 'name': '李四（未注册）', 'reason': '花名册账号尚未注册'},
        ],
        'weak_knowledge_points': ['循环控制', '二叉树'],
        'recommended_assignments': [DEMO_ASSIGNMENT_TITLE],
    })
    suggestion.last_updated = suggestion.last_updated or dt.utcnow()
    return suggestion


def _refresh_assignment_stats(assignment):
    submissions = Submission.query.filter_by(assignment_id=assignment.id).all()
    scores = [submission.score for submission in submissions if submission.score is not None]
    assignment.count = len(submissions)
    assignment.total_score = 100
    assignment.average_score = round(sum(scores) / len(scores), 1) if scores else 0.0


def ensure_demo_experience():
    """补齐公开体验所需数据，并返回固定入口信息。

    所有写入发生在当前 SQLAlchemy 会话中，最后只提交一次；异常由调用方处理并回滚。
    既有体验会话、提交、日志不会被删除或重置。
    """
    teacher = _ensure_user(
        DEMO_TEACHER_ID,
        DEMO_TEACHER_USERNAME,
        '教师',
        '李老师（演示）',
        DEMO_TEACHER_PASSWORD,
    )
    _set_unique_email(teacher, 'teacher_demo@codesense.edu')
    demo_class = _ensure_class(teacher)

    student = _ensure_user(
        DEMO_STUDENT_ID,
        DEMO_STUDENT_USERNAME,
        '学生',
        '赵一（优秀）',
        DEMO_STUDENT_PASSWORD,
        class_id=demo_class.id,
        class_name=demo_class.name,
        user_ascore=4.8,
        submit_count=12,
    )
    _set_unique_email(student, 'student_demo_good@codesense.edu')

    middle_student = _ensure_user(
        'demo_s_002',
        'student_demo_mid',
        '学生',
        '钱二（中等）',
        DEMO_STUDENT_PASSWORD,
        class_id=demo_class.id,
        class_name=demo_class.name,
        user_ascore=3.5,
        submit_count=7,
    )
    risk_student = _ensure_user(
        'demo_s_003',
        'student_demo_risk',
        '学生',
        '孙三（风险）',
        DEMO_STUDENT_PASSWORD,
        class_id=demo_class.id,
        class_name=demo_class.name,
        user_ascore=1.8,
        submit_count=2,
    )
    db.session.flush()

    _ensure_roster(DEMO_STUDENT_ID, student.full_name, demo_class, DEMO_STUDENT_ID)
    _ensure_roster('demo_s_002', middle_student.full_name, demo_class, 'demo_s_002')
    _ensure_roster('demo_s_003', risk_student.full_name, demo_class, 'demo_s_003')
    _ensure_roster('demo_s_004', '李四（未注册）', demo_class)

    guided_assignment = _ensure_assignment(
        DEMO_ASSIGNMENT_TITLE,
        '使用循环计算斐波那契数列的前 N 项，并说明边界条件与空间复杂度。',
        2,
        demo_class,
    )
    second_assignment = _ensure_assignment(
        DEMO_SECOND_ASSIGNMENT_TITLE,
        '实现二叉树的中序遍历与归并输出，比较递归和迭代写法的差异。',
        4,
        demo_class,
    )
    db.session.flush()

    _ensure_assignment_knowledge(guided_assignment, '循环控制', 1.0, 2.0)
    _ensure_assignment_knowledge(guided_assignment, '边界条件', 0.8, 2.0)
    _ensure_assignment_knowledge(second_assignment, '二叉树', 1.0, 4.0)
    _ensure_assignment_knowledge(second_assignment, '递归', 0.8, 4.0)

    _ensure_test_case(guided_assignment, '5', '0 1 1 2 3', True, 1)
    _ensure_test_case(guided_assignment, '8', '0 1 1 2 3 5 8 13', False, 2)
    _ensure_test_case(guided_assignment, '0', '', True, 3)

    for student_id, scores in {
        DEMO_STUDENT_ID: (95.0, 88.0),
        'demo_s_002': (78.0, 65.0),
        'demo_s_003': (42.0, 20.0),
    }.items():
        _ensure_knowledge_score(student_id, '循环控制', scores[0], 5, 5 if scores[0] > 90 else 3, 2.0)
        _ensure_knowledge_score(student_id, '二叉树', scores[1], 4, 3 if scores[1] > 80 else 1, 4.0)

    _ensure_submission(
        DEMO_STUDENT_ID,
        guided_assignment.id,
        '// 演示学生：完整的 Fibonacci 解法\nint main() { return 0; }',
        100,
        'accepted',
        '已通过全部样例测试，边界条件处理清晰。',
        '思路完整，建议继续关注空间复杂度优化。',
        'passed',
        3,
        3,
    )
    _ensure_submission(
        'demo_s_002',
        guided_assignment.id,
        '// 演示学生：基本循环解法\nint main() { return 0; }',
        80,
        'accepted',
        '主要逻辑正确，边界处理仍可加强。',
        '建议检查 N 为 0 和 1 时的行为。',
        'partial',
        2,
        3,
    )
    _ensure_submission(
        'demo_s_003',
        guided_assignment.id,
        '// 演示学生：尚未完成边界处理\nint main() { return 0; }',
        40,
        'wrong_answer',
        '循环主体方向正确，但没有覆盖全部边界情况。',
        '建议先画出 N=0、N=1、N=2 的执行过程。',
        'failed',
        1,
        3,
    )
    _refresh_assignment_stats(guided_assignment)
    _refresh_assignment_stats(second_assignment)

    _ensure_trend(DEMO_STUDENT_ID)
    _ensure_teacher_suggestion(demo_class)
    _ensure_preset(guided_assignment)

    db.session.commit()
    return DemoExperience(
        teacher_id=teacher.student_id,
        student_id=student.student_id,
        class_id=demo_class.id,
        assignment_id=guided_assignment.id,
        second_assignment_id=second_assignment.id,
    )


# This explicit development/test-only seeder remains available for the legacy
# ``/classes/seed-demo-data`` and ``/sandbox-login`` workflow. Public visitors
# never call it; ``/demo-login`` always uses ``seed_demo_experience`` below.
seed_legacy_demo_experience = ensure_demo_experience


def is_demo_guided_session(thinking_session):
    """判断会话是否属于公开演示学生的共享引导作业。"""
    if not thinking_session or thinking_session.student_id != DEMO_STUDENT_ID:
        return False
    assignment = Assignment.query.get(thinking_session.assignment_id)
    return is_demo_guided_assignment(assignment)


def is_demo_guided_assignment(assignment):
    """判断作业是否属于公开演示的三阶段引导作业。"""
    return bool(
        assignment
        and assignment.title in {
            DEMO_ASSIGNMENT_TITLE,
            DEMO_SECOND_ASSIGNMENT_TITLE,
        }
        and assignment.creator_id == DEMO_TEACHER_ID
        and DEMO_CLASS_NAME in assignment.get_target_class_list()
    )


# ---------------------------------------------------------------------------
# Per-session fixture set
# ---------------------------------------------------------------------------
#
# The original fixture above was kept as a compatibility reference while the
# public demo was migrated away from the formal database.  The definitions
# below are the active implementation.  They deliberately use only the
# currently-bound SQLAlchemy session; the caller must activate a DemoRun
# before invoking seed_demo_experience().

from flask import has_request_context, session as flask_session

from services.demo_database import (
    DEMO_ROLE_SESSION_KEY,
    is_active_demo_run,
)


C_LANGUAGE_POINTS = (
    ('basic_syntax', '基础语法'),
    ('pointer', '指针'),
    ('function', '函数'),
    ('array', '数组'),
    ('string', '字符串'),
    ('struct', '结构体'),
    ('file_io', '文件操作'),
    ('dynamic_memory', '动态内存'),
    ('linked_list', '链表'),
    ('tree', '树'),
    ('sorting', '排序算法'),
    ('searching', '搜索算法'),
    ('recursion', '递归'),
)


DEMO_STUDENT_SPECS = (
    ('demo_s_001', 'student_demo_good', '赵一（优秀）', 4.6),
    ('demo_s_002', 'student_demo_mid', '钱二（中等）', 3.7),
    ('demo_s_003', 'student_demo_risk', '孙三（风险）', 2.2),
    ('demo_s_004', 'student_demo_04', '周四', 3.1),
    ('demo_s_005', 'student_demo_05', '吴五', 4.1),
    ('demo_s_006', 'student_demo_06', '郑六', 2.8),
    ('demo_s_007', 'student_demo_07', '王七', 3.5),
    ('demo_s_008', 'student_demo_08', '冯八', 4.3),
    ('demo_s_009', 'student_demo_09', '陈九', 2.6),
    ('demo_s_010', 'student_demo_10', '褚十', 3.9),
    ('demo_s_011', 'student_demo_11', '卫十一', 4.0),
    ('demo_s_012', 'student_demo_12', '蒋十二', 3.3),
)


DEMO_ASSIGNMENT_SPECS = (
    {
        'key': 'guided_fibonacci',
        'title': DEMO_ASSIGNMENT_TITLE,
        'description': '使用循环计算斐波那契数列的前 N 项，并说明边界条件与空间复杂度。',
        'difficulty': 2,
        'knowledge': [('basic_syntax', 0.8, 1.5), ('array', 0.7, 1.8), ('recursion', 0.5, 2.0)],
        'cases': [('5', '0 1 1 2 3', True), ('8', '0 1 1 2 3 5 8 13', False), ('0', '', True)],
    },
    {
        'key': 'guided_tree',
        'title': DEMO_SECOND_ASSIGNMENT_TITLE,
        'description': '实现二叉树的中序遍历，比较递归写法与显式栈写法的空间开销。',
        'difficulty': 4,
        'knowledge': [('tree', 1.0, 4.0), ('recursion', 0.9, 3.5), ('struct', 0.8, 3.5)],
        'cases': [('1 2 3', '2 1 3', True), ('7 3 9 1 5', '1 3 5 7 9', True)],
    },
    {
        'key': 'pointer_array',
        'title': '作业三：指针与数组的边界管理',
        'description': '使用指针遍历整数数组，完成最大值、最小值和平均值计算，并处理空数组。',
        'difficulty': 3,
        'knowledge': [('pointer', 1.0, 3.0), ('array', 1.0, 2.5), ('function', 0.7, 2.0)],
        'cases': [('4\\n3 1 9 2', '9 1 3.75', True), ('0', 'empty', False)],
    },
    {
        'key': 'linked_list',
        'title': '作业四：链表节点插入与释放',
        'description': '定义链表节点，完成头插、尾插和遍历操作，说明动态内存释放时机。',
        'difficulty': 4,
        'knowledge': [('linked_list', 1.0, 4.0), ('dynamic_memory', 1.0, 4.0), ('struct', 0.8, 3.5)],
        'cases': [('3\\n1 2 3', '1 2 3', True), ('0', 'empty', True)],
    },
    {
        'key': 'file_io',
        'title': '作业五：文本文件统计器',
        'description': '读取文本文件并统计字符、单词和行数，正确处理文件打开失败的情况。',
        'difficulty': 3,
        'knowledge': [('file_io', 1.0, 3.0), ('string', 0.8, 2.5), ('basic_syntax', 0.6, 1.5)],
        'cases': [('hello\\nworld', '2 lines', True), ('', '0 lines', True)],
    },
    {
        'key': 'sorting_search',
        'title': '作业六：排序与二分查找综合练习',
        'description': '实现插入排序和二分查找，比较不同数据规模下的时间复杂度。',
        'difficulty': 4,
        'knowledge': [('sorting', 1.0, 3.5), ('searching', 1.0, 3.5), ('function', 0.7, 2.0)],
        'cases': [('5\\n5 2 4 1 3', '1 2 3 4 5', True), ('3\\n2 4 6', 'not found', False)],
    },
)


def _structured_demo_feedback(score, seed):
    """Return historical evaluator-shaped feedback on the 0–5 scale."""
    offsets = (0.2, -0.1, 0.1, -0.2, 0.0)
    dimensions = {
        key: round(max(0.0, min(5.0, float(score) + offsets[(seed + index) % len(offsets)])), 1)
        for index, key in enumerate((
            'algorithm_score',
            'style_score',
            'functionality_score',
            'efficiency_score',
            'readability_score',
        ))
    }
    dimensions.update({
        'overall_score': round(float(score), 1),
        'strengths': ['能够拆分输入、处理和输出流程', '变量命名与函数边界较清楚'],
        'suggestions': ['补充边界条件测试', '尝试解释时间复杂度与空间复杂度'],
    })
    return _json(dimensions)


def _ensure_history_submission(
    student_id,
    assignment_id,
    score,
    attempt_index,
    submitted_at,
    assignment_title,
):
    """Upsert one deterministic historical submission without touching new work."""
    marker = f'/* CodeSense demo history: {student_id}/{assignment_id}/{attempt_index} */'
    submission = Submission.query.filter(
        Submission.student_id == student_id,
        Submission.assignment_id == assignment_id,
        Submission.code.like(f'{marker}%'),
    ).first()
    if not submission:
        submission = Submission(
            student_id=student_id,
            assignment_id=assignment_id,
            code=marker,
        )
        db.session.add(submission)

    score = max(0, min(5, int(round(score))))
    passed = 3 if score >= 4 else 2 if score >= 3 else 1 if score > 0 else 0
    submission.code = marker + f'\n/* {assignment_title} 示例历史记录 */\nint main(void) {{ return {score}; }}'
    submission.score = score
    submission.language = 'c'
    submission.status = 'evaluated'
    submission.feedback = (
        '本次提交已完成基础评测。' if score >= 3
        else '核心思路已经出现，建议继续检查边界条件和指针安全。'
    )
    submission.ai_feedback = _structured_demo_feedback(score, attempt_index)
    submission.sandbox_status = 'passed' if passed == 3 else 'partial' if passed else 'failed'
    submission.sandbox_passed = passed
    submission.sandbox_total = 3
    submission.sandbox_detail = _json({
        'cases': [
            {'index': 1, 'status': 'passed' if passed >= 1 else 'failed'},
            {'index': 2, 'status': 'passed' if passed >= 2 else 'failed'},
            {'index': 3, 'status': 'passed' if passed >= 3 else 'failed'},
        ]
    })
    submission.submitted_at = submitted_at
    return submission


def _seed_demo_knowledge_scores(student, student_index):
    """Seed all C-language dimensions with meaningful 0–100 profile values."""
    base = float(student.user_ascore or 3.0) * 20.0
    for point_index, (key, _name) in enumerate(C_LANGUAGE_POINTS):
        variation = ((student_index * 7 + point_index * 11) % 19) - 9
        score = round(max(28.0, min(96.0, base + 18.0 + variation)), 1)
        attempts = 2 + ((student_index + point_index) % 5)
        correct = max(0, min(attempts, round(attempts * score / 100.0)))
        _ensure_knowledge_score(
            student.student_id,
            key,
            score,
            attempts,
            correct,
            round(1.5 + ((student_index + point_index) % 4) * 0.6, 1),
        )


def _ensure_pending_trend(student_id, submission_count, student_index):
    """Create numeric trend history while leaving narrative generation to real AI."""
    trend = AbilityTrend.query.filter_by(student_id=student_id).first()
    if not trend:
        trend = AbilityTrend(student_id=student_id, status='pending')
        db.session.add(trend)

    if not trend.trend_data:
        start = 48 + ((student_index * 5) % 15)
        trend.trend_data = _json({
            'labels': [f'D-{offset}' for offset in range(13, -1, -1)],
            'scores': [
                round(max(0, min(100, start + offset * (1.5 + student_index % 3))), 1)
                for offset in range(14)
            ],
            'submission_count': submission_count,
            'source': 'demo_fixture_history',
        })
    trend.submissions_count = submission_count
    if not trend.last_updated:
        trend.last_updated = dt.utcnow()
    if not trend.analysis_markdown and trend.status not in ('failed', 'processing'):
        trend.status = 'pending'
    return trend


def _ensure_pending_teacher_suggestion(demo_class):
    suggestion = TeacherAISuggestion.query.filter_by(class_id=demo_class.id).first()
    if not suggestion:
        suggestion = TeacherAISuggestion(
            class_id=demo_class.id,
            teacher_id=DEMO_TEACHER_ID,
            status='pending',
        )
        db.session.add(suggestion)
    suggestion.teacher_id = DEMO_TEACHER_ID
    if not suggestion.suggestion_markdown and suggestion.status != 'failed':
        suggestion.status = 'pending'
    if not suggestion.last_updated:
        suggestion.last_updated = dt.utcnow()
    return suggestion


def _refresh_assignment_stats(assignment):
    """Keep assignment aggregates on the same 0–5 scale as submissions."""
    submissions = Submission.query.filter_by(assignment_id=assignment.id).all()
    scores = [submission.score for submission in submissions if submission.score is not None]
    assignment.count = len(submissions)
    assignment.total_score = sum(scores) if scores else 0
    assignment.average_score = round(sum(scores) / len(scores), 2) if scores else 0.0


def _demo_run_from_request():
    if not has_request_context():
        return None
    run_id = current_demo_run_id()
    if not run_id:
        return None
    role = flask_session.get(DEMO_ROLE_SESSION_KEY) or 'student'
    return DemoRun(
        run_id=run_id,
        role=role,
        student_id=DEMO_STUDENT_ID,
        teacher_id=DEMO_TEACHER_ID,
        db_path=str(_db_path(run_id)),
        created_at=dt.utcnow(),
    )


def seed_demo_experience(run: DemoRun) -> DemoExperience:
    """Seed one rich demo workspace into the explicitly active temporary DB."""
    if not isinstance(run, DemoRun):
        raise TypeError('seed_demo_experience 需要 DemoRun')
    if not is_active_demo_run(run.run_id):
        raise RuntimeError('体验临时数据库尚未激活，拒绝写入其他数据库')

    teacher = _ensure_user(
        DEMO_TEACHER_ID,
        DEMO_TEACHER_USERNAME,
        '教师',
        '李老师（演示）',
        DEMO_TEACHER_PASSWORD,
        user_ascore=4.8,
    )
    _set_unique_email(teacher, 'teacher_demo@codesense.edu')
    demo_class = _ensure_class(teacher)

    students = []
    for index, (student_id, username, full_name, ascore) in enumerate(DEMO_STUDENT_SPECS):
        student = _ensure_user(
            student_id,
            username,
            '学生',
            full_name,
            DEMO_STUDENT_PASSWORD,
            class_id=demo_class.id,
            class_name=demo_class.name,
            user_ascore=ascore,
        )
        _set_unique_email(student, f'{username}@demo.codesense.edu')
        students.append(student)

    db.session.flush()

    for student in students:
        _ensure_roster(student.student_id, student.full_name, demo_class, student.student_id)
    # Keep a couple of pending roster entries so class management also shows
    # the registration workflow without creating fake users for them.
    _ensure_roster('demo_r_013', '李四（未注册）', demo_class)
    _ensure_roster('demo_r_014', '何十三（待注册）', demo_class)

    assignments = {}
    now = dt.utcnow()
    for assignment_index, spec in enumerate(DEMO_ASSIGNMENT_SPECS):
        assignment = _ensure_assignment(
            spec['title'],
            spec['description'],
            spec['difficulty'],
            demo_class,
        )
        assignment.created_time = now - timedelta(days=35 - assignment_index * 4)
        assignment.due_date = now + timedelta(days=7 + assignment_index * 2)
        db.session.flush()
        for knowledge_point, weight, difficulty in spec['knowledge']:
            _ensure_assignment_knowledge(assignment, knowledge_point, weight, difficulty)
        for case_index, (input_data, expected_output, is_public) in enumerate(spec['cases']):
            _ensure_test_case(assignment, input_data, expected_output, is_public, case_index + 1)
        assignments[spec['key']] = assignment

    db.session.flush()
    assignment_list = list(assignments.values())

    # The primary demo student has a visible progression history; the other
    # students provide the teacher dashboard with enough cross-sectional data.
    for student_index, student in enumerate(students):
        _seed_demo_knowledge_scores(student, student_index)
        if student_index == 0:
            selected = (
                list(enumerate(assignment_list))
                + [(attempt_index + len(assignment_list), assignment)
                   for attempt_index, assignment in enumerate(assignment_list)]
            )
        else:
            selected = [
                (offset, assignment_list[(student_index + offset) % len(assignment_list)])
                for offset in range(4)
            ]
        for attempt_index, assignment in selected:
            score = ((student_index * 2 + attempt_index * 3) % 5) + 1
            if student_index == 0:
                score = min(5, max(2, 3 + ((attempt_index + 1) % 3)))
            submitted_at = now - timedelta(
                days=(student_index * 2 + attempt_index) % 14,
                hours=(attempt_index * 3) % 8,
            )
            _ensure_history_submission(
                student.student_id,
                assignment.id,
                score,
                attempt_index,
                submitted_at,
                assignment.title,
            )

    for assignment in assignment_list:
        _refresh_assignment_stats(assignment)
    for student_index, student in enumerate(students):
        submissions_count = Submission.query.filter_by(student_id=student.student_id).count()
        student.submit_count = submissions_count
        _ensure_pending_trend(student.student_id, submissions_count, student_index)

    demo_class.student_count = len(students)
    demo_class.avg_score = round(
        sum(student.user_ascore for student in students) / len(students), 2
    )
    demo_class.total_submissions = Submission.query.join(User).filter(
        User.class_id == demo_class.id,
    ).count()

    _ensure_pending_teacher_suggestion(demo_class)
    _ensure_preset(assignments['guided_fibonacci'])
    _ensure_tree_preset(assignments['guided_tree'])

    db.session.commit()
    return DemoExperience(
        teacher_id=teacher.student_id,
        student_id=students[0].student_id,
        class_id=demo_class.id,
        assignment_id=assignments['guided_fibonacci'].id,
        second_assignment_id=assignments['guided_tree'].id,
    )


def ensure_demo_experience(run=None):
    """Compatibility wrapper that only works when a demo run is active."""
    run = run or _demo_run_from_request()
    if run is None:
        raise RuntimeError('公开体验数据必须写入临时数据库')
    return seed_demo_experience(run)


def get_demo_assignment_id(run_id: str, key: str = 'guided_fibonacci') -> int:
    """Return a seeded demo assignment id from the active run."""
    if not is_active_demo_run(run_id):
        raise RuntimeError('体验临时数据库尚未激活')
    title_by_key = {spec['key']: spec['title'] for spec in DEMO_ASSIGNMENT_SPECS}
    title = title_by_key.get(key)
    if not title:
        raise KeyError(f'未知的演示作业标识: {key}')
    assignment = Assignment.query.filter_by(
        title=title,
        creator_id=DEMO_TEACHER_ID,
    ).first()
    if assignment is None:
        raise LookupError(f'演示作业尚未初始化: {key}')
    return assignment.id


def ensure_demo_guided_preset(assignment):
    """Repair a known demo preset in the active temporary database.

    Guided-demo presets are deterministic teaching material. If an old worker
    marked one as generating/failed, restore it locally instead of enqueueing
    a task that would use the formal database.
    """
    if not is_demo_guided_assignment(assignment):
        return None
    if assignment.title == DEMO_SECOND_ASSIGNMENT_TITLE:
        preset = _ensure_tree_preset(assignment)
    else:
        preset = _ensure_preset(assignment)
    db.session.flush()
    return preset
