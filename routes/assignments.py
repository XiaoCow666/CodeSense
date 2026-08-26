"""
作业相关路由
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, Response, current_app, jsonify
from flask_login import current_user
from models import db, User, Assignment, Submission, SystemLog
from forms import AssignmentForm, SubmissionForm
from utils.auth import login_required, admin_required, teacher_required, admin_or_teacher_required
from utils.code_evaluator import evaluate_cpp_code, initialize_models
from tasks.submission_tasks import evaluate_submission_async
from services.demo_database import current_demo_run_id
from io import BytesIO
from sqlalchemy import desc
import traceback  # 添加traceback模块
import os
import json
from datetime import datetime

assignments = Blueprint('assignments', __name__)

class InMemoryPagination:
    """内存分页辅助类，行为与 Flask-SQLAlchemy Pagination 保持一致"""
    def __init__(self, items, page, per_page):
        self.total = len(items)
        self.page = page
        self.per_page = per_page
        self.items = items[(page - 1) * per_page : page * per_page]
        
        self.has_prev = page > 1
        self.prev_num = page - 1
        self.has_next = (page * per_page) < self.total
        self.next_num = page + 1
        self.pages = (self.total + per_page - 1) // per_page

    def iter_pages(self, left_edge=2, left_current=2, right_current=5, right_edge=2):
        last = 0
        for num in range(1, self.pages + 1):
            if (
                num <= left_edge
                or (num >= self.page - left_current and num <= self.page + right_current)
                or num > self.pages - right_edge
            ):
                if last + 1 != num:
                    yield None
                yield num
                last = num

    def __iter__(self):
        return iter(self.items)

    def __bool__(self):
        return len(self.items) > 0

# 在模块开始时初始化模型
initialize_models()

@assignments.route('/assignments/generate', methods=['POST'])
@login_required
@admin_or_teacher_required
def generate_assignment():
    """根据简短提示智能生成作业题目和描述"""
    data = request.json
    prompt = data.get('prompt', '')
    
    if not prompt:
        return jsonify({'error': '提示词不能为空'}), 400
        
    try:
        from openai import OpenAI
        # 首选智谱AI
        zhipu_key = current_app.config.get('ZHIPU_API_KEY')
        openai_key = current_app.config.get('OPENAI_API_KEY')

        if zhipu_key:
            client = OpenAI(
                api_key=zhipu_key,
                base_url="https://open.bigmodel.cn/api/paas/v4/"
            )
            model_name = current_app.config.get('ZHIPU_MODEL', "glm-4.5-flash")
        # 降级使用 OpenAI
        elif openai_key:
            client = OpenAI(
                api_key=openai_key,
                base_url=current_app.config.get('OPENAI_BASE_URL', "https://api.openai.com/v1")
            )
            model_name = current_app.config.get('OPENAI_MODEL', "gpt-3.5-turbo")
        else:
            return jsonify({'error': '系统未配置AI大模型接口，无法使用智能生成功能'}), 501

        system_prompt = '''你是一个资深的计算机科学教授。你需要根据用户的简短提示，扩充并生成一道相对完整的编程或算法作业题。
请以 JSON 格式返回，确保可以被程序解析。JSON必须包含两个字段：
1. "title": 题目名称（字符串）
2. "description": 题目的详细描述（支持Markdown，包含题目背景、输入限制、输出格式要求，以及示例输入和输出）。千万不要在JSON外附加任何解释文本。'''

        import time
        max_retries = 5
        base_delay = 2
        current_model = model_name
        response = None

        for attempt in range(max_retries):
            try:
                try:
                    from services.llm_client import SharedLLMClient
                    import time
                    SharedLLMClient.last_user_request_time = time.time()
                except Exception:
                    pass
                response = client.chat.completions.create(
                    model=current_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"请针对这个主题生成一道编程题：{prompt}"}
                    ],
                    temperature=0.7,
                    timeout=30
                )
                break
            except Exception as e:
                err_str = str(e)
                is_rate_limit = (
                    "429" in err_str or
                    "1305" in err_str or
                    "rate limit" in err_str.lower() or
                    "访问量过大" in err_str or
                    "频率" in err_str or
                    "Too Many Requests" in err_str or
                    "APIReachLimitError" in type(e).__name__ or
                    "rate_limit" in type(e).__name__.lower()
                )
                
                if is_rate_limit and attempt < max_retries - 1:
                    if zhipu_key and current_model == "glm-4.5-flash":
                        print(f"智能生成作业触发限流，将模型从 {current_model} 降级为 glm-4.5-flash")
                        current_model = "glm-4.5-flash"
                        # 触发全局 SharedLLMClient 的同步更新
                        try:
                            from services.llm_client import llm_client
                            llm_client._model_name = "glm-4.5-flash"
                        except Exception:
                            pass
                        time.sleep(0.5)
                    else:
                        delay = base_delay * (2 ** attempt)
                        print(f"智能生成作业触发限流，将在 {delay} 秒后重试 {current_model} (尝试 {attempt+1}/{max_retries})...")
                        time.sleep(delay)
                    continue
                else:
                    raise e
        
        result_content = response.choices[0].message.content
        
        # 尝试从内容中提取JSON数据
        try:
            # 处理可能的Markdown代码块
            if "```json" in result_content:
                json_str = result_content.split("```json")[1].split("```")[0].strip()
            elif "```" in result_content:
                json_str = result_content.split("```")[1].split("```")[0].strip()
            else:
                json_str = result_content.strip()
            
            result_json = json.loads(json_str)
        except Exception as json_err:
            current_app.logger.error(f"解析AI产生的JSON失败: {str(json_err)}, 原内容: {result_content}")
            # 备选方案：如果不是合法JSON，尝试提取关键字段（简单正则表达式或字符串查找）
            # 这里简单返回 500 让用户重试或查看日志
            return jsonify({'error': "AI返回格式有误，请重试"}), 500
        
        return jsonify({
            'success': True,
            'title': result_json.get('title', ''),
            'description': result_json.get('description', '')
        })
    except Exception as e:
        current_app.logger.error(f"智能生成作业失败: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f"生成失败: {str(e)}"}), 500



@assignments.route('/assignments')
@login_required
def manage_assignments():
    """显示作业列表"""
    try:
        per_page = 10  # 每页显示的题目数量
        page = request.args.get('page', 1, type=int)  # 获取当前页码，默认为1
        search_term = request.args.get('search', '')  # 获取搜索关键词
        sort_by = request.args.get('sort_by', 'id')  # 获取排序字段，默认为id
        sort_order = request.args.get('sort_order', 'asc')  # 获取排序顺序，默认为升序
        
        print(f"当前页码: {page}, 搜索词: {search_term}")
        session['apage'] = page
        
        # 构建查询
        query = Assignment.query
        
        # 添加排序逻辑
        if sort_by == 'id':
            if sort_order == 'asc':
                query = query.order_by(Assignment.id.asc())
            else:
                query = query.order_by(Assignment.id.desc())
        elif sort_by == 'title':
            if sort_order == 'asc':
                query = query.order_by(Assignment.title.asc())
            else:
                query = query.order_by(Assignment.title.desc())
        elif sort_by == 'count':
            if sort_order == 'asc':
                query = query.order_by(Assignment.count.asc())
            else:
                query = query.order_by(Assignment.count.desc())
        elif sort_by == 'average_score':
            if sort_order == 'asc':
                query = query.order_by(Assignment.average_score.asc())
            else:
                query = query.order_by(Assignment.average_score.desc())
        
        # 添加搜索条件
        if search_term:
            query = query.filter(
                db.or_(
                    Assignment.title.ilike(f'%{search_term}%'),
                    Assignment.description.ilike(f'%{search_term}%')
                )
            )
        
        # 获取分页的作业列表
        print("正在获取作业列表...")
        assignment_list = query.paginate(page=page, per_page=per_page, error_out=False)
        print(f"获取到 {len(assignment_list.items)} 个作业")
        
        # 获取统计信息
        total_submissions = Submission.query.count()
        student_count = db.session.query(db.func.count(db.distinct(Submission.student_id))).scalar() or 0
        
        # 根据用户类型展示不同视图
        usertype = session.get('usertype')
        print(f"用户类型: {usertype}")
        
        if usertype == '管理员':
            print("显示管理员视图")
            return render_template(
                'assignments.html', 
                assignments=assignment_list,
                total_submissions=total_submissions,
                student_count=student_count,
                search_term=search_term,
                sort_by=sort_by,
                sort_order=sort_order
            )
        elif usertype == '教师':
            print("显示教师视图 - 重定向到教师作业管理")
            return redirect(url_for('assignments.teacher_assignments'))
        else:
            # 对于学生用户，获取每个作业的最高得分
            student_id = session.get('student_id')
            print(f"学生ID: {student_id}")
            
            if not student_id:
                flash('会话已过期，请重新登录')
                return redirect(url_for('auth.login'))
            
            print("获取每个作业的最高得分...")
            # 优化：使用单次查询获取所有作业的最高分，避免 N+1 问题
            assignment_ids = [a.id for a in assignment_list.items]
            if assignment_ids:
                # 子查询：获取每个作业该学生的最高分
                from sqlalchemy import func
                max_scores_subquery = db.session.query(
                    Submission.assignment_id,
                    func.max(Submission.score).label('max_score')
                ).filter(
                    Submission.student_id == student_id,
                    Submission.assignment_id.in_(assignment_ids)
                ).group_by(Submission.assignment_id).subquery()

                # 主查询：连接获取结果
                max_scores_query = db.session.query(
                    max_scores_subquery.c.assignment_id,
                    max_scores_subquery.c.max_score
                )
                max_scores_dict = {row.assignment_id: row.max_score for row in max_scores_query.all()}

                # 分配分数
                for assignment in assignment_list.items:
                    assignment.max_student_score = max_scores_dict.get(assignment.id, 0)
            else:
                for assignment in assignment_list.items:
                    assignment.max_student_score = 0
            
            print("渲染学生作业视图...")
            return render_template(
                's_assignments.html', 
                assignments=assignment_list,
                search_term=search_term,
                sort_by=sort_by,
                sort_order=sort_order
            )
    except Exception as e:
        print(f"访问题库时出错: {str(e)}")
        print(traceback.format_exc())  # 打印完整的堆栈跟踪
        flash(f'访问题库时出错: {str(e)}')
        return redirect(url_for('main.home'))


@assignments.route('/add_assignment', methods=['GET', 'POST'])
@login_required
@admin_required
def add_assignment():
    """添加新作业"""
    form = AssignmentForm()
    
    if form.validate_on_submit():
        # 检查作业ID是否已存在
        assignment_id = form.assignment_id.data
        existing_assignment = Assignment.query.get(assignment_id)
        
        if existing_assignment:
            flash('该作业ID已存在，请使用其他ID', 'danger')
            return render_template('add_assignment.html', form=form)
        
        # 创建新作业
        new_assignment = Assignment(
            id=assignment_id,
            title=form.title.data,
            description=form.description.data,
            due_date=form.due_date.data,
            total_score=0,
            average_score=0.0,
            count=0
        )
        
        try:
            db.session.add(new_assignment)
            db.session.commit()
            
            # 触发异步生成预设任务
            try:
                from utils.async_tasks import add_generate_preset_task
                add_generate_preset_task(new_assignment.id)
            except Exception as e:
                current_app.logger.error(f"触发预设生成任务失败: {e}")
            
            # 添加系统日志
            admin_id = session.get('student_id')
            admin_user = User.query.get(admin_id)
            SystemLog.add_log(
                log_type='添加作业',
                content=f'管理员 {admin_user.username} 添加了新作业：{new_assignment.title} (ID: {new_assignment.id})',
                user_id=admin_id,
                icon='bi bi-file-earmark-plus'
            )
            
            flash('作业添加成功！', 'success')
            return redirect(url_for('assignments.manage_assignments'))
        except Exception as e:
            db.session.rollback()
            flash(f'添加作业失败: {str(e)}', 'danger')
    
    return render_template('add_assignment.html', form=form)


@assignments.route('/delete_assignment/<int:assignment_id>', methods=['POST'])
@login_required
def delete_assignment(assignment_id):
    """删除作业 (仅限管理员或作业创建者)"""
    assignment_to_delete = Assignment.query.get_or_404(assignment_id)
    assignment_title = assignment_to_delete.title
    
    # 权限检查：仅允许管理员或创建者删除
    is_admin = getattr(current_user, 'usertype', '') == '管理员'
    is_creator = assignment_to_delete.creator_id == current_user.student_id
    
    if not (is_admin or is_creator):
        flash('您没有权限删除此作业', 'danger')
        return redirect(url_for('assignments.manage_assignments'))
    
    try:
        db.session.delete(assignment_to_delete)
        db.session.commit()
        
        # 添加系统日志
        user_id = session.get('student_id')
        user_role = '管理员' if is_admin else '教师'
        SystemLog.add_log(
            log_type='删除作业',
            content=f'{user_role} {current_user.username} 删除了作业：{assignment_title} (ID: {assignment_id})',
            user_id=user_id,
            icon='bi bi-trash'
        )
        
        flash('作业已成功删除', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除作业失败: {str(e)}', 'danger')
    
    # 根据用户角色返回不同的列表页面
    if is_admin:
        return redirect(url_for('assignments.manage_assignments'))
    else:
        return redirect(url_for('assignments.teacher_assignments'))


@assignments.route('/view_assignment/<int:assignment_id>')
@login_required
def view_assignment(assignment_id):
    """查看作业详情，不包括代码提交功能"""
    # 获取作业详情
    assignment = Assignment.query.get_or_404(assignment_id)
    
    # 获取用户信息
    student_id = session.get('student_id')
    usertype = session.get('usertype')
    if not student_id:
        flash('会话已过期，请重新登录')
        return redirect(url_for('auth.login'))
    
    # 获取该作业的提交总数
    submission_count = Submission.query.filter_by(
        assignment_id=assignment_id
    ).count()
    
    # 获取全部用户的平均分
    average_score = assignment.average_score if assignment and assignment.count > 0 else 0
    
    # 根据用户类型提供不同的数据
    if usertype == '管理员':
        # 管理员视图 - 提供更多统计数据
        
        # 获取参与学生数量
        student_count = db.session.query(db.func.count(db.distinct(Submission.student_id)))\
                        .filter_by(assignment_id=assignment_id).scalar() or 0
        
        # 获取分数分布
        score_counts = db.session.query(
            Submission.score, db.func.count(Submission.id)
        ).filter_by(assignment_id=assignment_id).group_by(Submission.score).all()
        
        score_distribution = {int(score): count for score, count in score_counts}
        
        # 获取最近的10个提交记录
        recent_submissions = Submission.query.filter_by(assignment_id=assignment_id).order_by(desc(Submission.submitted_at)).limit(10).all()
            
        # 添加用户信息到提交记录
        for submission in recent_submissions:
            submission.user = User.query.get(submission.student_id)
            
        return render_template(
            'assignment_detail.html',
            assignment=assignment,
            submission_count=submission_count,
            average_score=average_score,
            student_count=student_count,
            score_distribution=score_distribution,
            recent_submissions=recent_submissions,
            usertype=usertype
        )
    else:
        # 学生视图 - 提供个人提交数据
        latest_submission = Submission.query.filter_by(
            student_id=student_id,
            assignment_id=assignment_id
        ).order_by(desc(Submission.id)).first()
        
        # 获取该学生的最高分
        max_score = db.session.query(db.func.max(Submission.score)).filter_by(
            student_id=student_id,
            assignment_id=assignment_id
        ).scalar() or 0
        
        return render_template(
            'assignment_detail.html',
            assignment=assignment,
            latest_submission=latest_submission,
            submission_count=submission_count,
            average_score=average_score,
            max_score=max_score,
            usertype=usertype
        )


@assignments.route('/submit/<int:assignment_id>', methods=['GET', 'POST'])
@login_required
def submit_code(assignment_id):
    """提交代码"""
    # 获取作业详情
    assignment = Assignment.query.get_or_404(assignment_id)
    
    # 获取用户最近的提交
    student_id = session.get('student_id')
    if not student_id:
        flash('会话已过期，请重新登录')
        return redirect(url_for('auth.login'))
        
    # 获取用户最近的提交及提交历史
    latest_submission = Submission.query.filter_by(
        student_id=student_id,
        assignment_id=assignment_id
    ).order_by(desc(Submission.id)).first()
    
    # 获取该作业的所有提交记录用于显示历史
    submissions = Submission.query.filter_by(
        student_id=student_id,
        assignment_id=assignment_id
    ).order_by(desc(Submission.submitted_at)).all()
    
    # 获取该作业的提交总数
    submission_count = Submission.query.filter_by(
        assignment_id=assignment_id
    ).count()
    
    # 创建提交表单
    form = SubmissionForm()
    
    if form.validate_on_submit():
        # 获取用户提交的代码和语言
        code = form.code.data
        language = form.language.data
        
        # 检查代码长度
        if len(code.strip()) < 10:
            flash('代码太短，请提交更完整的代码。', 'danger')
            return render_template(
                'submit_code.html',
                form=form,
                assignment=assignment,
                latest_submission=latest_submission,
                submissions=submissions,
                submission_count=submission_count
            )
            
        try:
            # 1. 保存提交记录，设置状态为pending
            submission = Submission(
                student_id=student_id,
                assignment_id=assignment_id,
                code=code,
                language=language,
                status='pending'
            )
            db.session.add(submission)
            db.session.commit()
            
            # 2. 触发后台异步评测
            try:
                from flask import current_app
                evaluate_submission_async(
                    current_app._get_current_object(), 
                    submission.id, 
                    assignment.title,
                    demo_run_id=current_demo_run_id(),
                )
                print(f"已为提交 {submission.id} 启动后台评测")
                
                # 跳转到等待评测页面
                return redirect(url_for('assignments.evaluating_submission', submission_id=submission.id))
            except Exception as async_err:
                print(f"启动异步评测失败: {async_err}")
                flash(f'后台评测系统启动失败，请稍后重试: {str(async_err)}', 'danger')
                return redirect(url_for('assignments.submit_code', assignment_id=assignment_id))

        except Exception as e:
            db.session.rollback()
            print(f"处理提交时出错: {e}")
            traceback.print_exc()
            flash(f'提交代码时出错: {str(e)}', 'danger')
            return redirect(url_for('assignments.submit_code', assignment_id=assignment_id))
    
    return render_template(
        'submit_code.html',
        form=form,
        assignment=assignment,
        latest_submission=latest_submission,
        submissions=submissions,
        submission_count=submission_count
    )

@assignments.route('/submission/<int:submission_id>/evaluating')
@login_required
def evaluating_submission(submission_id):
    """等待评测完成的过渡页面"""
    submission = Submission.query.get_or_404(submission_id)
    
    # 安全检查
    if current_user.usertype == '学生' and submission.student_id != current_user.student_id:
        flash('您无权访问此提交。', 'danger')
        return redirect(url_for('main.home'))
        
    # 如果已经评测完成，直接跳转到详情页
    if submission.status == 'evaluated' or submission.status == 'failed':
        return redirect(url_for('assignments.view_submission', submission_id=submission_id))
        
    return render_template('submission_evaluating.html', submission=submission)


@assignments.route('/download_code/<int:submission_id>')
@login_required
def download_code(submission_id):
    """下载提交的代码"""
    try:
        submission = Submission.query.get_or_404(submission_id)
        
        # 确保只有提交者、教师或管理员可以下载代码
        if session['usertype'] not in ['管理员', '教师'] and session['student_id'] != submission.student_id:
            flash('您无权下载该代码', 'danger')
            return redirect(url_for('main.home'))
        
        # 准备代码内容
        code_content = ""
        if submission.code is not None:
            # 处理不同编码的情况
            if isinstance(submission.code, bytes):
                # 尝试不同的编码方式
                encodings = ['utf-8', 'latin1', 'gbk', 'gb2312', 'gb18030', 'big5']
                decoded = False
                for encoding in encodings:
                    try:
                        code_content = submission.code.decode(encoding, errors='replace')
                        decoded = True
                        print(f"下载代码：成功使用 {encoding} 解码")
                        break
                    except Exception as e:
                        print(f"下载代码：使用 {encoding} 解码失败: {str(e)}")
                        continue
                
                if not decoded:
                    # 如果所有编码都失败，使用latin1作为最后的选择
                    code_content = submission.code.decode('latin1', errors='replace')
            else:
                code_content = submission.code
        
        # 移除可能的BOM标记
        if code_content.startswith('\ufeff'):
            code_content = code_content[1:]
        
        # 设置文件扩展名为.cpp
        file_ext = '.cpp'
        
        # 准备文件下载
        text_buffer = BytesIO(code_content.encode('utf-8', errors='replace'))
        
        # 设置响应头
        text_buffer.seek(0)
        response = Response(
            text_buffer,
            headers={'Content-Disposition': f'attachment; filename=submission_{submission_id}{file_ext}'},
            mimetype='text/plain'
        )
        
        return response
    except Exception as e:
        print(f"下载代码时出错: {str(e)}")
        print(traceback.format_exc())
        flash(f'下载代码时出错: {str(e)}', 'danger')
        return redirect(url_for('assignments.view_submission', submission_id=submission_id))


@assignments.route('/student_assignments')
@login_required
def student_assignments():
    """学生查看作业列表"""
    page = request.args.get('page', 1, type=int)
    search_term = request.args.get('search', '').strip()
    sort_by = request.args.get('sort', 'id')
    sort_order = request.args.get('order', 'desc')
    
    try:
        # 获取学生ID和班级
        student_id = current_user.student_id
        class_name = current_user.class_name
        
        if not student_id:
            flash('会话已过期，请重新登录', 'danger')
            return redirect(url_for('auth.login'))
        
        # 根据学生所在班级筛选作业
        if class_name:
            all_assignments = Assignment.query.filter(
                Assignment.target_classes.like(f'%{class_name}%')
            ).all()
        else:
            all_assignments = []

        # 获取当前学生对所有作业的最高分与提交状态，同时自动触发缺失/旧版预设的后台生成
        assignment_max_scores = {}
        assignment_statuses = {}
        from models import AssignmentThinkingPreset
        from utils.async_tasks import add_generate_preset_task
        for a in all_assignments:
            # 自动检查预设，若不存在或失败则优先触发生成
            preset = AssignmentThinkingPreset.query.filter_by(assignment_id=a.id).first()
            if not preset:
                try:
                    preset = AssignmentThinkingPreset(assignment_id=a.id, status='generating')
                    db.session.add(preset)
                    db.session.commit()
                    add_generate_preset_task(a.id)
                    current_app.logger.info(f"列表加载发现作业 {a.id} 无预设，已触发后台生成任务")
                except Exception as ex:
                    db.session.rollback()
                    current_app.logger.error(f"列表加载自动触发作业 {a.id} 预设失败: {ex}")
            elif preset.status == 'failed':
                try:
                    preset.status = 'generating'
                    preset.error_message = None
                    db.session.commit()
                    add_generate_preset_task(a.id)
                    current_app.logger.info(f"列表加载发现作业 {a.id} 预设失败，已重新触发后台生成任务")
                except Exception as ex:
                    db.session.rollback()
                    current_app.logger.error(f"列表加载重新触发作业 {a.id} 预设失败: {ex}")
            elif preset.status == 'ready' and (not hasattr(preset, 'quiz_steps') or not preset.quiz_steps or preset.quiz_steps.strip() == '' or preset.quiz_steps == '[]'):
                # 检查预设是否是老版本（状态为 ready 但没有 quiz_steps），如果是，则自动重新生成
                try:
                    preset.status = 'generating'
                    preset.error_message = None
                    db.session.commit()
                    add_generate_preset_task(a.id)
                    current_app.logger.info(f"列表加载发现作业 {a.id} 预设缺少 quiz_steps 数据，已重置并重新触发生成任务")
                except Exception as ex:
                    db.session.rollback()
                    current_app.logger.error(f"列表加载重置作业 {a.id} 预设状态失败: {ex}")

            sub = Submission.query.filter_by(
                assignment_id=a.id,
                student_id=student_id
            ).order_by(Submission.score.desc()).first()
            if sub:
                assignment_max_scores[a.id] = sub.score
                if sub.score >= 60:
                    assignment_statuses[a.id] = '已通过'
                else:
                    assignment_statuses[a.id] = '不及格'
            else:
                assignment_max_scores[a.id] = 0
                assignment_statuses[a.id] = '未提交'

        filtered_assignments = []
        is_llm_recommended = False
        
        if search_term:
            # 尝试大模型个性化推荐
            from services.llm_client import llm_client
            if llm_client.is_available() and len(all_assignments) > 0:
                try:
                    # 序列化作业列表（仅包含 ID, 标题, 描述前100字，以节省 token）
                    assignments_data = [
                        {
                            "id": a.id,
                            "title": a.title,
                            "desc": (a.description or '')[:100],
                            "my_score": assignment_max_scores[a.id],
                            "status": assignment_statuses[a.id]
                        }
                        for a in all_assignments
                    ]
                    
                    system_prompt = (
                        "你是一个智能作业推荐算法引擎。根据用户的搜索/练习需求（如'我想练排序'、'我分数低的作业'、'我没做过的题'），"
                        "从候选的编程作业列表中，挑选并排序最符合需求的作业，并输出它们的关联匹配度得分。\n\n"
                        "你需要以 JSON 数组格式返回结果，每个元素包含 'id' (整数) 和 'score' (0.0 到 10.0 的浮点数，"
                        "表示关联匹配度，10.0表示完美符合需求，0.0表示完全不相关)。只返回 JSON 块，不要包含任何解释文字。\n\n"
                        "示例输出：\n[\n  {\"id\": 101, \"score\": 9.5},\n  {\"id\": 102, \"score\": 1.2}\n]"
                    )
                    
                    user_prompt = f"用户搜索意图：'{search_term}'\n\n候选作业列表及个人进度：\n{json.dumps(assignments_data, ensure_ascii=False)}"
                    
                    messages = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ]
                    
                    response = llm_client.chat(messages, temperature=0.2)
                    if response:
                        clean_res = response.strip()
                        if "```json" in clean_res:
                            clean_res = clean_res.split("```json")[1].split("```")[0].strip()
                        elif "```" in clean_res:
                            clean_res = clean_res.split("```")[1].split("```")[0].strip()
                        
                        recommendations = json.loads(clean_res)
                        scores = {item['id']: float(item['score']) for item in recommendations if 'id' in item and 'score' in item}
                        
                        # 过滤和打分
                        for a in all_assignments:
                            score = scores.get(a.id, 0.0)
                            # 如果标题或描述模糊匹配到了关键字，保证至少有 5 分的基础得分
                            if search_term.lower() in a.title.lower() or search_term.lower() in (a.description or '').lower():
                                score = max(score, 5.0)
                            
                            if score >= 4.0:
                                a.relevance_score = score
                                filtered_assignments.append(a)
                        
                        is_llm_recommended = True
                        current_app.logger.info(f"大模型推荐算法对搜索词 '{search_term}' 成功返回了 {len(filtered_assignments)} 个匹配结果")
                except Exception as llm_err:
                    current_app.logger.error(f"大模型个性化推荐搜索失败，退回传统模糊搜索: {llm_err}")
            
            # 如果大模型不可用，或者推荐结果解析失败/没有匹配结果，则使用传统的数据库/内存模糊搜索
            if not is_llm_recommended:
                for a in all_assignments:
                    if search_term.lower() in a.title.lower() or search_term.lower() in (a.description or '').lower():
                        a.relevance_score = 5.0
                        filtered_assignments.append(a)
        else:
            # 没有搜索词，展示全部
            filtered_assignments = all_assignments

        # 排序逻辑
        if search_term and is_llm_recommended:
            # 如果是有搜索词的大模型推荐，则默认按大模型相关度得分降序排序
            filtered_assignments.sort(key=lambda x: getattr(x, 'relevance_score', 0.0), reverse=True)
        else:
            # 否则，按用户选择的排序参数排序
            if sort_by == 'id':
                filtered_assignments.sort(key=lambda x: x.id, reverse=(sort_order == 'desc'))
            elif sort_by == 'title':
                filtered_assignments.sort(key=lambda x: x.title or '', reverse=(sort_order == 'desc'))
            elif sort_by == 'count':
                filtered_assignments.sort(key=lambda x: x.count or 0, reverse=(sort_order == 'desc'))
            elif sort_by == 'average_score':
                filtered_assignments.sort(key=lambda x: x.average_score or 0.0, reverse=(sort_order == 'desc'))
            else:
                filtered_assignments.sort(key=lambda x: x.id, reverse=True)

        # 进行分页 (per_page = 10)
        pagination = InMemoryPagination(filtered_assignments, page, 10)
        
        # 获取学生每个作业的最高分供渲染使用
        max_scores = {a.id: assignment_max_scores[a.id] for a in pagination.items}
        
        return render_template('s_assignments.html',
                               assignments=pagination,
                               max_scores=max_scores,
                               sort_by=sort_by,
                               sort_order=sort_order,
                               search_term=search_term,
                               is_llm_recommended=is_llm_recommended,
                               current_time=datetime.utcnow())
    except Exception as e:
        print(f"获取学生作业列表时出错: {str(e)}")
        print(traceback.format_exc())
        flash('获取学生作业列表时出错', 'danger')
        return redirect(url_for('main.home'))

@assignments.route('/view_submission/<int:submission_id>')
@login_required
def view_submission(submission_id):
    """查看提交详情"""
    try:
        submission = Submission.query.get_or_404(submission_id)
        
        # 权限检查
        allowed = False
        # 1. 提交者本人
        if current_user.is_authenticated and submission.student_id == current_user.student_id:
            allowed = True
        # 2. 管理员
        elif current_user.is_authenticated and current_user.is_admin:
            allowed = True
        # 3. 学生的任课教师
        elif current_user.is_authenticated and current_user.is_teacher:
            student = User.query.get(submission.student_id)
            if student and student.class_id in [c.id for c in current_user.managed_classes]:
                allowed = True

        if not allowed:
            flash('您无权查看此提交', 'danger')
            return redirect(url_for('main.home'))
        
        # 处理可能的编码问题
        try:
            if submission.code is not None:
                if isinstance(submission.code, bytes):
                    # 尝试不同的编码方式
                    encodings = ['utf-8', 'latin1', 'cp1252', 'gbk', 'gb2312', 'gb18030', 'big5']
                    decoded = False
                    for encoding in encodings:
                        try:
                            submission.code = submission.code.decode(encoding, errors='replace')
                            decoded = True
                            print(f"成功使用 {encoding} 解码代码内容")
                            break
                        except Exception as e:
                            print(f"使用 {encoding} 解码失败: {str(e)}")
                            continue
                    
                    if not decoded:
                        # 如果所有编码都失败，使用十六进制表示
                        submission.code = f"[代码内容是二进制数据: {submission.code.hex()[:100]}...]"
            else:
                submission.code = ""
        except Exception as e:
            print(f"解码代码内容时出错: {str(e)}")
            print(traceback.format_exc())
            submission.code = "[代码内容无法显示]"
            
        try:
            if submission.feedback is not None:
                if isinstance(submission.feedback, bytes):
                    # 尝试不同的编码方式
                    encodings = ['utf-8', 'latin1', 'cp1252', 'gbk', 'gb2312', 'gb18030', 'big5']
                    decoded = False
                    for encoding in encodings:
                        try:
                            submission.feedback = submission.feedback.decode(encoding, errors='replace')
                            decoded = True
                            print(f"成功使用 {encoding} 解码反馈内容")
                            break
                        except Exception as e:
                            print(f"使用 {encoding} 解码失败: {str(e)}")
                            continue
                    
                    if not decoded:
                        # 如果所有编码都失败，使用十六进制表示
                        submission.feedback = f"[反馈内容是二进制数据: {submission.feedback.hex()[:100]}...]"
            else:
                submission.feedback = ""
        except Exception as e:
            print(f"解码反馈内容时出错: {str(e)}")
            print(traceback.format_exc())
            submission.feedback = "[反馈内容无法显示]"
        
        assignment = Assignment.query.get_or_404(submission.assignment_id)
        return render_template('submission_detail.html', submission=submission, assignment=assignment)
    except Exception as e:
        print(f"查看提交详情时出错: {str(e)}")
        print(traceback.format_exc())
        flash(f'查看提交详情时出错: {str(e)}', 'danger')
        return redirect(url_for('assignments.student_assignments'))


@assignments.route('/all_submissions')
@login_required
@admin_required
def all_submissions():
    """管理员查看所有提交记录"""
    try:
        per_page = 15
        page = request.args.get('page', 1, type=int)
        
        # 获取筛选参数
        student_id = request.args.get('student_id', '')
        assignment_id = request.args.get('assignment_id', '')
        min_score = request.args.get('min_score', '', type=float)
        max_score = request.args.get('max_score', '', type=float)
        
        # 构建查询
        query = Submission.query
        
        if student_id:
            query = query.filter(Submission.student_id == student_id)
        if assignment_id:
            query = query.filter(Submission.assignment_id == assignment_id)
        if min_score:
            query = query.filter(Submission.score >= min_score)
        if max_score:
            query = query.filter(Submission.score <= max_score)
            
        # 分页获取提交记录，并按提交时间降序排序
        submissions = query.order_by(desc(Submission.submitted_at)).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        # 获取所有学生和作业，用于筛选下拉框
        students = User.query.filter_by(usertype='学生').all()
        assignments = Assignment.query.all()
        
        # 创建学生ID到用户名的映射字典
        user_dict = {}
        for student in students:
            user_dict[student.student_id] = student.username
        
        return render_template('all_submissions.html', 
                              submissions=submissions,
                              students=students,
                              assignments=assignments,
                              user_dict=user_dict,
                              filters={
                                  'student_id': student_id,
                                  'assignment_id': assignment_id,
                                  'min_score': min_score,
                                  'max_score': max_score
                              })
    except Exception as e:
        print(f"查看所有提交记录时出错: {str(e)}")
        print(traceback.format_exc())
        flash(f'查看所有提交记录时出错: {str(e)}', 'danger')
        return redirect(url_for('main.admin_dashboard'))


@assignments.route('/submission-history/<int:assignment_id>')
@login_required
def submission_history(assignment_id):
    """查看特定作业的提交历史"""
    # 获取作业信息
    assignment = Assignment.query.get_or_404(assignment_id)
    
    # 获取当前学生ID
    student_id = session.get('student_id')
    if not student_id:
        flash('会话已过期，请重新登录', 'danger')
        return redirect(url_for('auth.login'))
    
    # 获取该作业的所有提交记录，按时间降序排列
    submissions = Submission.query.filter_by(
        student_id=student_id,
        assignment_id=assignment_id
    ).order_by(desc(Submission.submitted_at)).all()
    
    # 获取学生信息
    student = User.query.get(student_id)
    
    # 计算提交统计信息
    total_submissions = len(submissions)
    average_score = sum(s.score or 0 for s in submissions) / total_submissions if total_submissions > 0 else 0
    best_submission = max(submissions, key=lambda s: s.score or 0) if submissions else None
    best_score = best_submission.score if best_submission else 0
    
    # 按时间分组的提交
    submissions_by_date = {}
    for submission in submissions:
        date_key = submission.submitted_at.strftime('%Y-%m-%d')
        if date_key not in submissions_by_date:
            submissions_by_date[date_key] = []
        submissions_by_date[date_key].append(submission)
    
    # 渲染模板
    return render_template(
        'submission_history.html',
        assignment=assignment,
        submissions=submissions,
        submissions_by_date=submissions_by_date,
        student=student,
        stats={
            'total': total_submissions,
            'average_score': average_score,
            'best_score': best_score
        }
    )
            
@assignments.route('/teacher')
@login_required
@teacher_required
def teacher_assignments():
    """教师查看自己创建的作业列表"""
    # 只获取当前教师创建的作业
    teacher_assignments = Assignment.query.filter_by(creator_id=current_user.student_id).order_by(Assignment.id.desc()).all()
    
    # 获取教师管理的班级名称列表
    managed_classes = [cls.name for cls in current_user.managed_classes]
    
    # 为每个作业添加一个状态，表示是否已布置给教师的班级
    for assignment in teacher_assignments:
        assigned_to_my_classes = []
        target_classes = assignment.get_target_class_list()
        for cls_name in target_classes:
            if cls_name in managed_classes:
                assigned_to_my_classes.append(cls_name)
        assignment.assigned_to_my_classes = assigned_to_my_classes

    return render_template('teacher_assignments.html', assignments=teacher_assignments, current_time=datetime.utcnow())


@assignments.route('/assign/<int:assignment_id>', methods=['GET', 'POST'])
@login_required
@teacher_required
def assign_to_classes(assignment_id):
    """为教师的班级指派作业"""
    assignment = Assignment.query.get_or_404(assignment_id)
    managed_classes = current_user.managed_classes.all()
    
    if request.method == 'POST':
        # 获取教师从表单中选择的班级
        selected_class_names = request.form.getlist('class_names')
        
        # 获取该作业当前已分配的所有班级
        current_target_classes = set(assignment.get_target_class_list())
        
        # 从当前列表中移除该教师管理的所有班级，以便用新的选择替换
        teacher_class_names = {cls.name for cls in managed_classes}
        current_target_classes -= teacher_class_names
        
        # 添加教师本次选择的班级
        new_target_classes = current_target_classes.union(set(selected_class_names))
        
        # 更新作业的目标班级列表
        assignment.set_target_classes(list(new_target_classes))
        
        try:
            db.session.commit()
            flash(f'作业 "{assignment.title}" 的班级分配已更新。', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败: {str(e)}', 'danger')
            
        return redirect(url_for('assignments.teacher_assignments'))

    # GET请求：准备数据以渲染表单
    assigned_classes = set(assignment.get_target_class_list())
    return render_template('assign_form.html', assignment=assignment, managed_classes=managed_classes, assigned_classes=assigned_classes)


@assignments.route('/teacher/add', methods=['GET', 'POST'])
@login_required
@teacher_required
def add_teacher_assignment():
    """教师创建新作业"""
    form = AssignmentForm()
    if form.validate_on_submit():
        # 检查作业ID是否已存在
        assignment_id = form.assignment_id.data
        existing_assignment = Assignment.query.get(assignment_id)
        
        if existing_assignment:
            flash('该作业ID已存在，请使用其他ID', 'danger')
            return render_template('teacher_add_assignment.html', form=form)

        new_assignment = Assignment(
            id=form.assignment_id.data,
            title=form.title.data,
            description=form.description.data,
            due_date=form.due_date.data,
            creator_id=current_user.student_id, # Set the creator
            total_score=0,
            average_score=0.0,
            count=0
        )
        
        try:
            db.session.add(new_assignment)
            db.session.commit()
            
            # 触发异步生成预设任务
            try:
                from utils.async_tasks import add_generate_preset_task
                add_generate_preset_task(new_assignment.id)
            except Exception as e:
                current_app.logger.error(f"触发预设生成任务失败: {e}")
                
            flash('作业创建成功！', 'success')
            # AJAX 提交时返回 JSON，普通提交时重定向
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': True, 'assignment_id': new_assignment.id,
                                 'redirect': url_for('assignments.teacher_assignments')})
            return redirect(url_for('assignments.teacher_assignments'))
        except Exception as e:
            db.session.rollback()
            flash(f'创建作业失败: {str(e)}', 'danger')
            
    return render_template('teacher_add_assignment.html', form=form)


@assignments.route('/teacher/edit/<int:assignment_id>', methods=['GET', 'POST'])
@login_required
@teacher_required
def edit_assignment(assignment_id):
    """编辑作业详情"""
    assignment = Assignment.query.get_or_404(assignment_id)
    
    # 鉴权：只有管理员或该作业的创建者可以修改
    if current_user.usertype != '管理员' and assignment.creator_id != current_user.student_id:
        flash('您没有权限修改此作业', 'danger')
        return redirect(url_for('assignments.teacher_assignments'))
    
    form = AssignmentForm()
    
    if request.method == 'GET':
        form.assignment_id.data = assignment.id
        form.title.data = assignment.title
        form.description.data = assignment.description
        form.due_date.data = assignment.due_date
    
    if form.validate_on_submit():
        assignment.title = form.title.data
        assignment.description = form.description.data
        assignment.due_date = form.due_date.data
        
        try:
            db.session.commit()
            
            # 触发异步生成预设任务，以便更新
            try:
                from utils.async_tasks import add_generate_preset_task
                add_generate_preset_task(assignment.id)
            except Exception as e:
                current_app.logger.error(f"触发预设生成任务失败: {e}")
                
            flash('作业更新成功！', 'success')
            
            # AJAX 提交时返回 JSON，支持测试用例同步保存
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': True, 'assignment_id': assignment.id,
                                 'redirect': url_for('assignments.teacher_assignments')})
            return redirect(url_for('assignments.teacher_assignments'))
        except Exception as e:
            db.session.rollback()
            flash(f'更新作业失败: {str(e)}', 'danger')
            
    return render_template('edit_assignment.html', form=form, assignment=assignment)
