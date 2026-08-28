import json
import threading
from datetime import datetime as dt
from models import db, User, Class, KnowledgePointScore, Assignment, AssignmentKnowledgePoint, TeacherAISuggestion
from services.teacher_analytics import build_class_learning_rows
from services.llm_client import SharedLLMClient
from services.demo_database import activate_demo_run, is_active_demo_run

# 线程锁，防止重复并发生成同一班级的AI建议
_generation_locks = {}
_locks_lock = threading.Lock()

def get_generation_lock(class_id):
    with _locks_lock:
        if class_id not in _generation_locks:
            _generation_locks[class_id] = threading.Lock()
        return _generation_locks[class_id]


def _demo_database_is_available(demo_run_id):
    return not demo_run_id or is_active_demo_run(demo_run_id)


def _mark_demo_suggestion_failed(class_id, teacher_id):
    suggestion = TeacherAISuggestion.get_or_create(
        class_id=class_id,
        teacher_id=teacher_id,
    )
    if suggestion is None:
        return None
    suggestion.status = 'failed'
    suggestion.suggestion_markdown = None
    suggestion.suggestion_json = None
    suggestion.last_updated = dt.utcnow()
    db.session.commit()
    return suggestion


def generate_class_suggestions(class_id, teacher_id, demo_run_id=None):
    """
    同步生成班级学情建议，计算规则引擎结果，并可选调用LLM增强
    """
    if demo_run_id and not activate_demo_run(demo_run_id):
        return None

    lock = get_generation_lock(class_id)
    acquired = lock.acquire(blocking=False)
    if not acquired:
        # 已经在生成中，直接返回现有记录
        return TeacherAISuggestion.query.filter_by(class_id=class_id).first()

    try:
        # 更新状态为 processing
        suggestion = TeacherAISuggestion.get_or_create(class_id=class_id, teacher_id=teacher_id)
        suggestion.status = 'processing'
        db.session.commit()

        cls = Class.query.get(class_id)
        if not cls:
            suggestion.status = 'failed'
            db.session.commit()
            return None

        # 1. 获取班级所有学生和学情行
        students = User.query.filter_by(class_id=class_id, usertype='学生').all()
        student_ids = [s.student_id for s in students]

        attention_students = []
        if students:
            learning_rows = build_class_learning_rows(cls, students=students)
            for row in learning_rows:
                if row['status'] == '需关注' or row['status'] == '未开始':
                    attention_students.append({
                        'student_id': row['student'].student_id,
                        'name': row['student'].full_name or row['student'].username,
                        'risk_tags': row['risk_tags'],
                        'latest_score': row['latest_score']
                    })

        # 2. 获取弱势知识点 (班级平均分最低的前3个)
        weak_points = []
        if student_ids:
            rows = db.session.query(
                KnowledgePointScore.knowledge_point,
                db.func.avg(KnowledgePointScore.score).label('avg_score'),
                db.func.sum(KnowledgePointScore.total_attempts).label('total_attempts')
            ).filter(
                KnowledgePointScore.student_id.in_(student_ids)
            ).group_by(
                KnowledgePointScore.knowledge_point
            ).order_by(
                db.func.avg(KnowledgePointScore.score).asc()
            ).all()

            for row in rows:
                kp_code = row.knowledge_point
                kp_display = KnowledgePointScore.KNOWLEDGE_POINTS.get(kp_code, kp_code)
                weak_points.append({
                    'code': kp_code,
                    'name': kp_display,
                    'avg_score': round(float(row.avg_score), 1) if row.avg_score else 0.0,
                    'total_attempts': int(row.total_attempts) if row.total_attempts else 0
                })

        # 3. 推荐补练作业
        suggested_assignments = []
        if weak_points:
            weak_kp_codes = [wp['code'] for wp in weak_points[:3]]
            candidate_assignments = Assignment.query.join(
                AssignmentKnowledgePoint, Assignment.id == AssignmentKnowledgePoint.assignment_id
            ).filter(
                AssignmentKnowledgePoint.knowledge_point.in_(weak_kp_codes)
            ).all()

            for assign in candidate_assignments:
                if cls.name not in assign.get_target_class_list():
                    if assign.id not in [a['id'] for a in suggested_assignments]:
                        suggested_assignments.append({
                            'id': assign.id,
                            'title': assign.title,
                            'description': assign.description or '暂无描述',
                            'difficulty': {1: '简单', 2: '较易', 3: '中等', 4: '较难', 5: '困难'}.get(assign.difficulty_level, '中等')
                        })

        # 兜底生成缺省推荐
        if not suggested_assignments and weak_points:
            for wp in weak_points[:2]:
                suggested_assignments.append({
                    'id': 0,
                    'title': f'针对【{wp["name"]}】的巩固练习',
                    'description': f'建议为班级新建一份涵盖【{wp["name"]}】的编程作业，帮助学生专项突破该知识点。',
                    'difficulty': '中等'
                })

        # 4. 生成规则引擎基础 Markdown 和 JSON 数据作为备份
        rule_markdown = _generate_rule_based_markdown(cls, weak_points, attention_students, suggested_assignments)
        rule_json_dict = {
            'attention_students': [
                {
                    'student_id': s['student_id'],
                    'name': s['name'],
                    'risk_reason': f"存在{'/'.join(s['risk_tags'])}风险，最近得分 {s['latest_score'] if s['latest_score'] is not None else '无'}"
                } for s in attention_students
            ],
            'weak_knowledge_points': [
                {
                    'point_code': wp['code'],
                    'point_name': wp['name'],
                    'explanation': f"班级掌握度较低，平均分：{wp['avg_score']}/100，尝试：{wp['total_attempts']}次。建议课堂串讲基本概念。"
                } for wp in weak_points[:3]
            ],
            'suggested_assignments': [
                {
                    'title': a['title'],
                    'reason': f"针对弱势概念进行课后巩固训练。",
                    'difficulty': a['difficulty']
                } for a in suggested_assignments[:3]
            ]
        }

        # 5. 尝试大模型生成
        llm = SharedLLMClient()
        if llm.is_available():
            try:
                attention_details_str = "\n".join([
                    f"- {s['name']} ({s['student_id']}): 风险标签 {s['risk_tags']}, 最近得分 {s['latest_score']}" 
                    for s in attention_students
                ]) if attention_students else "暂无高风险学生"

                weak_points_str = "\n".join([
                    f"- {wp['name']}: {wp['avg_score']}分, 尝试 {wp['total_attempts']} 次" 
                    for wp in weak_points
                ]) if weak_points else "暂无评分数据"

                assignments_str = "\n".join([
                    f"- {a['title']} (难度: {a['difficulty']}): {a['description']}" 
                    for a in suggested_assignments[:3]
                ]) if suggested_assignments else "无推荐作业"

                messages = [
                    {
                        "role": "system",
                        "content": (
                            "你是一个专业的编程教育专家，擅长从班级学生成绩、提交活跃度、弱点概念等多维度给出点对点的教学建议。\n"
                            "请用简洁专业的中文直接输出分析内容，并在正文结束后，输出一行由 `===JSON===` 分隔的 JSON 字符串，包含系统结构。"
                        )
                    },
                    {
                        "role": "user",
                        "content": f"""请针对以下班级学情数据，为授课教师生成本周的 AI 个性化建议报告。

班级: {cls.name}
学生数: {len(students)} 人
需关注的学生:
{attention_details_str}

本班概念掌握情况(平均分):
{weak_points_str}

可供派发的关联作业:
{assignments_str}

请生成一份详细的教学建议报告，必须包含以下三个核心部分：
1. 本周重点关注学生：列出高风险学生、原因及对应的关怀建议。
2. 建议讲解知识点：针对薄弱概念，提供核心讲解策略和典型错误提醒。
3. 建议补练作业：推荐具体的练习方案。

必须按 Markdown 格式排版正文。
正文结束后，输出一行 `===JSON===`（不能有其他文字），紧接着输出以下 JSON 格式的解析字典，不要包含任何 markdown codeblock 标记:
{{
  "attention_students": [
     {{"student_id": "学号", "name": "学生姓名", "risk_reason": "具体风险和建议建议"}}
  ],
  "weak_knowledge_points": [
     {{"point_code": "概念代码", "point_name": "概念名称", "explanation": "掌握现状及对策建议"}}
  ],
  "suggested_assignments": [
     {{"title": "作业标题", "reason": "推荐原因", "difficulty": "中等/困难"}}
  ]
}}
"""
                    }
                ]

                response = llm.chat(messages, temperature=0.7, max_tokens=2500)
                if response:
                    parts = response.split('===JSON===')
                    markdown_part = parts[0].strip()
                    json_part = parts[1].strip() if len(parts) > 1 else "{}"
                    
                    # 尝试清理 markdown 代码包裹标记
                    if json_part.startswith('```'):
                        lines = json_part.splitlines()
                        if lines[0].startswith('```json') or lines[0].startswith('```'):
                            lines = lines[1:]
                        if lines[-1].startswith('```'):
                            lines = lines[:-1]
                        json_part = "\n".join(lines).strip()

                    try:
                        parsed_json = json.loads(json_part)
                        # 确保基本字段完整
                        if 'attention_students' in parsed_json and 'weak_knowledge_points' in parsed_json:
                            suggestion.suggestion_markdown = markdown_part
                            suggestion.suggestion_json = json.dumps(parsed_json, ensure_ascii=False)
                            suggestion.status = 'completed'
                            suggestion.last_updated = dt.utcnow()
                            db.session.commit()
                            return suggestion
                    except Exception as je:
                        print(f"LLM JSON 解析失败: {je}. Fallback to rule structure.")

            except Exception as le:
                print(f"LLM 接口调用或处理失败: {le}")

        # 公开体验要求使用真实 AI。没有可用模型或模型返回内容不完整时，
        # 明确记录失败，不能把规则引擎结果伪装成 AI 报告。
        if demo_run_id:
            raise RuntimeError('AI 服务不可用或未返回有效班级建议')

        # Rules-based fallback（正式账户的历史兼容行为）
        suggestion.suggestion_markdown = rule_markdown
        suggestion.suggestion_json = json.dumps(rule_json_dict, ensure_ascii=False)
        suggestion.status = 'completed'
        suggestion.last_updated = dt.utcnow()
        db.session.commit()
        return suggestion

    except Exception as e:
        db.session.rollback()
        print(f"生成AI建议失败: {e}")
        if _demo_database_is_available(demo_run_id):
            try:
                if demo_run_id:
                    _mark_demo_suggestion_failed(class_id, teacher_id)
                else:
                    suggestion = TeacherAISuggestion.get_or_create(
                        class_id=class_id,
                        teacher_id=teacher_id,
                    )
                    suggestion.status = 'failed'
                    db.session.commit()
            except Exception:
                db.session.rollback()
        return None
    finally:
        lock.release()


def _generate_rule_based_markdown(cls, weak_points, attention_students, suggested_assignments):
    markdown = f"## 班级【{cls.name}】学情 AI 个性化建议报告\n\n"
    markdown += "> [!NOTE]\n"
    markdown += "> 本报告由 CodeSense 学情分析规则引擎自动生成。大语言模型增强服务暂不可用或正在加载。\n\n"

    # 1. 重点关注学生
    markdown += "### 📌 本周重点关注学生\n"
    if attention_students:
        markdown += "根据本周的提交频率和成绩分布，以下学生需要重点关注：\n\n"
        for s in attention_students[:6]:
            tags_str = "、".join(s['risk_tags'])
            score_str = f"，最近作业最高分：{s['latest_score']}分" if s['latest_score'] is not None else "，暂无任何作业提交记录"
            markdown += f"- **{s['name']}** (学号: {s['student_id']}): 触发 **[{tags_str}]** 预警{score_str}。建议课后点对点沟通，了解学习困难。\n"
    else:
        markdown += "🎉 本班暂无触发预警的高风险学生，大家学习态度良好，请继续保持！\n"
    markdown += "\n"

    # 2. 建议讲解知识点
    markdown += "### 💡 建议讲解知识点\n"
    if weak_points:
        markdown += "基于当前班级各维度的得分数据，以下知识点得分较低，建议在接下来的课堂中进行重难点剖析或代码查错演练：\n\n"
        for wp in weak_points[:3]:
            markdown += f"- **{wp['name']}** (班级掌握度: {wp['avg_score']}/100, 累计提交 {wp['total_attempts']} 次): 处于薄弱水平。建议通过简单的编程实例重新梳理其运作流程。\n"
    else:
        markdown += "📝 班级尚未有充足的学生作业能力分值记录，暂未确定薄弱概念。请分派更多作业以收集数据。\n"
    markdown += "\n"

    # 3. 建议补练作业
    markdown += "### 🏋️ 建议补练作业\n"
    if suggested_assignments:
        markdown += "为巩固学习弱势，建议向本班级分派以下强化训练任务：\n\n"
        for a in suggested_assignments[:3]:
            markdown += f"- **{a['title']}** (难度: {a['difficulty']}): {a['description']}\n"
    else:
        markdown += "🎯 暂无合适的推荐作业，建议根据薄弱知识点自行设计一些精细的巩固练习。\n"

    return markdown


def generate_class_suggestions_async(class_id, teacher_id, app, demo_run_id=None):
    """
    异步启动班级AI建议生成任务
    """
    def task():
        with app.app_context():
            if demo_run_id and not activate_demo_run(demo_run_id):
                return
            generate_class_suggestions(
                class_id,
                teacher_id,
                demo_run_id=demo_run_id,
            )

    thread = threading.Thread(target=task)
    thread.daemon = True
    thread.start()
    return thread


def generate_class_suggestions_stream(class_id, teacher_id, demo_run_id=None):
    """
    流式生成班级学情建议，计算规则引擎结果，并流式输出LLM反馈报告，最后保存入库
    """
    if demo_run_id and not activate_demo_run(demo_run_id):
        yield f"data: {json.dumps({'type': 'error', 'message': '体验会话已结束，请重新进入演示'})}\n\n"
        return

    yield f"data: {json.dumps({'type': 'status', 'message': '正在读取班级基本数据...'})}\n\n"
    
    cls = Class.query.get(class_id)
    if not cls:
        yield f"data: {json.dumps({'type': 'error', 'message': '班级未找到'})}\n\n"
        return

    suggestion = TeacherAISuggestion.get_or_create(class_id=class_id, teacher_id=teacher_id)
    suggestion.status = 'processing'
    db.session.commit()

    yield f"data: {json.dumps({'type': 'status', 'message': '正在分析学生提交与风险情况...'})}\n\n"
    students = User.query.filter_by(class_id=class_id, usertype='学生').all()
    student_ids = [s.student_id for s in students]

    attention_students = []
    if students:
        learning_rows = build_class_learning_rows(cls, students=students)
        for row in learning_rows:
            if row['status'] == '需关注' or row['status'] == '未开始':
                attention_students.append({
                    'student_id': row['student'].student_id,
                    'name': row['student'].full_name or row['student'].username,
                    'risk_tags': row['risk_tags'],
                    'latest_score': row['latest_score']
                })

    yield f"data: {json.dumps({'type': 'status', 'message': '正在聚合知识点雷达掌握度...'})}\n\n"
    weak_points = []
    if student_ids:
        rows = db.session.query(
            KnowledgePointScore.knowledge_point,
            db.func.avg(KnowledgePointScore.score).label('avg_score'),
            db.func.sum(KnowledgePointScore.total_attempts).label('total_attempts')
        ).filter(
            KnowledgePointScore.student_id.in_(student_ids)
        ).group_by(
            KnowledgePointScore.knowledge_point
        ).order_by(
            db.func.avg(KnowledgePointScore.score).asc()
        ).all()

        for row in rows:
            kp_code = row.knowledge_point
            kp_display = KnowledgePointScore.KNOWLEDGE_POINTS.get(kp_code, kp_code)
            weak_points.append({
                'code': kp_code,
                'name': kp_display,
                'avg_score': round(float(row.avg_score), 1) if row.avg_score else 0.0,
                'total_attempts': int(row.total_attempts) if row.total_attempts else 0
            })

    yield f"data: {json.dumps({'type': 'status', 'message': '正在匹配系统作业并生成推荐大纲...'})}\n\n"
    suggested_assignments = []
    if weak_points:
        weak_kp_codes = [wp['code'] for wp in weak_points[:3]]
        candidate_assignments = Assignment.query.join(
            AssignmentKnowledgePoint, Assignment.id == AssignmentKnowledgePoint.assignment_id
        ).filter(
            AssignmentKnowledgePoint.knowledge_point.in_(weak_kp_codes)
        ).all()

        for assign in candidate_assignments:
            if cls.name not in assign.get_target_class_list():
                if assign.id not in [a['id'] for a in suggested_assignments]:
                    suggested_assignments.append({
                        'id': assign.id,
                        'title': assign.title,
                        'description': assign.description or '暂无描述',
                        'difficulty': {1: '简单', 2: '较易', 3: '中等', 4: '较难', 5: '困难'}.get(assign.difficulty_level, '中等')
                    })

    if not suggested_assignments and weak_points:
        for wp in weak_points[:2]:
            suggested_assignments.append({
                'id': 0,
                'title': f'针对【{wp["name"]}】的巩固练习',
                'description': f'建议为班级新建一份涵盖【{wp["name"]}】的编程作业，帮助学生专项突破该知识点。',
                'difficulty': '中等'
            })

    rule_markdown = _generate_rule_based_markdown(cls, weak_points, attention_students, suggested_assignments)
    rule_json_dict = {
        'attention_students': [
            {
                'student_id': s['student_id'],
                'name': s['name'],
                'risk_reason': f"存在{'/'.join(s['risk_tags'])}风险，最近得分 {s['latest_score'] if s['latest_score'] is not None else '无'}"
            } for s in attention_students
        ],
        'weak_knowledge_points': [
            {
                'point_code': wp['code'],
                'point_name': wp['name'],
                'explanation': f"班级掌握度较低，平均分：{wp['avg_score']}/100，尝试：{wp['total_attempts']}次。建议课堂串讲基本概念。"
            } for wp in weak_points[:3]
        ],
        'suggested_assignments': [
            {
                'title': a['title'],
                'reason': f"针对弱势概念进行课后巩固训练。",
                'difficulty': a['difficulty']
            } for a in suggested_assignments[:3]
        ]
    }

    llm = SharedLLMClient()
    if llm.is_available():
        try:
            yield f"data: {json.dumps({'type': 'status', 'message': '正在与 AI 助手建立流式会话...'})}\n\n"
            
            attention_details_str = "\n".join([
                f"- {s['name']} ({s['student_id']}): 风险标签 {s['risk_tags']}, 最近得分 {s['latest_score']}" 
                for s in attention_students
            ]) if attention_students else "暂无高风险学生"

            weak_points_str = "\n".join([
                f"- {wp['name']}: {wp['avg_score']}分, 尝试 {wp['total_attempts']} 次" 
                for wp in weak_points
            ]) if weak_points else "暂无评分数据"

            assignments_str = "\n".join([
                f"- {a['title']} (难度: {a['difficulty']}): {a['description']}" 
                for a in suggested_assignments[:3]
            ]) if suggested_assignments else "无推荐作业"

            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是一个专业的编程教育专家，擅长从班级 student 分数、提交活跃度、弱点概念等多维度给出建议。\n"
                        "请用学术严谨且易懂的中文直接输出分析内容，并在正文结束后，输出一行由 `===JSON===` 分隔的 JSON 字符串，包含系统结构。"
                    )
                },
                {
                    "role": "user",
                    "content": f"""请针对以下班级学情数据，为授课教师生成本周的 AI 个性化建议报告。

班级: {cls.name}
学生数: {len(students)} 人
需关注的学生:
{attention_details_str}

本班概念掌握情况(平均分):
{weak_points_str}

可供派发的关联作业:
{assignments_str}

请生成一份详细的教学建议报告，必须包含以下三个核心部分：
1. 本周重点关注学生：列出高风险学生、原因及对应的关怀建议。
2. 建议讲解知识点：针对薄弱概念，提供核心讲解策略和典型错误提醒。
3. 建议补练作业：推荐具体的练习方案。

必须按 Markdown 格式排版正文。
正文结束后，输出一行 `===JSON===`，紧接着输出以下 JSON 格式的解析字典:
{{
  "attention_students": [
     {{"student_id": "学号", "name": "学生姓名", "risk_reason": "具体风险和建议建议"}}
  ],
  "weak_knowledge_points": [
     {{"point_code": "概念代码", "point_name": "概念名称", "explanation": "掌握现状及对策建议"}}
  ],
  "suggested_assignments": [
     {{"title": "作业标题", "reason": "推荐原因", "difficulty": "中等/困难"}}
  ]
}}
"""
                }
            ]

            full_text = ""
            json_started = False
            has_sent_start = False
            
            for chunk in llm.chat_stream(messages):
                full_text += chunk
                if "===" in chunk or "JSON" in chunk or json_started:
                    json_started = True
                else:
                    if not has_sent_start:
                        yield f"data: {json.dumps({'type': 'start'})}\n\n"
                        has_sent_start = True
                    yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"

            # 提取 JSON 部分
            parts = full_text.split('===JSON===')
            markdown_part = parts[0].strip()
            json_part = parts[1].strip() if len(parts) > 1 else "{}"

            if json_part.startswith('```'):
                lines = json_part.splitlines()
                if lines[0].startswith('```json') or lines[0].startswith('```'):
                    lines = lines[1:]
                if lines[-1].startswith('```'):
                    lines = lines[:-1]
                json_part = "\n".join(lines).strip()

            try:
                parsed_json = json.loads(json_part)
                if 'attention_students' in parsed_json and 'weak_knowledge_points' in parsed_json:
                    suggestion.suggestion_markdown = markdown_part
                    suggestion.suggestion_json = json.dumps(parsed_json, ensure_ascii=False)
                    suggestion.status = 'completed'
                    suggestion.last_updated = dt.utcnow()
                    db.session.commit()
                    
                    yield f"data: {json.dumps({'type': 'complete', 'suggestion_json': parsed_json, 'last_updated': suggestion.last_updated.strftime('%Y-%m-%d %H:%M:%S')})}\n\n"
                    return
            except Exception as je:
                print(f"LLM JSON 流解析失败: {je}")

        except Exception as le:
            print(f"LLM 流式分析失败: {le}")

        if demo_run_id:
            if _demo_database_is_available(demo_run_id):
                _mark_demo_suggestion_failed(class_id, teacher_id)
            yield f"data: {json.dumps({'type': 'error', 'message': '真实 AI 建议生成失败，请稍后重试'})}\n\n"
            return

    elif demo_run_id:
        if _demo_database_is_available(demo_run_id):
            _mark_demo_suggestion_failed(class_id, teacher_id)
        yield f"data: {json.dumps({'type': 'error', 'message': 'AI 服务当前不可用，请稍后重试'})}\n\n"
        return

    # Fallback to rules-based
    yield f"data: {json.dumps({'type': 'start'})}\n\n"
    chunk_size = 30
    import time
    for i in range(0, len(rule_markdown), chunk_size):
        chunk = rule_markdown[i:i+chunk_size]
        yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
        time.sleep(0.04)

    suggestion.suggestion_markdown = rule_markdown
    suggestion.suggestion_json = json.dumps(rule_json_dict, ensure_ascii=False)
    suggestion.status = 'completed'
    suggestion.last_updated = dt.utcnow()
    db.session.commit()

    yield f"data: {json.dumps({'type': 'complete', 'suggestion_json': rule_json_dict, 'last_updated': suggestion.last_updated.strftime('%Y-%m-%d %H:%M:%S')})}\n\n"

