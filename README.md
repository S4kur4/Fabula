# Fabula

Fabula 是一个多摄影师共同展示、各自维护内容的轻量摄影站。公开站汇集所有已发布作品和摄影师介绍，登录后每位摄影师只管理自己的摄影集、照片故事与 About。管理员负责用户生命周期和站点公共文案，不获得其他摄影师内容的编辑权。

## 架构选择

- Flask 负责路由、权限、模板和 JSON API
- SQLite 负责用户、内容、审计与登录限速，启用 WAL
- Jinja 输出首屏，原生 JavaScript 负责渐进增强
- Pillow 验证、纠正方向、移除元数据并生成 WebP
- Gunicorn 使用单进程与多线程，避免 SQLite 多进程写入协调
- 不需要 Node、PostgreSQL、Redis、任务队列或前后端分离

运行时只有一个 Web 服务和一个持久化 `var` 目录。`var` 同时保存数据库、会话密钥和图片，便于备份与迁移。

## 已实现功能

- 公开 Gallery、摄影集筛选、照片标题与故事灯箱
- 公开 About 汇总所有摄影师各自维护的介绍
- 普通摄影师工作台，管理自己的摄影集、照片、故事和 About
- 管理员工作台，管理用户、角色、状态、临时密码、站点文案和全站配色
- 首位管理员通过一次性 CLI 创建，不采用“第一个用户自动成为管理员”
- 内容所有权校验、CSRF 防护、登录限速、会话撤销与安全响应头
- 图片类型和像素限制、重新编码、EXIF 方向纠正和元数据移除
- 管理操作审计、最后一位有效管理员保护、含内容用户删除保护
- 明暗主题、桌面与移动端布局、减少动态效果偏好支持
- 中英文界面切换，语言偏好按账号保存，用户自定义内容保持原文
- 可选 Cloudflare Turnstile 登录保护，服务端强制校验令牌

## 本地运行

建议使用 Python 3.13：

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app wsgi bootstrap-admin
flask --app wsgi run --port 5002
```

`bootstrap-admin` 只允许在用户表为空时执行。创建出的首位管理员首次登录后必须修改临时密码。

如果只想查看带图片和多角色账号的演示：

```bash
flask --app wsgi seed-demo
flask --app wsgi run --port 5002
```

演示账号：

- 管理员：`lin.qiu` / `fabula-demo-2026`
- 普通用户：`zhou.wang` / `fabula-user-2026`

演示初始化只允许在用户表为空时执行，不会覆盖已有数据。

## Docker 部署

```bash
cp .env.example .env
docker compose build
docker compose run --rm web flask --app wsgi bootstrap-admin
docker compose up -d
```

默认只监听宿主机 `127.0.0.1:5002`。生产环境建议在前方配置 HTTPS 反向代理，并设置：

```dotenv
FABULA_SECURE_COOKIE=true
FABULA_TRUST_PROXY_HEADERS=true
```

只有在反向代理会清理并重新写入 `X-Forwarded-For` 时才启用 `FABULA_TRUST_PROXY_HEADERS`。容器默认只读、丢弃 Linux capabilities，并启用 `no-new-privileges`。仅 `/app/var` 和临时目录可写。

### Cloudflare Turnstile

在 Cloudflare 控制台创建 Turnstile Widget，将生产域名加入允许列表，然后同时配置：

```dotenv
FABULA_TURNSTILE_SITE_KEY=your-site-key
FABULA_TURNSTILE_SECRET_KEY=your-secret-key
FABULA_TURNSTILE_EXPECTED_HOSTNAMES=example.com,www.example.com
FABULA_TURNSTILE_TIMEOUT_SECONDS=5
```

Site Key、Secret Key 和预期 hostname 必须完整配置，否则应用会拒绝启动，避免出现只展示组件但未完成服务端校验的失效保护。登录校验还会核对固定的 `login` action 与 Siteverify 返回的 hostname。Secret Key 只能存放在服务器环境变量或密钥管理系统中，不得写入代码或镜像。生产 Widget 不应允许 `localhost` 或 `127.0.0.1`。

## 数据与备份

持久化数据全部位于 `var/`：

- `fabula.db`：业务数据、登录限速和审计事件
- `secret.key`：会话签名密钥
- `media/`：原图和缩略图

备份时应同时保留整个 `var/`。最简单且一致的方式是先停止写入，再复制该目录：

```bash
docker compose stop web
tar -czf fabula-backup.tar.gz var
docker compose start web
```

备份文件包含账号和会话密钥，应加密保存并限制访问。恢复时保持文件所有者和权限，并在上线前验证 `/healthz`、登录、图片访问及权限隔离。

## 运维建议

- 小型团队继续使用单实例和 SQLite，部署最简单
- 先为 `var/` 做自动快照和异地加密备份，再考虑扩容
- 当出现多实例部署或持续高并发写入需求时，再迁移 PostgreSQL 与对象存储
- 反向代理限制请求体大小，并为 `/login` 增加第二层限速
- 定期检查 `audit_events`、停用离职账号并轮换临时密码

## 测试

```bash
python -m unittest discover -s tests -v
```
