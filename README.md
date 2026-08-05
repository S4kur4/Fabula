# Fabula

Fabula 是一个多摄影师共同展示、各自维护内容的轻量摄影站。公开站汇集所有已发布作品和摄影师介绍，登录后每位摄影师只管理自己的摄影集、照片故事与 About。管理员负责用户生命周期和站点公共文案，不获得其他摄影师内容的编辑权。

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

如果管理员忘记密码，可通过交互式命令设置一次性临时密码：

```bash
flask --app wsgi reset-admin-password
```

命令会隐藏密码输入、撤销该管理员的现有会话、写入审计事件，并要求管理员下次登录后立即更换临时密码。为避免绕过账号治理流程，命令不会重置普通用户，也不会恢复已停用的管理员账号。

如果只想查看带图片和多角色账号的演示：

```bash
flask --app wsgi seed-demo
flask --app wsgi run --port 5002
```

## Docker 部署

```bash
cp .env.example .env
docker compose build
docker compose run --rm web flask --app wsgi bootstrap-admin
docker compose up -d
```

容器运行后，可使用以下命令重置管理员密码：

```bash
docker compose exec web flask --app wsgi reset-admin-password
```

如果 Web 容器尚未启动，则使用：

```bash
docker compose run --rm web flask --app wsgi reset-admin-password
```

默认只监听宿主机 `127.0.0.1:5002`。生产环境建议在前方配置 HTTPS 反向代理，并设置：

```dotenv
FABULA_ENV=production
FABULA_SECURE_COOKIE=true
FABULA_TRUST_PROXY_HEADERS=true
```

生产模式会拒绝在 `FABULA_SECURE_COOKIE=false` 时启动。只有在反向代理会清理并重新写入 `X-Forwarded-For` 时才启用 `FABULA_TRUST_PROXY_HEADERS`。容器默认只读、丢弃 Linux capabilities，并启用 `no-new-privileges`。仅 `/app/var` 和临时目录可写。`/healthz` 只表示进程存活，Compose 使用 `/readyz` 同时检查数据库与数据目录是否可用。

新建账号和管理员重置账号时，临时密码由服务端随机生成，只显示一次，默认在 15 分钟后失效。可通过 `FABULA_TEMPORARY_PASSWORD_TTL_SECONDS` 调整为 60 至 86400 秒。升级后，历史上尚未完成首次改密且没有有效期记录的临时密码会被拒绝；管理员需要重新生成临时密码，初始管理员则可使用 `reset-admin-password` 命令恢复。

图片上传支持 JPEG、PNG、WebP 以及 iPhone 常用的 HEIF/HEIC。所有输入都会经过格式识别、像素与尺寸检查，再重新编码为 WebP，不会直接保存用户上传的原始文件。HEIF 解码关闭缩略图、景深图和辅助图读取，并限制为单线程；高像素 JPEG 会在完整解码前由解码器降采样。图片处理默认允许不超过 5000 万像素、单边不超过 12000 像素的源图片，输出长边不超过 2400 像素，并在单个进程内串行处理。可以通过 `FABULA_MAX_IMAGE_PIXELS` 和 `FABULA_MAX_IMAGE_DIMENSION` 进一步降低限制，但不能提高到内置安全上限以上。Compose 同时限制容器为 512 MiB 内存和 128 个进程。

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
- `site/`：管理员设置的首页与登录页照片

备份时应同时保留整个 `var/`。最简单且一致的方式是先停止写入，再复制该目录：

```bash
docker compose stop web
tar -czf fabula-backup.tar.gz var
docker compose start web
```

备份文件包含账号和会话密钥，应加密保存并限制访问。恢复时保持文件所有者和权限，并在上线前验证 `/healthz`、登录、图片访问及权限隔离。

## 测试

```bash
python -m unittest discover -s tests -v
```
