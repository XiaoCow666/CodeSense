# CodeSense 部署指南

这份文档面向把 CodeSense 部署到一台 Linux 服务器的场景。推荐拓扑是 Nginx 终止 HTTPS，Gunicorn 运行 Flask，MySQL 保存正式数据，Redis 保存多进程会话；C++ 评测和 AI 服务由应用按需调用。

~~~text
浏览器 ── HTTPS ──> Nginx ── HTTP ──> Gunicorn :5000
                                      ├── MySQL
                                      ├── Redis（推荐）
                                      ├── g++ / C++17 评测
                                      └── 智谱或 OpenAI API
~~~

仓库当前没有 Dockerfile 或官方容器镜像。若使用 Docker，需要额外设计数据库、密钥、上传目录、会话、队列和代码执行隔离。

## 1. 上线前的硬性要求

- Python 3.8+、g++ 和可写的应用目录；
- 生产环境必须设置 DATABASE_URL 和长度至少 32 个字符的随机 SECRET_KEY；
- AI 功能至少配置 ZHIPU_API_KEY 或 OPENAI_API_KEY；不配置时基础页面仍可启动，但 AI 功能不可用；
- 生产 HTTPS 必须使用 SECURE_COOKIES=true；Nginx → Gunicorn 拓扑使用 TRUST_PROXY_HEADERS=true 和 PROXY_FIX_HOPS=1；
- 学生提交的 C++ 代码只经过应用层限制，当前实现不是完整的 OS 级恶意代码隔离。公网部署必须补充容器/虚拟机、低权限账户、网络限制和资源配额。

## 2. 首次部署

以下命令以 Ubuntu/Debian 为例：

~~~bash
sudo apt update
sudo apt install -y python3-venv g++ nginx mysql-client redis-server

sudo mkdir -p /srv/codesense
sudo chown "$USER":"$USER" /srv/codesense
git clone https://github.com/XiaoCow666/CodeSense.git /srv/codesense
cd /srv/codesense

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

cp .env.example .env
chmod 600 .env
~~~

确认编译器：

~~~bash
g++ --version
~~~

## 3. 创建数据库

生产配置要求 DATABASE_URL。MySQL 用户和密码请通过服务器密钥管理或受限环境变量提供，不要写进 Git：

~~~sql
CREATE DATABASE codesense CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'codesense'@'127.0.0.1' IDENTIFIED BY 'replace-with-a-long-password';
GRANT ALL PRIVILEGES ON codesense.* TO 'codesense'@'127.0.0.1';
FLUSH PRIVILEGES;
~~~

在 .env 中填写：

~~~dotenv
FLASK_CONFIG=production
DATABASE_URL=mysql+pymysql://codesense:replace-with-a-long-password@127.0.0.1:3306/codesense?charset=utf8mb4
SECRET_KEY=replace-with-a-random-32-byte-secret

ZHIPU_API_KEY=your_server_side_key
OPENAI_API_KEY=

AUTO_INIT_DB=0
DB_ENSURE_INDEXES=0
SECURE_COOKIES=true
TRUST_PROXY_HEADERS=true
PROXY_FIX_HOPS=1
REDIS_URL=redis://127.0.0.1:6379/0
~~~

如果密码包含 @、:、/ 或 #，需要先进行 URL 编码，否则 SQLAlchemy 可能无法解析连接串。

### 单机试点的并发选择

仓库内的后台任务仍是进程内队列。小规模试点可以先使用一个 Web worker：

~~~dotenv
WEB_CONCURRENCY=1
WEB_THREADS=4
ASYNC_TASKS_ENABLED=1
~~~

如果启用多个 worker 或多台机器，建议使用 Redis 会话，并把后台任务迁移到独立队列后再关闭进程内任务；不要把多个 worker 的本地队列当成共享队列。

## 4. 初始化数据库并启动 Gunicorn

首次部署和数据库结构变更时，先运行一次维护命令：

~~~bash
cd /srv/codesense
source .venv/bin/activate
python database_maintenance.py
~~~

它会使用生产 DATABASE_URL 建表、补历史列和维护索引，不会启动 Web 服务或后台 AI 任务。

手动启动生产 WSGI：

~~~bash
cd /srv/codesense
source .venv/bin/activate
gunicorn -c gunicorn_config.py wsgi:application
~~~

默认监听 127.0.0.1:5000。[wsgi.py](wsgi.py) 会在没有显式设置时选择 production 配置；[gunicorn_config.py](gunicorn_config.py) 已包含 worker、线程、超时和日志配置。

## 5. 使用 Systemd 常驻

创建 /etc/codesense/codesense.env，内容与项目 .env 相同，权限设置为 600。然后创建 /etc/systemd/system/codesense.service：

~~~ini
[Unit]
Description=CodeSense Flask application
After=network.target mysql.service redis-server.service

[Service]
User=codesense
Group=www-data
WorkingDirectory=/srv/codesense
EnvironmentFile=/etc/codesense/codesense.env
ExecStart=/srv/codesense/.venv/bin/gunicorn -c /srv/codesense/gunicorn_config.py wsgi:application
Restart=always
RestartSec=5
PrivateTmp=true

[Install]
WantedBy=multi-user.target
~~~

创建运行用户并启动：

~~~bash
sudo useradd --system --home /srv/codesense --shell /usr/sbin/nologin codesense
sudo chown -R codesense:www-data /srv/codesense
sudo chmod 600 /etc/codesense/codesense.env
sudo systemctl daemon-reload
sudo systemctl enable --now codesense
sudo systemctl status codesense --no-pager
~~~

logs/、uploads/、flask_session/ 等目录只授予应用用户所需权限，不要使用全局可写权限。

## 6. 配置 Nginx 和 HTTPS

创建 /etc/nginx/sites-available/codesense：

~~~nginx
server {
    listen 80;
    server_name codesense.example.com;

    client_max_body_size 16m;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 180s;
        proxy_buffering off;
    }
}
~~~

启用配置并申请证书：

~~~bash
sudo ln -s /etc/nginx/sites-available/codesense /etc/nginx/sites-enabled/codesense
sudo nginx -t
sudo systemctl reload nginx

# 已将域名解析到本机后，再按实际域名申请证书
sudo certbot --nginx -d codesense.example.com
~~~

proxy_buffering off 对 SSE/流式响应很重要；HTTPS 启用后，确认 .env 中的安全 Cookie 和代理头设置仍然正确。

## 7. 验证部署

应用提供两个探针：

~~~bash
curl -i https://codesense.example.com/healthz
curl -i https://codesense.example.com/readyz
~~~

- /healthz：轻量存活检查，不访问数据库；
- /readyz：检查数据库是否可用，不就绪时返回 HTTP 503。

再验证：登录、学生体验、教师体验、C++ 编译评测、AI 失败/重试状态、文件上传和 SSE/流式响应。没有 AI Key 时，不要把“AI 不可用”误判为网站整体故障。

## 8. 发布新版本

~~~bash
cd /srv/codesense
git pull --ff-only origin main
source .venv/bin/activate
python -m pip install -r requirements.txt
python database_maintenance.py
sudo systemctl restart codesense

curl -fsS https://codesense.example.com/healthz
curl -fsS https://codesense.example.com/readyz
~~~

每次发布前记录 Git commit。新版本启动失败时，先停止继续重启，查看日志并恢复到上一个已验证版本，再处理数据库或环境变量问题。

## 9. 日志、备份与排障

~~~bash
sudo journalctl -u codesense -n 200 --no-pager
sudo tail -n 200 /var/log/nginx/error.log
sudo systemctl status redis-server --no-pager
~~~

至少备份：

- MySQL 数据库；
- 业务需要保留的 uploads/；
- 版本号、Git commit 和部署配置；
- 密钥的受控备份，不要把密钥备份放进仓库。

常见问题：

| 现象 | 检查顺序 |
| --- | --- |
| 502 Bad Gateway | systemctl status codesense、Gunicorn 监听端口、Nginx proxy_pass |
| /healthz 正常但 /readyz 503 | DATABASE_URL、MySQL 用户权限、网络和连接池 |
| 登录后会话丢失 | Redis 是否可用、REDIS_URL、HTTPS 下 SECURE_COOKIES 和代理头 |
| AI 请求失败 | AI Key、provider 顺序、网络出口、应用日志；查看页面失败/重试状态 |
| C++ 评测失败 | g++ --version、临时目录权限、超时/输出限制和沙箱边界 |
| 页面资源或 SSE 异常 | Nginx HTTPS 头、proxy_buffering off、proxy_read_timeout |

## 10. 发布前清单

- [ ] 生产环境使用随机 SECRET_KEY，且密钥文件权限为 600。
- [ ] DATABASE_URL 指向正式数据库，已完成备份和恢复演练。
- [ ] database_maintenance.py 已成功执行，/readyz 返回 200。
- [ ] g++ 已安装，代码执行目录权限和资源限制已复核。
- [ ] Nginx 已启用 HTTPS、代理头和流式响应配置。
- [ ] Redis/会话策略与 worker 数量匹配。
- [ ] 未把 .env、API Key、个人数据、生产日志或数据库文件提交到 Git。
- [ ] 已明确 AI 辅导不是人工教师替代品，代码评测隔离也不是完整的恶意代码防护。

## 相关入口

- [主 README](README.md)
- [英文 README](README.en.md)
- [环境变量模板](.env.example)
- [性能与容量评估](PERFORMANCE_CAPACITY.md)
- [GitHub Pages 发布源配置](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site?apiVersion=2022-11-28)
