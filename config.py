import os
import secrets


def _env_bool(name, default=False):
    """Read a boolean environment variable without raising on bad input."""

    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


def _env_int(name, default, minimum=None, maximum=None):
    """Read a bounded integer environment variable."""

    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


class Config(object):
    """
    基础配置类
    所有敏感信息都从环境变量中读取，不提供硬编码的默认值
    """

    def __init__(self):
        # 大模型评估配置
        self.use_llm = True  # 是否使用大模型评估
        self.llm_timeout = 10  # API调用超时时间(秒)

    # 应用程序密钥 - 从环境变量读取
    # 生产环境必须设置 SECRET_KEY 环境变量
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        # 开发环境生成临时密钥，生产环境会报错
        import sys
        if 'pytest' not in sys.modules:  # 非测试环境
            print("[!] 警告: SECRET_KEY 未设置，使用临时生成的密钥（仅限开发环境）")
            print("   生产环境请在 .env 文件中设置 SECRET_KEY")
        SECRET_KEY = secrets.token_hex(32)
    
    # 会话配置
    SESSION_COOKIE_AGE = None
    
    # 数据库配置
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_RECORD_QUERIES = False

    # 数据库连接池。实际的 SQLAlchemy engine options 会在 app factory 中
    # 根据 SQLite/MySQL 自动组装，避免把连接数乘到不可控。
    DB_POOL_SIZE = _env_int('DB_POOL_SIZE', 3, minimum=1, maximum=32)
    DB_MAX_OVERFLOW = _env_int('DB_MAX_OVERFLOW', 2, minimum=0, maximum=32)
    DB_POOL_TIMEOUT = _env_int('DB_POOL_TIMEOUT', 10, minimum=1, maximum=120)
    DB_POOL_RECYCLE = _env_int('DB_POOL_RECYCLE', 1800, minimum=60, maximum=86400)
    DB_AUTO_INIT = _env_bool('AUTO_INIT_DB', True)
    DB_ENSURE_INDEXES = _env_bool('DB_ENSURE_INDEXES', True)

    # 进程内后台任务适合单机小规模部署。多 worker 生产环境建议改用
    # 外部队列，并关闭每个 Web worker 的预扫描线程。
    ASYNC_TASKS_ENABLED = _env_bool('ASYNC_TASKS_ENABLED', True)
    ASYNC_WORKER_COUNT = _env_int('ASYNC_WORKER_COUNT', 1, minimum=0, maximum=8)
    ASYNC_MAX_QUEUE_SIZE = _env_int('ASYNC_MAX_QUEUE_SIZE', 1000, minimum=10, maximum=10000)
    PRESET_SCAN_ENABLED = _env_bool('PRESET_SCAN_ENABLED', True)
    PRESET_SCAN_BATCH_SIZE = _env_int('PRESET_SCAN_BATCH_SIZE', 20, minimum=1, maximum=200)

    # Formal-account ability analysis can be moved to an external RQ worker.
    # The legacy thread backend remains the default until worker deployment is
    # reviewed.  Demo sessions intentionally keep their isolated thread path.
    ABILITY_ANALYSIS_QUEUE_BACKEND = os.environ.get(
        'ABILITY_ANALYSIS_QUEUE_BACKEND', 'thread'
    ).strip().lower()
    ABILITY_ANALYSIS_REDIS_URL = os.environ.get('ABILITY_ANALYSIS_REDIS_URL', '')
    ABILITY_ANALYSIS_QUEUE_NAME = os.environ.get(
        'ABILITY_ANALYSIS_QUEUE_NAME', 'ability-analysis'
    )
    ABILITY_ANALYSIS_JOB_TIMEOUT = _env_int(
        'ABILITY_ANALYSIS_JOB_TIMEOUT', 180, minimum=30, maximum=900
    )
    ABILITY_ANALYSIS_QUEUE_TTL = _env_int(
        'ABILITY_ANALYSIS_QUEUE_TTL', 300, minimum=30, maximum=86400
    )
    ABILITY_ANALYSIS_RESULT_TTL = _env_int(
        'ABILITY_ANALYSIS_RESULT_TTL', 3600, minimum=60, maximum=604800
    )
    ABILITY_ANALYSIS_FAILURE_TTL = _env_int(
        'ABILITY_ANALYSIS_FAILURE_TTL', 86400, minimum=300, maximum=2592000
    )

    # 请求与静态文件运行参数
    ACCESS_LOG_ENABLED = _env_bool('ACCESS_LOG_ENABLED', True)
    SLOW_REQUEST_MS = _env_int('SLOW_REQUEST_MS', 800, minimum=50, maximum=60000)
    STATIC_CACHE_SECONDS = _env_int('STATIC_CACHE_SECONDS', 3600, minimum=0, maximum=31536000)
    ENABLE_RESPONSE_COMPRESSION = _env_bool('ENABLE_RESPONSE_COMPRESSION', False)
    
    # AI API配置 - 从环境变量读取
    ZHIPU_API_KEY = os.environ.get('ZHIPU_API_KEY', '')
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
    
    # 上传文件配置
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max-limit
    
    # 分页配置
    ITEMS_PER_PAGE = 10

    @staticmethod
    def init_app(app):
        """初始化应用配置"""
        if app.config.get('ABILITY_ANALYSIS_QUEUE_BACKEND') not in {'thread', 'rq'}:
            raise RuntimeError(
                'ABILITY_ANALYSIS_QUEUE_BACKEND must be either thread or rq'
            )

        if (
            app.config.get('ABILITY_ANALYSIS_QUEUE_BACKEND') == 'rq'
            and not app.config.get('ABILITY_ANALYSIS_REDIS_URL')
        ):
            raise RuntimeError(
                'ABILITY_ANALYSIS_REDIS_URL is required when the RQ backend is enabled'
            )


class DevelopmentConfig(Config):
    """开发环境配置"""
    DEBUG = True
    STATIC_CACHE_SECONDS = _env_int('STATIC_CACHE_SECONDS', 0, minimum=0, maximum=31536000)
    DB_AUTO_INIT = _env_bool('AUTO_INIT_DB', True)
    DB_ENSURE_INDEXES = _env_bool('DB_ENSURE_INDEXES', True)
    
    # 开发环境数据库配置
    # 从环境变量读取，如果没有则使用本地开发默认值
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        os.environ.get('DEV_DATABASE_URL') or \
        'sqlite:///dev_student_code_review.db'  # 默认使用SQLite作为开发数据库
    
    @staticmethod
    def init_app(app):
        Config.init_app(app)
        if 'sqlite' in app.config['SQLALCHEMY_DATABASE_URI']:
            app.logger.info("ℹ️  开发环境: 使用 SQLite 数据库")
            app.logger.info(f"   Database URI: {app.config['SQLALCHEMY_DATABASE_URI']}")
            app.logger.info(f"   Instance Path: {app.instance_path}")
            app.logger.info("   如需使用MySQL，请在 .env 中设置 DEV_DATABASE_URL")


class TestingConfig(Config):
    """测试环境配置"""
    TESTING = True
    DB_AUTO_INIT = True
    DB_ENSURE_INDEXES = True
    
    # 测试环境使用独立的SQLite数据库
    SQLALCHEMY_DATABASE_URI = os.environ.get('TEST_DATABASE_URL') or \
        'sqlite:///test_student_code_review.db'
    
    # 测试环境禁用CSRF保护
    WTF_CSRF_ENABLED = False
    
    @staticmethod
    def init_app(app):
        Config.init_app(app)


class ProductionConfig(Config):
    """生产环境配置"""
    DEBUG = False
    # 生产进程不在每个 worker 启动时执行 create_all/ALTER TABLE；请先运行
    # database_maintenance.py 完成一次性建表和索引维护。
    DB_AUTO_INIT = _env_bool('AUTO_INIT_DB', False)
    DB_ENSURE_INDEXES = _env_bool('DB_ENSURE_INDEXES', False)
    ACCESS_LOG_ENABLED = _env_bool('ACCESS_LOG_ENABLED', False)
    PRESET_SCAN_ENABLED = _env_bool('PRESET_SCAN_ENABLED', False)
    ENABLE_RESPONSE_COMPRESSION = _env_bool('ENABLE_RESPONSE_COMPRESSION', True)
    
    # 生产环境必须从环境变量获取数据库配置
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    
    # 生产环境安全配置
    # 注意：这些设置在 app.py 的 create_app 中可能会被环境变量进一步覆盖
    SESSION_COOKIE_HTTPONLY = True  # 防止JavaScript访问Cookie
    SESSION_COOKIE_SAMESITE = 'Lax'  # 防止CSRF攻击
    PERMANENT_SESSION_LIFETIME = 86400  # Session有效期1天 (24小时)
    
    @staticmethod
    def init_app(app):
        Config.init_app(app)
        
        # 生产环境必须设置的配置项检查
        required_vars = ['DATABASE_URL', 'SECRET_KEY']
        missing_vars = [var for var in required_vars if not os.environ.get(var)]
        
        if missing_vars:
            raise RuntimeError(
                f"❌ 生产环境缺少必需的环境变量: {', '.join(missing_vars)}\n"
                f"   请在 .env 文件或服务器环境中设置这些变量"
            )
        
        # 检查SECRET_KEY强度（至少32个字符）
        if len(os.environ.get('SECRET_KEY', '')) < 32:
            raise RuntimeError(
                "❌ SECRET_KEY 长度不足，生产环境至少需要32个字符\n"
                "   建议使用: python -c 'import secrets; print(secrets.token_hex(32))'"
            )
        
        # 检查是否配置了AI API密钥
        if not os.environ.get('ZHIPU_API_KEY') and not os.environ.get('OPENAI_API_KEY'):
            print("[!] 警告: 未配置 AI API 密钥，AI评估功能将不可用")
            print("   请在 .env 中设置 ZHIPU_API_KEY 或 OPENAI_API_KEY")
        
        print("[OK] 生产环境配置检查通过")

# 配置字典，用于在app.py中选择配置
config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    
    'default': DevelopmentConfig
}
