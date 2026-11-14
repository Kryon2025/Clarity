# 深清商店服务端（FastAPI + SQLite）

深清（Clarity）主题 / 插件商店的可部署后端：账号登录、角色权限、开发者提交、
管理员审核、评论、公开商店页面，桌面端兼容的 /api/catalog.json，账户云同步
（/api/sync，跨设备同步专注数据），以及 CW2 风格的 **GitHub 发布源自动同步**
（开发者必填仓库 / 发布页地址，后台从 GitHub Releases 同步版本与下载地址）
和 **开发者发布 Token**（cwpt_...，给 CI 持续发布用）。

- 技术栈：Python 3.13 + FastAPI + uvicorn + SQLite（stdlib sqlite3）
- 认证：JWT（HS256，stdlib hmac/base64）+ PBKDF2-SHA256（stdlib hashlib）
- 单进程同时提供接口与静态前端；CORS 默认允许所有来源
- 数据文件只有一个 SQLite（默认 server/store.db），备份就是复制文件

## 目录结构

~~~
server/
├── main.py               FastAPI 应用（路由 / 依赖 / 静态挂载 / 初始管理员）
├── config.py             环境变量与 .env 解析
├── db.py                 SQLite 连接、建表、行序列化
├── auth.py               密码哈希与 JWT（纯 stdlib）
├── mailer.py             邮箱验证码发信（smtplib，未配 SMTP 时走开发模式）
├── ratelimit.py          验证码发送 / 云同步写入限流（内存滑动窗口）
├── services/
│   └── github_sync.py    GitHub 发布源：地址解析 + Releases API + 版本/资产解析
├── seed.py               演示数据（3 主题 + 2 插件 + 示例账号）
├── static/               前端静态文件（index.html / app.js / style.css，由前端提供）
├── tests/                单元测试（fastapi.testclient.TestClient）
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
~~~

## 快速开始（本地）

需要 Python 3.13（3.10+ 也可运行）。

~~~bash
cd server
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # 修改 SECRET_KEY / ADMIN_EMAIL / ADMIN_PASSWORD

# 回到仓库根目录启动（推荐）：
cd ..
uvicorn server.main:app --reload --port 8000
# 或者 cd server && uvicorn main:app --reload --port 8000
~~~

打开 http://127.0.0.1:8000/ 是前端页面，接口在 http://127.0.0.1:8000/api/*，
交互式接口文档在 http://127.0.0.1:8000/docs。

自检：

~~~bash
curl http://127.0.0.1:8000/api/store/items     # 应返回 []
curl http://127.0.0.1:8000/api/health          # {"status":"ok",...}
~~~

## 环境变量

| 变量 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- |
| SECRET_KEY | 生产必填 | dev-insecure-change-me | JWT 签名密钥，务必改成随机长串 |
| ADMIN_EMAIL | 建议填 | 空 | 初始管理员邮箱；首次启动不存在则创建 |
| ADMIN_PASSWORD | 建议填 | 空 | 初始管理员密码（至少 6 位）；已存在账号不会改密码 |
| DATABASE_PATH | 否 | server/store.db | SQLite 路径；相对路径相对 server/ |
| TOKEN_TTL_SECONDS | 否 | 604800 | 登录 token 有效期（7 天） |
| CORS_ORIGINS | 否 | * | 逗号分隔的来源列表 |
| PUBLIC_BASE_URL | 否 | 空 | 反代后固定 catalog 里的绝对下载地址，如 https://store.example.com |
| APP_VERSION | 否 | 0.19.0 | catalog.json 顶层 version |
| STATIC_DIR | 否 | server/static | 前端静态目录 |
| BOOTSTRAP_ADMIN | 否 | 1 | 设为 0 可关闭启动时创建管理员 |
| SMTP_HOST | 否 | 空 | SMTP 服务器；为空即开发模式（不发信，验证码写日志 + 响应带 dev_code） |
| SMTP_PORT | 否 | 587 | SMTP 端口（587 配 STARTTLS，465 配 SMTP_SSL=1） |
| SMTP_USER | 否 | 空 | SMTP 登录账号 |
| SMTP_PASSWORD | 否 | 空 | SMTP 密码 / 授权码 |
| SMTP_FROM | 否 | SMTP_USER | 发件地址（显示名为「深清商店」） |
| SMTP_TLS | 否 | 1 | 是否 STARTTLS（587 端口一般开） |
| SMTP_SSL | 否 | 0 | 是否隐式 SSL（465 端口开，开了就不再 STARTTLS） |
| MAIL_DEV_MODE | 否 | 0 | 强制开发模式：不发信、响应里带 dev_code。**生产严禁开启** |
| EMAIL_CODE_TTL_SECONDS | 否 | 600 | 验证码有效期（秒） |
| EMAIL_CODE_MAX_ATTEMPTS | 否 | 5 | 单个验证码最多尝试次数，超限返回 429 |
| GITHUB_TOKEN | 否 | 空 | GitHub API Token：匿名 60 次/小时，配置后 5000 次/小时（只读公开仓库即可，无需任何权限） |
| GITHUB_TIMEOUT_SECONDS | 否 | 6 | 单次 GitHub API 请求超时（秒） |
| GITHUB_SYNC_INTERVAL_SECONDS | 否 | 21600 | 后台同步周期（秒），默认 6 小时 |
| GITHUB_SYNC_ENABLED | 否 | 1 | 设为 0 可关闭后台同步线程（仍可手动 POST /api/admin/sync）；测试环境建议关 |

配置也可以写在 server/.env（KEY=VALUE，# 注释），环境变量优先于 .env。

## 初始管理员

启动时读取 ADMIN_EMAIL / ADMIN_PASSWORD：

- 该邮箱不存在：自动创建 role=admin 的账号；
- 已存在：不改密码也不自动提权（日志会提示）。

创建后可登录网页商店，进入管理后台审核条目、调整用户角色。若忘记密码，
直接改数据库或删掉该用户后用新密码重启即可。

## 邮箱验证码（OTP）

注册、验证码登录、找回密码共用一套邮箱验证码：

~~~text
POST /api/auth/send-code      {email, purpose}        # purpose = register | login | reset
   200 -> {"ok": true, "ttl_seconds": 600}          # 开发模式额外带 "dev_code"
POST /api/auth/register       {email, password, name, code}    # code 为 purpose=register 的验证码
POST /api/auth/login-code     {email, code}                     # purpose=login
POST /api/auth/reset-password {email, code, new_password}       # purpose=reset -> {"ok": true}
~~~

- 验证码 6 位数字、10 分钟有效、**用后即废**；库里只存 HMAC-SHA256 摘要 + 独立盐，不存明文；
- 同一邮箱同一用途只保留最新一条（重新发码会作废旧码）；
- 验证码错误 / 不存在 / 已过期 / 已使用统一 `400 {"detail": "验证码错误或已过期"}`，不区分具体原因；
  单个验证码错 5 次后继续请求返回 `429 {"detail": "验证码尝试次数过多，请重新获取"}`；
- 防枚举：`purpose=login/reset` 时邮箱不存在也返回成功（只写日志，不发信、不建档）；
  `purpose=register` 时邮箱已注册返回 `400`；验证码登录/重置接口对不存在的账号同样返回统一提示。

发送限流（内存计数，进程重启即重置；多副本或公网部署请再叠加 Nginx limit_req）：

| 维度 | 限制 |
| --- | --- |
| 同一邮箱 | 60 秒 1 次、1 小时 5 次、1 天 10 次 |
| 同一 IP | 10 分钟 20 次（优先取 X-Forwarded-For 第一段，否则取连接来源） |

命中限流返回 `429`，`detail` 是可读中文，并带 `Retry-After` 响应头（秒）。

### 开发模式与正式部署

- **未配置 SMTP_HOST，或 `MAIL_DEV_MODE=1`**：不连邮件服务器，把验证码写进日志
  （logger `shenqing.mailer`，WARNING 级），并在 `send-code` 响应里返回 `dev_code`；
  本地联调直接用 dev_code 完成注册 / 登录 / 重置。
- 配好 SMTP（`SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / SMTP_FROM`）且未开
  `MAIL_DEV_MODE` 时**不会**返回 `dev_code`；发信失败返回 `503` + 可读中文提示
  （不会 500），同时丢弃本次验证码记录，避免留下永远收不到的码。
- SMTP 连接/读写超时固定 10 秒，避免请求线程被拖住。

示例（QQ 邮箱，密码填 SMTP 授权码）：

~~~bash
SMTP_HOST=smtp.qq.com SMTP_PORT=587 SMTP_USER=you@qq.com \
SMTP_PASSWORD=授权码 SMTP_FROM=you@qq.com SMTP_TLS=1 uvicorn server.main:app
~~~

## 演示数据（可选）

~~~bash
python -m server.seed          # 仓库根目录
# 或 cd server && python seed.py
~~~

会幂等写入：

- 3 个已过审主题：极光 / 樱雾 / 苔原
- 2 个已过审插件：专注统计 / 白噪音
- 示例账号：dev@example.com / dev123456（开发者）、user@example.com / user123456、aki@example.com / aki123456
- 若干已过审评论 + 1 条待审核评论（用于演示评论审核）

未配置 ADMIN_EMAIL 时 seed 不会创建管理员，但仍会导入其它数据。

## 角色与流程

- user：注册默认角色，可浏览、评论；
- developer：管理员在「用户管理」提升后，可在开发者中心提交主题/插件；
- admin：审核提交、审核评论、调整用户角色。

提交流程：开发者提交 → status=pending（只有作者和管理员可见）→ 管理员通过
（进入公开商店与 catalog.json）或拒绝（必须写原因，开发者能看到）。
只有 pending 条目允许作者继续修改。

插件提交建议在请求体里带 id，且与插件包 plugin.json 的 id 完全一致
（例如 com.example.hello）；否则自动生成的 plugin-xxxx 会导致桌面端安装时
清单 id 校验失败。主题 id 可自行指定（如 theme-aurora）或省略自动生成。

## 接口一览

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| POST | /api/auth/send-code | 公开 | 发送邮箱验证码 {email, purpose: register/login/reset} → {ok, ttl_seconds, dev_code?} |
| POST | /api/auth/register | 公开 | 注册（需邮箱验证码 code），返回 {token,user} |
| POST | /api/auth/login | 公开 | 密码登录，返回 {token,user} |
| POST | /api/auth/login-code | 公开 | 验证码登录 {email, code} → {token,user} |
| POST | /api/auth/reset-password | 公开 | 用验证码重置密码 {email, code, new_password} → {ok: true} |
| GET | /api/auth/me | 登录 | 当前用户 |
| GET | /api/store/items?kind=&q=&sort= | 公开 | 已过审列表；sort=rating/downloads/newest/oldest/name |
| GET | /api/store/items/{id} | 公开 | 详情；pending/rejected 仅作者与管理员可见 |
| GET | /api/store/items/{id}/comments | 公开 | 已过审评论 |
| POST | /api/store/items/{id}/comments | 登录 | 发评论（status=pending） |
| POST | /api/dev/items | developer/admin 或发布 Token | 提交主题/插件（github_url 必填） |
| GET | /api/dev/items | developer/admin | 自己的全部提交与状态 |
| PUT | /api/dev/items/{id} | developer/admin 或发布 Token | 修改自己的 pending 条目 |
| POST | /api/dev/tokens | developer/admin | 创建发布 Token {name, scope?, expires_days?} → 含一次性明文 token |
| GET | /api/dev/tokens | developer/admin | 我的 Token 列表（prefix/status/created/last_used/expires，无明文） |
| POST | /api/dev/tokens/{id}/revoke | developer/admin | 撤销自己的 Token（幂等） |
| POST | /api/admin/sync | admin | 立即同步所有已过审条目的 GitHub 版本（同步执行，返回统计） |
| GET | /api/admin/sync/status | admin | 上次同步时间 / 成功数 / 失败数 / 错误明细 |
| GET | /api/admin/submissions?status=pending | admin | 审核队列（status=all 看全部） |
| POST | /api/admin/review | admin | {item_id, action: approve/reject, reason} |
| GET | /api/admin/users | admin | 用户列表 |
| POST | /api/admin/users/{id}/role | admin | {role: user/developer/admin}，不能改自己 |
| GET | /api/admin/comments?status=pending | admin | 评论审核队列（扩展接口） |
| POST | /api/admin/comments/{id}/review | admin | {action: approve/reject}（扩展接口） |
| GET | /api/sync | 登录 | 读取本账号云同步快照 → {revision, updated_at, payload, device_name} |
| PUT | /api/sync | 登录 | 写入快照（乐观并发）{payload, revision, device} → {revision, updated_at}；版本冲突 409 |
| DELETE | /api/sync | 登录 | 清空本账号快照 → {ok: true, revision: 0} |
| GET | /api/catalog.json | 公开 | 桌面端目录（仅 approved，download_url 绝对地址） |
| GET | /api/health | 公开 | 健康检查 |

约定：成功统一 200；错误统一 {"detail": "中文提示"}（400/401/403/404/409/413/422/429/503）。
列表接口直接返回 JSON 数组，单个资源返回对象。

鉴权请求头：Authorization: Bearer <token>。

### catalog.json

~~~json
{
  "version": "0.19.0",
  "updated_at": "2026-11-14T12:00:00Z",
  "items": [
    {
      "id": "theme-aurora",
      "kind": "theme",
      "name": "极光",
      "author": "示例开发者",
      "summary": "……",
      "description": "……",
      "version": "1.0.0",
      "rating": 4.7,
      "downloads": 12840,
      "tags": ["深色", "青绿"],
      "screenshots": [],
      "download_url": "",
      "github_url": "https://github.com/example/aurora-theme",
      "last_sync_at": "2026-11-14T12:00:00Z",
      "palette": {
        "bgTop": "#0A1F2E",
        "bgMid": "#06202C",
        "bgBottom": "#04121A",
        "accent": "#35E0C8",
        "cardBg": "#0D2634",
        "textPrimary": "#EAF8FC"
      },
      "published_at": "2026-11-14"
    }
  ]
}
~~~

桌面端设置里的 store_catalog_url 填 https://你的域名/api/catalog.json 即可。
download_url 若在数据库里是站内相对路径（以 / 开头），会拼成绝对地址。
v0.26 起目录条目额外带 github_url（发布源）与 last_sync_at（最近一次同步时间），
桌面端可以忽略这些字段；商店列表 / 详情接口同样返回它们，以及 last_sync_error。

## 账户云同步（跨设备同步专注数据）

登录用户每人一份「专注数据快照」，用于多设备同步；读接口不限流，写接口限流。
payload 由客户端自己序列化为 JSON（服务端只保存、不解析结构，端到端加密也可以
由客户端加密后再放进 payload）。

### 表结构

~~~sql
CREATE TABLE sync_data (
    user_id      INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    revision     INTEGER NOT NULL DEFAULT 0,
    payload      TEXT    NOT NULL DEFAULT '',
    payload_hash TEXT    NOT NULL DEFAULT '',
    updated_at   INTEGER NOT NULL DEFAULT 0,
    device_name  TEXT    NOT NULL DEFAULT ''
);
~~~

- 每个账号最多一条记录（user_id 既是主键也是外键）；账号删除时级联清空；
- payload 存原始 JSON 文本（不建索引、不解析），payload_hash 是它的
  sha256 十六进制摘要（排查/校验用）；
- updated_at 为 Unix 时间戳（秒）；device_name 是最后一次写入的设备名。

### 接口语义

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/sync | 无数据时返回 {"revision": 0, "updated_at": 0, "payload": null, "device_name": ""}；有数据时返回最新快照 |
| PUT | /api/sync | 请求体 {payload: JSON 对象, revision: 当前版本, device: 设备名}；成功 revision+1，返回 {revision, updated_at} |
| DELETE | /api/sync | 删除本人快照，返回 {ok: true, revision: 0}（只影响本人） |

- 乐观并发：revision 必须等于服务端当前版本（无数据为 0）；不匹配返回
  **409**，响应体 {"detail": "...", "revision": <最新版本>}，数据不变；
- payload 必须是 **JSON 对象**，序列化后 ≤ **5MB**（超限 413，非对象 400），
  失败的写入不会推进 revision；
- 写限流（PUT / DELETE 共享）：每用户 **30 秒最多 10 次**，超出返回 429 并带
  Retry-After；纯内存滑动窗口，进程重启即重置，多副本请叠加 Nginx limit_req；
- device 最长 64 个字符（可省略），服务端记录为「最后写入设备」。

~~~bash
# 首次上传
curl -X PUT http://127.0.0.1:8000/api/sync \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"payload":{"sessions":[],"settings":{}},"revision":0,"device":"我的笔记本"}'
# → {"revision": 1, "updated_at": 1763000000}

# 另一台设备想用旧版本覆盖 → 409
# → {"detail": "revision 不匹配：服务端当前版本为 1，请先拉取最新数据", "revision": 1}
~~~

## GitHub 发布源与发布 Token（v0.26）

参考 CW2 插件广场的做法：开发者发布时必须填 **GitHub 仓库 / 发布页地址**，
商店后台从 GitHub Releases 自动同步版本号与下载地址；给 CI 持续发布用的
**发布 Token**（cwpt_...）则可以像 JWT 一样调用提交 / 更新接口。

### 条目字段

| 列 | 默认 | 说明 |
| --- | --- | --- |
| github_url | ''（必填） | 只接受 http(s)://github.com/&lt;owner&gt;/&lt;repo&gt; 与 /releases 页面，统一归一化成 https |
| repo_branch | main | 发布源分支，允许 release/1.0 这种写法 |
| api_version | 空 | 发布源声明的 API 版本（可选，≤32 字符） |
| readme_path | README.md | 发布源里 README 的相对路径 |
| icon_path | icon.png | 发布源里图标的相对路径 |
| last_sync_at | 空 | 最近一次成功同步的时间（ISO8601 UTC） |
| last_sync_error | 空 | 最近一次同步失败的原因，成功时清空 |

提交（POST）时 github_url 为空或不是 GitHub 地址 → 400
「请填写 GitHub 仓库或发布页地址」；更新（PUT）时不传表示保持原值，
原值为空时同样要求补填。旧库由 init_db 幂等补列，历史条目 github_url 为空，
前端据此不展示 GitHub 链接。

### 同步规则

- 用的是 GitHub API `repos/{owner}/{repo}/releases/latest`，单次超时 6 秒；
  配置 GITHUB_TOKEN 可把匿名 60 次/小时 的限额提高到 5000 次/小时；
- 版本 = release 的 tag_name（去掉 v 前缀，v1.2.3 → 1.2.3）；
- 下载地址 = 资产名匹配 Setup / Portable 的（优先 Setup），否则第一个资产，
  再退化成 release 页面地址；
- 同步成功只改 version / download_url / last_sync_at / updated_at，并清空
  last_sync_error；开发者留空的版本（含 0.0.0）在首次同步后即变成真实版本；
- 同步失败只写 last_sync_error：版本、下载地址、审核状态、公开可见性都不变；
- 后台线程每 GITHUB_SYNC_INTERVAL_SECONDS（默认 6 小时）同步所有已过审且填了
  github_url 的条目；管理员也可以 `POST /api/admin/sync` 立即同步（同步执行，
  返回 {total, success, failed, errors}），`GET /api/admin/sync/status` 看上次
  同步时间 / 成功数 / 失败数 / 错误明细。

~~~bash
# 管理员立即同步（Bearer 管理员 JWT）
curl -X POST -H "Authorization: Bearer $ADMIN_JWT" http://127.0.0.1:8000/api/admin/sync

# 同步状态
curl -H "Authorization: Bearer $ADMIN_JWT" http://127.0.0.1:8000/api/admin/sync/status
# → {"running": false, "last_run_at": "2026-11-14T12:00:00Z", "total": 3,
#    "success": 2, "failed": 1, "errors": [{"item_id": "...", "name": "...", "error": "..."}]}
~~~

### 发布 Token

开发者在「发布 Token」页面创建（名称 + 有效期，0 天表示永久）。响应里的明文
形如 `cwpt_3Qn...`，**只返回这一次**；库里只存 sha256 摘要和列表用的前缀
（cwpt_ + 8 位），因此忘记只能重新创建。

~~~bash
# 创建（返回一次性明文 token 字段）
curl -X POST -H "Authorization: Bearer $DEV_JWT" -H "Content-Type: application/json" \
  -d '{"name": "GitHub Actions 发布", "expires_days": 90}' \
  http://127.0.0.1:8000/api/dev/tokens

# 用 Token 提交条目（与登录 JWT 二选一）
curl -X POST -H "Authorization: Bearer cwpt_xxx" -H "Content-Type: application/json" \
  -d '{"kind": "plugin", "name": "示例插件", "github_url": "https://github.com/me/plugin"}' \
  http://127.0.0.1:8000/api/dev/items

# 撤销
curl -X POST -H "Authorization: Bearer $DEV_JWT" http://127.0.0.1:8000/api/dev/tokens/3/revoke
~~~

校验顺序：存在 → 未撤销 → 未过期；通过后刷新 last_used_at。Token 只对
`POST/PUT /api/dev/items` 生效（不能代替登录访问其它接口），且账号必须仍是
developer / admin。每个账号最多保留 20 个 Token（含已撤销）。

## 前端静态页面

- 目录固定 server/static（index.html / app.js / style.css），由同一个服务提供；
- /api/* 优先，未知且不像文件的路径回退 index.html（支持单页路由）；
- 目录不存在会自动创建；还没有 index.html 时首页显示接口占位页；
- 修改静态文件无需重启（StaticFiles 每次请求读取磁盘）。

## 运行测试

~~~bash
# 仓库根目录
python -m unittest discover -s server/tests

# 或指定文件
python -m unittest server.tests.test_store_api -v
python -m unittest server.tests.test_sync -v
python -m unittest server.tests.test_github_market -v
~~~

覆盖：注册/登录/鉴权、角色权限、待审不可见、审核通过后可见、拒绝原因、
评论 pending 与评分、catalog 结构、管理员调整角色、排序筛选、输入校验、静态回退，
GitHub 发布源（地址必填与格式校验、发布源附加字段、版本/下载地址同步（mock
GitHub API，不联网）、Setup/Portable 资产优先、同步失败只写错误、同步统计与
管理员权限、商店/catalog 的 github_url 与 last_sync_at、新列迁移幂等），
发布 Token（一次性明文、列表不含明文、撤销幂等与越权 404、过期/撤销后 401、
last_used_at 刷新、用 Token 提交与更新、数量与有效期上限），
以及邮箱验证码（建档只存摘要、dev_code 开发模式、注册需 code、错误/过期/用后即废/
尝试超限、邮箱/IP 限流、验证码登录、找回密码后旧密码失效、SMTP 失败返回 503），
以及账户云同步（未登录 401、空快照 revision=0、首次写入 revision=1、重复写入递增、
旧/超前 revision 409 且回传最新版本、payload 非对象 400 与超 5MB 413、
DELETE 后归零、双账号互不可见、每用户 30 秒 10 次写限流与窗口恢复）。

测试全部用临时 SQLite + TestClient，并把发送限流与云同步写限流的时钟注入成
可控假时钟，所以限流用例（60 秒 / 1 小时 / 1 天 / 30 秒）不需要真的等待。

## Docker 部署

~~~bash
cd server
cp .env.example .env        # 修改 SECRET_KEY / ADMIN_PASSWORD
docker compose up -d --build
curl http://127.0.0.1:8000/api/store/items
~~~

- 数据库落在命名卷 store-data（容器内 /data/store.db），升级镜像不丢数据；
- compose 默认只监听 127.0.0.1:8000，公网请用 Nginx 反代 + HTTPS；
- 也可以 docker build -t shenqing-store . && docker run ... 单容器运行。

## 生产部署要点

更完整的云服务器 + Nginx + HTTPS + systemd 步骤见仓库
docs/store-server-deploy.md。关键点：

- 端口：容器/uvicorn 监听 8000，只在内网/本机暴露，公网通过 80/443；
- 反代时透传 Host / X-Forwarded-Proto，uvicorn 用 --proxy-headers；
  若 catalog 里的绝对地址仍不对，设置 PUBLIC_BASE_URL；
- 备份：sqlite3 /data/store.db ".backup /backup/store-$(date +%F).db"
  或停服复制 store.db（WAL 模式建议用 .backup）；
- 限流：Nginx 对 /api/auth/* 限速，防暴力破解（应用内另有验证码发送限流，
  依赖 X-Forwarded-For，反代请透传真实 IP）；
- 邮件：生产必须配置 SMTP_* 且保持 MAIL_DEV_MODE=0，否则验证码只写日志、接口返回 dev_code；
- 升级：git pull && docker compose up -d --build（表结构 IF NOT EXISTS，无需迁移）。

## 常见问题

- 桌面端显示「加载失败，使用内置目录」：确认 /api/catalog.json 可直接访问、
  HTTPS 证书有效、桌面端设置里地址带 https:// 且以 /api/catalog.json 结尾；
- 401：token 过期（默认 7 天）或 SECRET_KEY 改过导致旧 token 全部失效，重新登录；
- 403：当前角色不够（先让管理员把账号提升为 developer）；
- 409：邮箱已注册 / 条目 id 重复；
- 429：验证码发送太频繁或尝试次数过多（看 detail 与 Retry-After）；
- 503：验证码邮件发送失败（检查 SMTP_HOST/PORT/USER/PASSWORD、授权码是否过期、
  服务器是否允许 587 端口发信）；本地开发没配 SMTP 时会自动用 dev_code，不会走到这里；
- 插件安装失败：download_url 必须公网可访问（GitHub Release、对象存储直链），
  且条目 id 要与 plugin.json 的 id 一致；
- 忘记管理员密码：删掉该用户后用新的 ADMIN_PASSWORD 重启，或直接改库里的
  password_hash（用 server.auth.hash_password 生成）。
