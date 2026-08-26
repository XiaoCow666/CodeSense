"""
CodeSense 酷森思 - 基于机器学习的代码能力评价系统
主程序入口文件
版本: v0.2.0
修改日期: 2025-10-16
"""
import os
import sys
import logging
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from logging import FileHandler

from flask import Flask, request, session, flash, redirect, url_for
from flask_login import LoginManager
# Flask-Session导入优化
try:
    from flask_session import Session
    HAS_FLASK_SESSION = True
except ImportError:
    print("⚠️ Flask-Session导入失败，Session功能将被禁用")
    Session = None
    HAS_FLASK_SESSION = False
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


# 添加当前目录到Python路径，确保可以正确导入模块
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 导入配置
from config import config
from models import db, init_db
from utils.code_evaluator import initialize_models
from utils.guidance_generator import initialize_guidance_system
from utils.code_advisor import initialize_code_advisor  # 导入代码建议系统初始化函数
from services.api_keys import api_keys  # 导入 API 密钥管理器

# 环境变量检查和警告
def check_environment_variables():
    """检查关键环境变量并提供警告"""
    warnings = []

    # 检查数据库配置
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        warnings.append("DATABASE_URL 未设置，将使用默认MySQL配置")

    # 检查SECRET_KEY
    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        warnings.append("SECRET_KEY 未设置，生产环境中请设置强密钥")
    elif secret_key in ['dev', 'dev-key-change-in-production']:
        warnings.append("使用默认SECRET_KEY，生产环境中请更改")

    # 检查AI服务配置（使用统一 API 密钥管理器）
    if not api_keys.has_any_key:
        warnings.append("未设置AI API密钥（ZHIPU_API_KEY或OPENAI_API_KEY），AI功能将不可用")

    # 显示警告
    if warnings:
        print("\n⚠️  环境变量警告：")
        for warning in warnings:
            print(f"  - {warning}")
        print()

    return len(warnings) == 0


def setup_logging(app):
    """配置Flask应用日志系统"""
    
    # 确保logs目录存在
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    # 配置日志格式
    formatter = logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d] - %(name)s'
    )
    
    # 根据不同环境设置不同的日志级别
    if app.debug:
        log_level = logging.DEBUG
        print("✓ 开发模式：启用DEBUG级别日志")
    else:
        log_level = logging.INFO
        print("✓ 生产模式：启用INFO级别日志")
    
    # 清除默认的handlers
    if app.logger.hasHandlers():
        app.logger.handlers.clear()
    
    # 1. 应用主日志文件 - 按日期轮转
    app_log_handler = TimedRotatingFileHandler(
        os.path.join(log_dir, 'app.log'),
        when='midnight',
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )
    app_log_handler.setLevel(log_level)
    app_log_handler.setFormatter(formatter)
    app.logger.addHandler(app_log_handler)
    
    # 2. 错误日志文件 - 按大小轮转
    error_log_handler = RotatingFileHandler(
        os.path.join(log_dir, 'error.log'),
        maxBytes=1024 * 1024 * 10,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    error_log_handler.setLevel(logging.ERROR)
    error_log_handler.setFormatter(formatter)
    app.logger.addHandler(error_log_handler)
    
    # 3. 访问日志处理器
    if app.debug:
        # 在开发/调试模式下，使用简单的文件处理器以避免Windows上的文件锁定问题
        access_log_handler = FileHandler(
            os.path.join(log_dir, 'access.log'), encoding='utf-8'
        )
        print("✓ 开发模式：为访问日志启用 FileHandler")
    else:
        # 在生产模式下，使用按时间轮转的处理器
        access_log_handler = TimedRotatingFileHandler(
            os.path.join(log_dir, 'access.log'),
            when='midnight',
            interval=1,
            backupCount=7,
            encoding='utf-8'
        )
        print("✓ 生产模式：为访问日志启用 TimedRotatingFileHandler")
    access_log_handler.setLevel(logging.INFO)
    access_formatter = logging.Formatter(
        '%(asctime)s %(message)s'
    )
    access_log_handler.setFormatter(access_formatter)
    
    # 创建访问日志记录器
    access_logger = logging.getLogger('access')
    access_logger.setLevel(logging.INFO)
    access_logger.addHandler(access_log_handler)
    
    # 4. 控制台输出 (仅在开发模式)
    if app.debug:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter('%(levelname)s: %(message)s')
        console_handler.setFormatter(console_formatter)
        app.logger.addHandler(console_handler)
    
    # 设置应用日志级别
    app.logger.setLevel(log_level)
    
    # 添加请求日志记录
    @app.before_request
    def log_request_info():
        if request.endpoint not in ['static', 'favicon']:  # 忽略静态文件请求
            access_logger.info(f'{request.remote_addr} - "{request.method} {request.path}" - User-Agent: {request.headers.get("User-Agent", "N/A")}')
    
    # 单点登录校验
    @app.before_request
    def check_single_session():
        # 忽略静态文件、静态资源
        if not request.endpoint or 'static' in request.endpoint or request.endpoint == 'favicon':
            return

        # 公开体验必须在任何 Flask-Login/业务查询发生前切换到本次会话的临时库。
        # 若临时库已经失效，服务会清除 demo 身份，绝不回退到正式库。
        from services.demo_database import activate_demo_request_database
        activate_demo_request_database()
            
        # 忽略测试环境，避免 Session 干扰
        if app.config.get('TESTING'):
            return

        # 允许登出操作
        if request.endpoint == 'auth.logout':
            return

        from flask_login import current_user, logout_user
        if current_user.is_authenticated:
            if getattr(current_user, 'is_demo', False):
                return
            # 检查Session中的ID是否与数据库中一致
            session_id = session.get('current_session_id')
            db_session_id = current_user.current_session_id
            
            # 调试日志
            # app.logger.debug(f"User: {current_user.student_id}, SessionID: {session_id}, DB_SessionID: {db_session_id}")
            
            if session_id != db_session_id:
                app.logger.warning(f"检测到并发登录: 用户 {current_user.username} (ID: {session_id} != DB: {db_session_id})，强制登出。")
                logout_user()
                flash('您的账号已在其他地方登录，当前会话已失效。', 'warning')
                return redirect(url_for('auth.login'))
    
    @app.after_request
    def log_response_info(response):
        if request.endpoint not in ['static', 'favicon']:  # 忽略静态文件请求
            access_logger.info(f'Response: {response.status_code} - {request.remote_addr} - "{request.method} {request.path}"')
        return response
    
    # 记录应用启动日志
    app.logger.info('=' * 50)
    app.logger.info('Flask应用日志系统初始化完成')
    app.logger.info(f'日志目录: {log_dir}')
    app.logger.info(f'日志级别: {logging.getLevelName(log_level)}')
    app.logger.info(f'应用模式: {"开发模式" if app.debug else "生产模式"}')
    app.logger.info('=' * 50)


def create_app(config_name='default'):
    """
    创建应用实例
    
    参数:
        config_name: 配置名称，默认为'default'
    
    返回:
        Flask应用实例
    """
    app = Flask(__name__)  # 创建Flask应用实例
    
    # 从配置对象中加载配置
    app.config.from_object(config[config_name])
    
    # 动态会话配置
    app.config['SESSION_PERMANENT'] = False
    app.config['SESSION_USE_SIGNER'] = True
    app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 会话有效期1天

    # 尝试加载 Redis 作为会话后端，解决并发时的磁盘 I/O 及锁问题
    redis_url = os.environ.get('REDIS_URL') or 'redis://127.0.0.1:6379/0'
    try:
        import redis
        r = redis.from_url(redis_url, socket_timeout=1)
        r.ping()
        app.config['SESSION_TYPE'] = 'redis'
        app.config['SESSION_REDIS'] = r
        app.config['SESSION_KEY_PREFIX'] = 'codesense_session:'
        print(f"[OK] Redis 会话后端加载成功: {redis_url}")
    except Exception as e:
        # 降级到文件系统会话
        app.config['SESSION_TYPE'] = 'filesystem'
        app.config['SESSION_FILE_DIR'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'flask_session')
        app.config['SESSION_KEY_PREFIX'] = 'flask_session:'
        # 确保session目录存在
        os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)
        print(f"[!] Redis 连接失败或未安装，已自动降级至文件系统会话 (filesystem): {str(e)}")
    
    # 设置Cookie安全选项
    # 通过环境变量SECURE_COOKIES控制Cookie安全设置
    secure_cookies_env = os.environ.get('SECURE_COOKIES', '').lower()
    if secure_cookies_env == 'true':
        app.config['SESSION_COOKIE_SECURE'] = True
    elif secure_cookies_env == 'false':
        app.config['SESSION_COOKIE_SECURE'] = False
    elif config_name == 'production':
        app.config['SESSION_COOKIE_SECURE'] = True  # 生产环境默认启用HTTPS安全Cookie
    else:
        app.config['SESSION_COOKIE_SECURE'] = False  # 开发环境默认不启用
        
    # 调用配置初始化
    config[config_name].init_app(app)
    
    # 配置日志系统
    print("\n正在配置应用日志系统...")
    setup_logging(app)
    app.logger.info(f"应用启动 - 配置: {config_name}")
    app.logger.info(f"数据库 URI: {app.config.get('SQLALCHEMY_DATABASE_URI')}")
    app.logger.info(f"实例路径: {app.instance_path}")
    
    # 初始化扩展
    db.init_app(app)

    # 注册自定义 Jinja2 过滤器
    import json as _json
    @app.template_filter('from_json')
    def from_json_filter(s):
        try:
            return _json.loads(s) if s else []
        except Exception:
            return []

    # 注册全局上下文变量
    @app.context_processor
    def inject_now():
        from datetime import datetime as dt_now
        return {'current_time': dt_now.utcnow()}
    
    # 初始化Flask-Session（如果可用）
    if HAS_FLASK_SESSION and Session is not None:
        Session(app)
        print("✓ Flask-Session初始化成功")
    else:
        print("⚠️ Flask-Session不可用，使用默认session实现")
    
    # 初始化Flask-Login
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'  # 设置登录视图的端点
    login_manager.login_message = '请先登录以访问此页面'  # 设置登录提示消息
    
    # 定义用户加载函数
    @login_manager.user_loader
    def load_user(user_id):
        # 从models模块导入User模型
        from models import User
        from services.demo_database import is_demo_login_id, load_demo_principal
        if is_demo_login_id(user_id):
            return load_demo_principal(user_id)
        return db.session.get(User, user_id)
    
    # 注册蓝图
    from routes.auth import auth
    from routes.main import main
    from routes.assignments import assignments
    from routes.users import users
    from routes.api import api
    from routes.classes import classes
    from routes.thinking import thinking  # 三阶段引导式学习
    from routes.grades import grades
    
    app.register_blueprint(auth)
    app.register_blueprint(main)
    app.register_blueprint(assignments)
    app.register_blueprint(users)
    app.register_blueprint(api)
    app.register_blueprint(classes)
    app.register_blueprint(thinking)  # /thinking/*
    app.register_blueprint(grades)
    
    # 初始化数据库
    with app.app_context():
        app.logger.info("开始初始化数据库...")
        init_db(app)
        app.logger.info("数据库初始化完成")
        
    # 预加载机器学习模型 - 添加错误处理和内存优化
    load_local_model = os.getenv('LOAD_LOCAL_MODEL', 'False').lower() == 'true'

    if load_local_model:
        print("\n正在初始化评估模型，请稍候...")
        app.logger.info("开始初始化评估模型...")
        try:
            initialize_models()
            print("✓ 评估模型初始化成功")
            app.logger.info("评估模型初始化成功")
        except Exception as e:
            error_msg = f"评估模型初始化失败: {str(e)}"
            print(f"× {error_msg}")
            print("应用将继续运行，但评估功能可能受限")
            app.logger.error(error_msg, exc_info=True)
            app.logger.warning("应用将继续运行，但评估功能可能受限")
    else:
        print("\n✓ 运行在 API-only 模式，跳过本地模型加载以节省内存")
        app.logger.info("运行在 API-only 模式，跳过本地模型加载")
    
    # 初始化编程指导系统
    if load_local_model:
        print("\n正在初始化编程指导系统，请稍候...")
        app.logger.info("开始初始化编程指导系统...")
        try:
            initialize_guidance_system()
            print("✓ 编程指导系统初始化成功")
            app.logger.info("编程指导系统初始化成功")
        except Exception as e:
            error_msg = f"编程指导系统初始化失败: {str(e)}"
            print(f"× {error_msg}")
            print("应用将继续运行，但指导功能可能受限")
            app.logger.error(error_msg, exc_info=True)
            app.logger.warning("应用将继续运行，但指导功能可能受限")
    else:
        app.logger.info("跳过编程指导系统初始化（API-only 模式）")
    
    # 初始化代码建议系统
    if load_local_model:
        print("\n正在初始化代码建议系统，请稍候...")
        app.logger.info("开始初始化代码建议系统...")
        try:
            initialize_code_advisor()
            print("✓ 代码建议系统初始化成功")
            app.logger.info("代码建议系统初始化成功")
        except Exception as e:
            error_msg = f"代码建议系统初始化失败: {str(e)}"
            print(f"× {error_msg}")
            print("应用将继续运行，但建议功能可能受限")
            app.logger.error(error_msg, exc_info=True)
            app.logger.warning("应用将继续运行，但建议功能可能受限")
    else:
        app.logger.info("跳过代码建议系统初始化（API-only 模式）")
    
    # 初始化异步任务系统
    print("\n正在初始化异步任务系统...")
    try:
        from utils.async_tasks import init_async_tasks
        init_async_tasks(app)
        print("✓ 异步任务系统初始化成功")
        app.logger.info("异步任务系统初始化成功")
    except Exception as e:
        error_msg = f"异步任务系统初始化失败: {str(e)}"
        print(f"× {error_msg}")
        app.logger.error(error_msg, exc_info=True)
    
    # 记录应用完全初始化完成
    app.logger.info("Flask应用完全初始化完成，准备接受请求")
    app.logger.info("-" * 50)
    
    return app


# 检查环境变量
print("正在检查环境变量配置...")
check_environment_variables()

# 创建应用实例
app = create_app(os.environ.get('FLASK_CONFIG') or 'development')  # 默认使用开发环境配置

# 应用创建完成后记录日志
app.logger.info("应用实例创建成功")
try:
    flask_version = getattr(Flask, '__version__', 'Unknown')
    app.logger.info(f"Flask版本: {flask_version}")
except AttributeError:
    app.logger.info("Flask版本: Unknown")
app.logger.info(f"Python版本: {sys.version}")

if __name__ == '__main__':
    print("应用启动中，请访问 http://127.0.0.1:5000/ 查看程序运行结果")
    app.logger.info("开始启动Flask开发服务器")
    app.logger.info("访问地址: http://127.0.0.1:5000/")
    try:
        host = os.environ.get('HOST', '0.0.0.0')
        port = int(os.environ.get('PORT', 5000))
        debug = os.environ.get('FLASK_DEBUG', 'True').lower() in ('true', '1', 't')
        app.run(debug=debug, host=host, port=port)
    except KeyboardInterrupt:
        app.logger.info("接收到中断信号，正在关闭服务器...")
    except Exception as e:
        app.logger.critical(f"应用启动失败: {str(e)}", exc_info=True)
