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
