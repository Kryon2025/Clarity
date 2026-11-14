# 深清商店（网页端）部署指南

> 面向：想把「深清主题/插件商店」部署到自己云服务器的管理员。
> 代码位置：仓库 `server/`（FastAPI + SQLite + 原生前端，单进程即可运行）。

## 0. 先理解结构

- 网页端商店：`https://你的域名/` —— 登录 / 注册、浏览主题与插件、评论、开发者提交、管理员审核；
- 桌面端商店：深清设置里的 `store_catalog_url` 指向上面的 `/api/catalog.json`，桌面端只读取「已通过审核」的条目；
- 角色：`user`（普通用户，可评论）→ `developer`（可提交主题/插件）→ `admin`（审核、管理用户）；
- 初始管理员由环境变量 `ADMIN_EMAIL` / `ADMIN_PASSWORD` 在首次启动时创建。

## 1. 准备

- 一台云服务器（阿里云 / 腾讯云 / 华为云等）：1 核 2G 足够；Ubuntu 22.04 / Debian 12；
- 一个域名（备案要求按云厂商规定），解析 A 记录到服务器公网 IP；
- 安全组放行 80 / 443（不要放行 8000）。

## 2. 方式 A：Docker Compose（推荐）

服务器上：

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-plugin git
git clone https://github.com/Kryon2025/Clarity.git
cd Clarity/server
cp .env.example .env
```

编辑 `.env`：

```ini
SECRET_KEY=换成一串足够长的随机字符串
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=换成强密码
DATABASE_PATH=/data/store.db
```

启动：

```bash
docker compose up -d --build
curl http://127.0.0.1:8000/api/store/items   # 应返回 JSON
```

## 3. Nginx + HTTPS

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

`/etc/nginx/sites-available/shenqing-store`：

```nginx
server {
    listen 80;
    server_name store.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    client_max_body_size 20m;
}
```

```bash
sudo ln -s /etc/nginx/sites-available/shenqing-store /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d store.example.com   # 自动配置 HTTPS 并续期
```

完成后：

- 网页商店：`https://store.example.com/`
- 桌面端目录：`https://store.example.com/api/catalog.json`
- 在深清「设置 → 商店目录地址」填入上面的 catalog 地址（或改 `settings.json` 的 `store_catalog_url`）。

## 4. 方式 B：systemd 直跑（无 Docker）

```bash
sudo apt install -y python3.13 python3.13-venv nginx
cd /opt && git clone https://github.com/Kryon2025/Clarity.git shenqing-store
cd shenqing-store/server
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`/etc/systemd/system/shenqing-store.service`：

```ini
[Unit]
Description=ShenQing Store
After=network.target

[Service]
WorkingDirectory=/opt/shenqing-store/server
EnvironmentFile=/opt/shenqing-store/server/.env
ExecStart=/opt/shenqing-store/server/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now shenqing-store
sudo systemctl status shenqing-store
```

Nginx 与 HTTPS 同上。

## 4.5 邮箱验证码（注册 / 验证码登录 / 找回密码）

服务端支持邮箱验证码，需要配置 SMTP（不配置时进入开发模式：验证码只写日志并在接口返回 `dev_code`，不要用于公网）。

**免费 SMTP 选择（按场景挑一个）：**

| 服务 | 免费额度（以官网为准） | 适合 | 备注 |
| --- | --- | --- | --- |
| QQ 邮箱 SMTP | 免费，常见有每日上限（约 50–500 封） | 国内个人/小规模 | 需在 QQ 邮箱设置开启 SMTP 并用「授权码」当密码 |
| 163 / 126 邮箱 SMTP | 免费，有每日上限 | 国内个人 | 同样使用授权码 |
| 腾讯云 SES / 阿里云邮件推送 | 新用户有免费额度（几百~几千封，按活动） | 国内正式站点 | 需要域名验证（SPF/DKIM），送达率最好 |
| Brevo (Sendinblue) | 约 300 封/天 | 海外/国际用户 | SMTP 免费层，注册即用 |
| Resend | 约 100 封/天 | 海外、开发者友好 | 免费层可发测试域名 |
| SendGrid | 约 100 封/天 | 海外 | 免费层需审核用途 |
| Gmail SMTP | 约 500 封/天（应用专用密码） | 临时/测试 | 国内访问不稳定，建议仅测试 |

**配置方式（`.env`）：**

```ini
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USER=你的邮箱@qq.com
SMTP_PASSWORD=邮箱授权码
SMTP_FROM=深清商店 <你的邮箱@qq.com>
SMTP_SSL=1
SMTP_TLS=0
MAIL_DEV_MODE=0
EMAIL_CODE_TTL_SECONDS=600
EMAIL_CODE_MAX_ATTEMPTS=5
```

- 587 端口一般用 `SMTP_TLS=1`，465 端口用 `SMTP_SSL=1`；
- 正式站点建议用自有域名发信（腾讯云 SES / 阿里云 / Brevo 都可绑定域名），并配置 SPF/DKIM，否则容易进垃圾箱；
- 验证码规则：10 分钟有效、最多尝试 5 次、同邮箱 60 秒 1 次 / 每小时 5 次 / 每天 10 次；
- 配好后可用页面「找回密码」或「邮箱验证码登录」自测。

## 4.6 第三方登录与短信验证码（可行性与资质）

| 方式 | 个人能否申请 | 费用 | 说明 |
| --- | --- | --- | --- |
| 邮箱验证码 | ✅ 可以 | 免费（SMTP 免费额度） | 已内置，最推荐先用 |
| GitHub / Google OAuth | ✅ 可以 | 免费 | 只需注册 OAuth 应用，适合开发者用户 |
| QQ 登录（QQ 互联） | ✅ 个人可申请 | 免费 | 需要已备案域名、网站审核；审核约 1–7 天 |
| 微信扫码登录（开放平台网站应用） | ❌ 仅企业 | 300 元/年认证费 + 企业资质 | 个人开发者无法申请；公众号 H5 授权同样需要认证服务号 |
| 手机短信验证码（阿里云/腾讯云短信） | ⚠️ 可注册但需实名 + 签名/模板审核 | 新用户少量免费额度，之后约 0.04–0.05 元/条 | 个人可接，但模板审核严格、有最低消费门槛；国际可用 Twilio 试用额度 |

**建议路线：**

1. 先上线邮箱验证码（已经做好）：零成本、无资质要求；
2. 面向国内用户想加 QQ 登录：走 QQ 互联，个人主体可申请；
3. 微信登录：除非有企业主体和认证费预算，否则不建议个人项目接；
4. 短信验证码只在「防批量注册」确有需要时再接，优先用图形验证码 + 邮箱验证码替代；
5. 所有第三方登录都要在服务端做「state 校验 + 回调域名白名单 + 绑定已有账号」，不要只信前端。

## 4.7 账户云同步

桌面端「设置 → 账户同步」会把当前设置、空间与专注统计打包成一个 JSON 快照，通过商店服务端的 `/api/sync` 接口同步：

- 服务端按用户保存一份快照（revision 递增），换电脑登录同一账号即可拉取；
- 冲突处理：客户端先拉取远端 revision，若远端更新则下载覆盖（写前自动备份到数据目录 `backups/cloud-pre-pull-*.json`），否则上传本机；
- 服务端不解析 payload，仅存储；如担心隐私，客户端可自行加密后再上传（后续可加）；
- 接口：`GET /api/sync`、`PUT /api/sync`、`DELETE /api/sync`，需要登录令牌。

## 4.8 托管平台选择（Cloudflare Pages 只适合静态页）

深清商店是 **Python(FastAPI) + SQLite** 的服务，需要长期运行的进程和可写磁盘，Cloudflare Pages 只能托管静态文件，不能直接跑它。按预算选：

| 平台 | 免费/低成本 | 说明 |
| --- | --- | --- |
| **自己的 VPS（推荐）** | ¥30–60/月 | 按本文档 Docker Compose + Nginx + HTTPS 部署，SQLite 直接可用 |
| **Render / Railway / Fly.io / Zeabur** | 有免费或低价档 | 直接构建 `server/Dockerfile`，挂载持久卷存 `store.db`；注意免费档会休眠 |
| **Cloudflare Tunnel（家里电脑）** | 免费 | 本机跑 docker compose，用 `cloudflared tunnel --url http://127.0.0.1:8000` 拿临时公网地址；适合测试/小规模 |
| **Cloudflare Pages + Workers/D1** | 免费 | 需要把 FastAPI 重写成 Workers（JS）+ D1 数据库，工作量大，不建议现在做 |
| **Cloudflare Pages（仅前端）** | 免费 | 可把 `server/static` 放 Pages 当纯展示站，但登录/提交/审核仍需 API 域名（CORS + 跨域 token） |

**如果只想先把网页跑起来：**

1. 本机装 Docker，`cd server && docker compose up -d`；
2. 装 cloudflared：`cloudflared tunnel --url http://127.0.0.1:8000`，会得到一个 `https://xxx.trycloudflare.com` 地址；
3. 用这个地址访问网页商店；桌面端把商店目录地址填 `https://xxx.trycloudflare.com/api/catalog.json`；
4. 长期使用再换 VPS 或 Render，并把临时隧道换成固定域名。

> Cloudflare Pages 的拖拽上传（截图）只适用于纯 HTML/JS/CSS 静态站点；首页必须是 `index.html`，否则 404 —— 深清商店的主页正是静态文件，但 /api/* 需要后端，因此不能只靠 Pages。

## 5. 首次使用

1. 浏览器打开 `https://你的域名/`，用 `ADMIN_EMAIL/ADMIN_PASSWORD` 登录；
2. 「管理后台 → 用户」把可信开发者提升为 `developer`；
3. 开发者到「开发者中心」提交主题/插件（填写下载地址，插件需是含 `plugin.json` 的 zip）；
4. 管理员在「待审核」里通过或拒绝（拒绝需写原因，开发者能看到）；
5. 通过后自动出现在公开商店与桌面端目录里。

## 6. 运维

- **备份**：`docker compose exec app cp /data/store.db /data/store.db.bak`，或定时 `sqlite3 /data/store.db ".backup /backup/store-$(date +%F).db"`；
- **升级**：`git pull && docker compose up -d --build`（SQLite 字段变更见 migrations 说明）；
- **限流**：Nginx `limit_req` 限制 `/api/auth/*` 防暴力破解；
- **日志**：`docker compose logs -f` 或 `journalctl -u shenqing-store -f`；
- **HTTPS 证书续期**：certbot 自动；确认 `systemctl list-timers | grep certbot`。

## 7. 常见问题

- 桌面端显示「加载失败，使用内置目录」：检查 `/api/catalog.json` 能否直接打开、域名证书是否有效、桌面端设置里地址是否带 `https://`；
- 忘记管理员密码：`ADMIN_EMAIL` 不变时不会重建；可在数据库里把该用户 `role` 改回 `admin` 并用新账号注册后提升；
- 插件下载失败：`download_url` 必须公网可访问（GitHub Release / 对象存储直链），不要填内网地址。
