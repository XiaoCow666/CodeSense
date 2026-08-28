# 源代码目录：CodeSense 酷森思

## 项目摘要

CodeSense 酷森思是面向高校编程教学的 Flask 平台，整合代码评测、因果隔离沙箱、启发式 AI 辅导和教师学情分析。核心学习流程为“思路描述 → 积木式编程 → 费曼教学”，AI 只提供引导，不直接投喂完整代码。

## 常用命令

```bash
# 安装依赖
python -m pip install -r requirements.txt

# 启动开发服务
python run.py
# 或
python app.py

# 运行全部测试
python -m pytest tests -q

# 运行单项测试
python -m pytest tests/test_app.py -q

# 生产服务
gunicorn -w 4 -b 0.0.0.0:5000 wsgi:app
```

配置使用 `.env.example` 作为模板；不要提交 `.env`、密钥或本地数据库文件。测试使用 `create_app("testing")` 和独立 SQLite 数据库。

## 目录索引

- `app.py`、`run.py`、`wsgi.py`：应用创建与启动入口。
- `routes/`：认证、页面、作业、班级、提交 API、三阶段学习和成绩路由。
- `services/`、`utils/`、`tasks/`：业务服务、评测与 AI 工具、异步任务。
- `models.py`、`models/`：数据库模型和本地评测模型。
- `templates/`、`static/`：页面模板和前端资源。
- `tests/`：应用、沙箱、演示体验、教师分析和引导式学习测试。

## 必须保持的约束

- 保持沙箱隔离和超时限制：编译 15 秒、运行 5 秒；不要为方便调试而放宽限制。
- 保持 `sanitize_response` 与提示词约束，AI 辅导不得输出完整答案代码。
- 演示体验使用临时数据库并与正式数据隔离；AI 失败时必须明确显示失败或重试，不得伪造结果。

## Git 与 PR 规则

每次项目改动都必须在独立分支提交并推送到 GitHub，创建或更新 PR，并详细备注改动内容、测试结果和注意事项。随后先向项目负责人申请合并；未经本人明确同意，不得推送或合并到 `main`，获准后方可合并。
