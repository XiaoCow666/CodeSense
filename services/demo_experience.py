"""面向公开体验入口的稳定演示数据。

演示数据不是一次性测试夹具：公开体验入口、教师看板和学生思维竞技场都依赖同一组
记录。因此这里采用“按业务唯一键补齐”的方式，重复调用只会补缺，不会删除学生在
体验过程中产生的会话、提交或日志。
"""

import json
from dataclasses import dataclass
from datetime import datetime as dt

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


DEMO_TEACHER_ID = 'demo_t_001'
DEMO_TEACHER_USERNAME = 'teacher_demo'
DEMO_TEACHER_PASSWORD = '123456'
DEMO_STUDENT_ID = 'demo_s_001'
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
    )


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
        and assignment.title == DEMO_ASSIGNMENT_TITLE
        and assignment.creator_id == DEMO_TEACHER_ID
        and DEMO_CLASS_NAME in assignment.get_target_class_list()
    )
