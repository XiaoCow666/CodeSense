"""
CodeSense 酷森思 - 基于机器学习的代码能力评价系统
主程序入口文件
版本: v0.2.0
修改日期: 2025-10-16
"""
import os
import sys
import logging
import gzip
import re
import threading
import time
import uuid
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from logging import FileHandler

from flask import Flask, request, session, flash, redirect, url_for, g, jsonify, send_file
from flask_login import LoginManager
from werkzeug.middleware.proxy_fix import ProxyFix
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
from services.api_keys import api_keys  # 导入 API 密钥管理器
from utils.timezone import format_display_datetime


def _env_bool(name, default=False):
    """读取布尔环境变量，非法值时使用安全默认值。"""

    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


def _configure_proxy_headers(app, config_name):
    """让 HTTPS 反向代理后的请求恢复真实 scheme/host 信息。

    生产部署通常由 Nginx 终止 TLS，再通过 HTTP 转发给 Gunicorn。若不信任
    Nginx 传来的 X-Forwarded-* 头，Flask 会把外部 HTTPS 请求误判成 HTTP，
    造成外部 URL、重定向和安全 Cookie 行为不一致。默认只信任一个代理跳数，
    与当前线上拓扑（Nginx -> Gunicorn）匹配；直连开发环境默认关闭。
    """

    enabled = _env_bool('TRUST_PROXY_HEADERS', config_name == 'production')
    try:
        hops = int(os.environ.get('PROXY_FIX_HOPS', '1'))
    except (TypeError, ValueError):
        hops = 1
    hops = max(0, min(hops, 5))

    app.config['CODESENSE_PROXY_HEADERS_ENABLED'] = bool(enabled and hops)
    app.config['CODESENSE_PROXY_HEADERS_HOPS'] = hops
    if not enabled or not hops:
        return

    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=hops,
        x_proto=hops,
        x_host=hops,
        x_port=hops,
        x_prefix=hops,
    )


def _redact_connection_url(value):
    """日志中只显示连接地址，不泄露数据库/Redis密码。"""

    if not value:
        return value
    # 覆盖 user:password@ 和常见 query 参数形式；不记录密钥原文。
    redacted = re.sub(r'(?<=://)([^:/@]+):([^@]+)@', r'\1:***@', str(value))
    redacted = re.sub(
        r'((?:password|passwd|token|secret|api[_-]?key)=)[^&]+',
        r'\1***',
        redacted,
        flags=re.IGNORECASE,
    )
    return redacted


def _configure_database_engine(app):
    """Apply bounded, database-specific SQLAlchemy engine settings."""

    uri = str(app.config.get('SQLALCHEMY_DATABASE_URI') or '')
    if uri.startswith('sqlite:'):
        # SQLite is used by local/demo sessions. A busy timeout avoids quick
        # "database is locked" failures while keeping the demo isolated.
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'connect_args': {
                'check_same_thread': False,
                'timeout': 15,
            }
        }
        return

    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': app.config['DB_POOL_RECYCLE'],
        'pool_size': app.config['DB_POOL_SIZE'],
        'max_overflow': app.config['DB_MAX_OVERFLOW'],
        'pool_timeout': app.config['DB_POOL_TIMEOUT'],
        'pool_reset_on_return': 'rollback',
    }

# 环境变量检查和警告
def check_environment_variables():
    """检查关键环境变量并提供警告"""
    warnings = []

    # 检查数据库配置
    db_url = os.environ.get('DATABASE_URL') or os.environ.get('DEV_DATABASE_URL')
    if not db_url:
        warnings.append("未设置 DATABASE_URL/DEV_DATABASE_URL，将使用本地 SQLite 数据库")

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
    
    # 清除重复初始化留下的 handlers，并主动关闭文件句柄。测试套件和
    # Gunicorn 的应用探测都可能多次创建 app，不能让每次创建都叠加一份日志。
    for handler in list(app.logger.handlers):
        app.logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    
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
    
    # 3. 访问日志处理器。生产环境通常交给 Gunicorn/Nginx 记录；关闭时
    # 使用 NullHandler，避免每个 worker 无意义地打开并持有 access.log。
    access_log_enabled = app.config.get(
        'ACCESS_LOG_ENABLED', _env_bool('ACCESS_LOG_ENABLED', app.debug)
    )
    if access_log_enabled:
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
    else:
        access_log_handler = logging.NullHandler()
        print("✓ 访问日志已关闭：由外部 Web 服务器负责记录")
    access_log_handler.setLevel(logging.INFO)
    access_formatter = logging.Formatter(
        '%(asctime)s %(message)s'
    )
    access_log_handler.setFormatter(access_formatter)
    
    # 创建访问日志记录器
    access_logger = logging.getLogger('access')
    access_logger.setLevel(logging.INFO)
    access_logger.propagate = False
    for handler in list(access_logger.handlers):
        access_logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
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
    
    app.config.setdefault('ACCESS_LOG_ENABLED', _env_bool('ACCESS_LOG_ENABLED', app.debug))
    app.config.setdefault('SLOW_REQUEST_MS', 800)
    app.extensions['codesense_metrics'] = {
        'started_at': time.monotonic(),
        'lock': threading.Lock(),
        'requests': 0,
        'errors': 0,
        'slow_requests': 0,
    }

    # 只保留一条精简的响应日志，并记录慢请求计数。逐请求写入完整
    # User-Agent 会放大磁盘 I/O，生产环境默认由 Gunicorn/Nginx 记录访问日志。
    @app.before_request
    def start_request_timer():
        g.codesense_request_started = time.perf_counter()
        # Generate correlation data inside the trusted request context.  Do
        # not accept a caller-supplied id: access and LLM logs must remain
        # opaque and bounded even when a client sends arbitrary headers.
        g.codesense_request_id = str(uuid.uuid4())
    
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
        started = getattr(g, 'codesense_request_started', None)
        duration_ms = ((time.perf_counter() - started) * 1000) if started else 0
        request_id = getattr(g, 'codesense_request_id', None)
        if not request_id:
            request_id = str(uuid.uuid4())
        is_static = request.endpoint in ['static', 'favicon']
        metrics = app.extensions.get('codesense_metrics')
        if metrics:
            with metrics['lock']:
                metrics['requests'] += 1
                if response.status_code >= 500:
                    metrics['errors'] += 1
                if duration_ms >= app.config['SLOW_REQUEST_MS']:
                    metrics['slow_requests'] += 1

        if not is_static:
            line = (
                f'{request.remote_addr} "{request.method} {request.path}" '
                f'{response.status_code} {duration_ms:.0f}ms '
                f'request_id={request_id}'
            )
            if app.config.get('ACCESS_LOG_ENABLED'):
                access_logger.info(line)
            elif duration_ms >= app.config['SLOW_REQUEST_MS']:
                app.logger.warning('慢请求: %s', line)
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

    # FLASK_DEBUG 只影响 app.run 时还不够；日志级别、模板缓存和
    # 调试中间件都应使用同一份明确配置。
    if 'FLASK_DEBUG' in os.environ:
        app.config['DEBUG'] = _env_bool('FLASK_DEBUG', app.config.get('DEBUG', False))

    # 线上 HTTPS 通常由 Nginx 终止，再转发到本机 Gunicorn。必须在请求进入
    # Flask 前恢复代理传来的真实 scheme，否则 HTTPS 会被误判为 HTTP。
    _configure_proxy_headers(app, config_name)

    # 必须在 db.init_app 前设置 engine options，否则 Flask-SQLAlchemy 会
    # 立即创建一个没有连接池边界的 engine。
    _configure_database_engine(app)
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = app.config.get(
        'STATIC_CACHE_SECONDS', 0
    )
    
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
        app.extensions['codesense_session_redis'] = r
        print(f"[OK] Redis 会话后端加载成功: {_redact_connection_url(redis_url)}")
    except Exception as e:
        # 降级到文件系统会话
        app.config['SESSION_TYPE'] = 'filesystem'
        app.config['SESSION_FILE_DIR'] = os.environ.get(
            'SESSION_FILE_DIR',
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'flask_session'),
        )
        app.config['SESSION_KEY_PREFIX'] = 'flask_session:'
        # 确保session目录存在
        os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)
        app.extensions['codesense_session_redis'] = None
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

    # 明确设置会话 Cookie 的作用域和安全属性，避免不同 Flask-Session 版本
    # 或不同部署方式产生不一致的默认值。
    app.config.setdefault('SESSION_COOKIE_HTTPONLY', True)
    app.config.setdefault('SESSION_COOKIE_SAMESITE', 'Lax')
    app.config.setdefault('SESSION_COOKIE_PATH', '/')
    if config_name == 'production':
        app.config['PREFERRED_URL_SCHEME'] = 'https'
        
    # 调用配置初始化
    config[config_name].init_app(app)
    
    # 配置日志系统
    print("\n正在配置应用日志系统...")
    setup_logging(app)
    app.logger.info(f"应用启动 - 配置: {config_name}")
    app.logger.info(
        "反向代理协议头: %s (hops=%s)",
        '已启用' if app.config.get('CODESENSE_PROXY_HEADERS_ENABLED') else '未启用',
        app.config.get('CODESENSE_PROXY_HEADERS_HOPS', 0),
    )
    app.logger.info(
        "数据库连接: %s",
        _redact_connection_url(app.config.get('SQLALCHEMY_DATABASE_URI')),
    )
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

    @app.template_filter('localtime')
    def localtime_filter(value, fmt='%Y-%m-%d %H:%M:%S'):
        """Render a stored UTC timestamp in the configured display timezone."""
        return format_display_datetime(value, fmt)

    # 注册全局上下文变量
    @app.context_processor
    def inject_now():
        from datetime import datetime as dt_now
        notification_unread_count = 0
        student_id = session.get('student_id') if session.get('login') else None
        if student_id:
            try:
                from services.notifications import count_unread
                notification_unread_count = count_unread(student_id)
            except Exception:
                # Notification rendering must never make an otherwise healthy
                # page unavailable; the inbox remains the source of detail.
                app.logger.warning('站内通知未读数读取失败', exc_info=True)
        return {
            'current_time': dt_now.utcnow(),
            'notification_unread_count': notification_unread_count,
        }
    
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

    @app.after_request
    def compress_text_response(response):
        """压缩普通 HTML/JSON 响应；不触碰 SSE 和其它流式响应。"""

        if not app.config.get('ENABLE_RESPONSE_COMPRESSION'):
            return response
        if response.is_streamed or response.status_code in (204, 304):
            return response
        if response.headers.get('Content-Encoding'):
            return response
        if 'gzip' not in request.headers.get('Accept-Encoding', '').lower():
            return response
        content_type = (response.content_type or '').lower()
        compressible = (
            content_type.startswith('text/')
            or 'application/json' in content_type
            or 'application/javascript' in content_type
            or 'application/xml' in content_type
        )
        if not compressible:
            return response
        body = response.get_data()
        if len(body) < 1024:
            return response
        response.set_data(gzip.compress(body, compresslevel=6))
        response.headers['Content-Encoding'] = 'gzip'
        response.headers['Vary'] = 'Accept-Encoding'
        response.headers.pop('Content-Length', None)
        return response

    @app.get('/favicon.ico')
    def favicon():
        """Serve the same lightweight brand icon for browser defaults."""

        return send_file(
            os.path.join(app.root_path, 'static', 'img', 'favicon.svg'),
            mimetype='image/svg+xml',
        )

    @app.get('/healthz')
    def healthz():
        """轻量存活探针，不访问数据库，供负载均衡器快速检查。"""

        started_at = app.extensions.get('codesense_metrics', {}).get('started_at')
        uptime = max(0, int(time.monotonic() - started_at)) if started_at else 0
        return jsonify({'status': 'ok', 'uptime_seconds': uptime})

    @app.get('/readyz')
    def readyz():
        """就绪探针：只检查应用真正依赖的数据库连接。"""

        try:
            db.session.execute(db.text('SELECT 1'))
            db_status = 'ok'
            status_code = 200
        except Exception:
            db.session.rollback()
            db_status = 'unavailable'
            status_code = 503
        return jsonify({'status': 'ready' if status_code == 200 else 'not_ready',
                        'checks': {'database': db_status}}), status_code
    
    # 初始化数据库
    with app.app_context():
        if app.config.get('DB_AUTO_INIT', True):
            app.logger.info("开始初始化数据库...")
            init_db(app)
            app.logger.info("数据库初始化完成")
        else:
            app.logger.info("生产模式跳过启动期数据库建表/迁移；请先运行 database_maintenance.py")
        try:
            from services.demo_database import cleanup_expired_demo_runs
            removed_demo_runs = cleanup_expired_demo_runs()
            if removed_demo_runs:
                app.logger.info("启动清理了 %s 个过期体验临时库", removed_demo_runs)
        except Exception:
            # Demo cleanup is maintenance and must not prevent the formal
            # application from starting when a stale file is locked.
            app.logger.exception("启动清理体验临时库失败")
        
    # 代码评估不依赖仓库内的本地训练模型资源。
    # 评估时按需使用启发式规则和已配置的 AI 服务。
    app.logger.info("使用启发式规则和已配置的 AI 服务进行代码评估")
    
    # 初始化异步任务系统。生产环境可通过环境变量关闭进程内队列，
    # 交给 Celery/RQ 等独立 worker；这样不会让每个 Web worker 各自复制一套任务线程。
    if app.config.get('ASYNC_TASKS_ENABLED', True):
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
    else:
        app.logger.info("异步任务系统已按配置关闭")
    
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
