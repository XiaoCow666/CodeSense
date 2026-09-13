"""
表单处理模块
"""
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import StringField, PasswordField, SubmitField, TextAreaField, SelectField, HiddenField, RadioField, IntegerField, DateTimeLocalField
from wtforms.validators import DataRequired, Length, EqualTo, Email, ValidationError, Optional, NumberRange


class LoginForm(FlaskForm):
    """登录表单"""
    username = StringField(
        '用户名、学号或邮箱',
        validators=[DataRequired(message='用户名、学号或邮箱不能为空'), Length(1, 120)],
    )
    password = PasswordField('密码', validators=[DataRequired(message='密码不能为空')])
    submit = SubmitField('登录')


class PasswordResetRequestForm(FlaskForm):
    """密码重置申请表单。"""
    identifier = StringField(
        '用户名、学号或邮箱',
        validators=[
            DataRequired(message='请输入用户名、学号或邮箱'),
            Length(1, 120),
        ],
    )
    submit = SubmitField('发送重置链接')


class ResetPasswordForm(FlaskForm):
    """使用一次性令牌设置新密码的表单。"""
    token = HiddenField('重置令牌', validators=[DataRequired()])
    password = PasswordField(
        '新密码',
        validators=[
            DataRequired(message='新密码不能为空'),
            Length(8, 64, message='新密码长度应为 8-64 位'),
        ],
    )
    confirm_password = PasswordField(
        '确认新密码',
        validators=[
            DataRequired(message='确认新密码不能为空'),
            EqualTo('password', message='两次输入的新密码不匹配'),
        ],
    )
    submit = SubmitField('重置密码')


class AdminPasswordResetForm(FlaskForm):
    """管理员生成一次性密码重置链接的表单。"""
    pass


class RegistrationForm(FlaskForm):
    """注册表单"""
    username = StringField('用户名', validators=[DataRequired(message='用户名不能为空'), Length(1, 50)])
    # 学号对教学班学生是必需的，但自由用户可以先注册，再凭教师加入码入班。
    student_id = StringField('学号/教师工号', validators=[Optional(), Length(0, 20)])
    password = PasswordField('密码', validators=[DataRequired(message='密码不能为空'), Length(6, 20)])
    confirm_password = PasswordField('确认密码', validators=[
        DataRequired(message='确认密码不能为空'), 
        EqualTo('password', message='两次输入的密码不匹配')
    ])
    full_name = StringField('姓名', validators=[DataRequired(message='姓名不能为空'), Length(1, 50)])
    email = StringField('邮箱', validators=[Optional(), Email(message='邮箱格式不正确'), Length(0, 120)])
    class_name = StringField('班级', validators=[Optional(), Length(0, 50)])
    usertype = RadioField('用户类型', choices=[('学生', '学生'), ('管理员', '管理员')], default='学生')
    admin_password = PasswordField('管理员密码', validators=[Optional()])
    submit = SubmitField('注册')


class EmailRegistrationForm(FlaskForm):
    """独立的邮箱注册表单，不要求预先导入学生名单。"""
    username = StringField(
        '用户名',
        validators=[DataRequired(message='用户名不能为空'), Length(1, 50)],
    )
    email = StringField(
        '邮箱',
        validators=[
            DataRequired(message='邮箱不能为空'),
            Email(message='邮箱格式不正确'),
            Length(3, 120),
        ],
    )
    full_name = StringField(
        '姓名或昵称',
        validators=[Optional(), Length(0, 50)],
    )
    password = PasswordField(
        '密码',
        validators=[
            DataRequired(message='密码不能为空'),
            Length(8, 64, message='密码长度应为 8-64 位'),
        ],
    )
    confirm_password = PasswordField(
        '确认密码',
        validators=[
            DataRequired(message='确认密码不能为空'),
            EqualTo('password', message='两次输入的密码不匹配'),
        ],
    )
    submit = SubmitField('注册并验证邮箱')


class EmailVerificationRequestForm(FlaskForm):
    """重新发送注册邮箱验证邮件的表单。"""
    email = StringField(
        '注册邮箱',
        validators=[
            DataRequired(message='请输入注册邮箱'),
            Email(message='邮箱格式不正确'),
            Length(3, 120),
        ],
    )
    submit = SubmitField('重新发送验证邮件')


class EmailVerificationForm(FlaskForm):
    """确认邮箱验证令牌的表单。"""
    token = HiddenField('邮箱验证令牌', validators=[DataRequired()])
    submit = SubmitField('验证邮箱')


class AssignmentForm(FlaskForm):
    """作业表单"""
    assignment_id = IntegerField('作业ID', validators=[DataRequired(message='作业ID不能为空'), 
                                               NumberRange(min=1, message='作业ID必须为正整数')])
    title = StringField('标题', validators=[DataRequired(message='标题不能为空'), Length(1, 100)])
    description = TextAreaField('描述', validators=[DataRequired(message='描述不能为空')])
    due_date = DateTimeLocalField('截止日期', format='%Y-%m-%dT%H:%M', validators=[Optional()])
    submit = SubmitField('提交')


class SubmissionForm(FlaskForm):
    """代码提交表单"""
    code = TextAreaField('代码', validators=[DataRequired(message='代码不能为空')])
    language = HiddenField('编程语言', default='cpp')
    submit = SubmitField('提交')


class EditProfileForm(FlaskForm):
    """编辑资料表单"""
    username = StringField('用户名', validators=[DataRequired(message='用户名不能为空'), Length(1, 50)])
    full_name = StringField('姓名', validators=[DataRequired(message='姓名不能为空'), Length(1, 50)])
    email = StringField('邮箱', validators=[Optional(), Email(message='邮箱格式不正确'), Length(0, 120)])
    class_name = SelectField('班级', validators=[Optional()])
    bio = TextAreaField('个人简介', validators=[Optional(), Length(max=300, message='个人简介不能超过 300 个字符')])
    profile_visibility = SelectField(
        '公开范围',
        choices=[
            ('private', '仅自己和有权限的教学人员可见'),
            ('public', '允许通过公开链接查看基础资料'),
        ],
        validators=[Optional()],
        default='private',
    )
    avatar = FileField('头像', validators=[Optional(), FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'webp'], '仅支持 jpg、jpeg、png、gif、webp 格式')])
    submit = SubmitField('保存修改')


class ChangePasswordForm(FlaskForm):
    """修改密码表单"""
    current_password = PasswordField('当前密码', validators=[DataRequired(message='当前密码不能为空')])
    new_password = PasswordField('新密码', validators=[DataRequired(message='新密码不能为空'), Length(8, 64)])
    confirm_password = PasswordField('确认新密码', validators=[
        DataRequired(message='确认新密码不能为空'),
        EqualTo('new_password', message='两次输入的新密码不匹配')
    ])
    submit = SubmitField('修改密码')
