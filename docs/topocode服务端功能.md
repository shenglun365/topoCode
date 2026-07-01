# TopoCode 服务端功能

## 概述

独立 Web 服务器（独立仓库），不修改 Electron/Vue/Python 后端代码。

**角色**：用户注册登录 + 免费资源展示 + 下载鉴权跳转 OSS/CDN。

**规模**：5 万用户以内，低负载。

---

## 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| Web 框架 | FastAPI + Jinja2 | 与现有 web_server.py 技术栈一致 |
| 数据库 | MySQL | 本机部署 |
| 前端 | Jinja2 服务端模板 + 轻量 CSS/JS | 非 SPA，简单页无需 Vue |
| Auth | JWT + bcrypt | 密码哈希 + 无状态鉴权 |
| 文件 | OSS/CDN | 预签名 URL，服务器不存文件 |

---

## 项目结构

```
web-server/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI 应用入口
│   ├── config.py            # MySQL / JWT / OSS 配置
│   ├── database.py          # MySQL 连接池 (pymysql + DBUtils)
│   ├── models/
│   │   ├── __init__.py
│   │   ├── user.py          # User CRUD
│   │   └── resource.py      # Resource CRUD
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── auth.py          # 注册 / 登录 API
│   │   ├── resources.py     # 资源列表 / 下载 API
│   │   └── pages.py         # 页面路由
│   └── services/
│       ├── __init__.py
│       ├── auth_service.py  # JWT 签发 + bcrypt 校验
│       └── oss_service.py   # OSS 预签名 URL 生成
├── templates/               # Jinja2 模板
│   ├── base.html            # 基础布局（nav + footer）
│   ├── index.html           # Landing 页
│   ├── login.html           # 登录页
│   ├── register.html        # 注册页
│   ├── resources.html       # 资源中心列表页
│   ├── resource_detail.html # 资源详情页
│   └── download.html        # 下载跳转页
├── static/                  # 静态资源
│   ├── css/
│   ├── js/
│   └── images/
├── requirements.txt
└── deploy/
    ├── nginx.conf
    └── supervisor.conf
```

---

## 数据库 Schema

### users 表

```sql
CREATE TABLE users (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  username    VARCHAR(50) NOT NULL UNIQUE,
  email       VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  is_active   TINYINT(1) DEFAULT 1,
  created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### resources 表

```sql
CREATE TABLE resources (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  title         VARCHAR(200) NOT NULL,
  description   TEXT,
  category      VARCHAR(50) DEFAULT '',
  oss_url       VARCHAR(500) NOT NULL,
  thumbnail_url VARCHAR(500) DEFAULT '',
  is_free       TINYINT(1) DEFAULT 1,
  download_count INT DEFAULT 0,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_category (category),
  INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

资源由运营后台手动录入 INSERT。

---

## API 设计

### Auth

| 方法 | 路径 | 说明 | 请求体 | 响应 |
|---|---|---|---|---|
| POST | `/api/auth/register` | 注册 | `{username, email, password}` | `201 {id, username, email}` |
| POST | `/api/auth/login` | 登录 | `{email, password}` | `{token, user}` |
| GET | `/api/user/profile` | 用户信息 | — | `{id, username, email, created_at}` |

### Resources

| 方法 | 路径 | 说明 | 请求 | 响应 |
|---|---|---|---|---|
| GET | `/api/resources` | 资源列表（分页） | `?page=1&size=12` | `{total, items[]}` |
| GET | `/api/resources/:id` | 资源详情 | — | `{id, title, description, ...}` |
| GET | `/api/resources/:id/download` | 下载（需登录） | `Authorization: Bearer <jwt>` | `302 → OSS 预签名 URL` |

---

## 页面路由

| 路径 | 模板 | 页面说明 |
|---|---|---|
| `/` | `index.html` | Landing 页（产品介绍 + 注册/登录引导） |
| `/login` | `login.html` | 登录表单 |
| `/register` | `register.html` | 注册表单 |
| `/resources` | `resources.html` | 资源中心 Grid 列表 |
| `/resources/:id` | `resource_detail.html` | 资源详情 |
| `/download/:id` | `download.html` | 鉴权 → 跳转 OSS |

---

## JWT 鉴权

```
登录成功 → 签发 JWT
  payload: { user_id, username, exp }
  存储: httpOnly cookie + localStorage（前端备用）

下载鉴权:
  GET /api/resources/:id/download
  → 验证 JWT（cookie 或 Authorization header）
  → 生成 OSS 预签名 URL（有效期 5 分钟）
  → 302 重定向到 OSS URL
```

---

## 部署结构

```
User → Nginx (443 SSL)
           ↓
    Uvicorn (127.0.0.1:8000)
           ↓
    MySQL (127.0.0.1:3306)
```

### nginx.conf 要点

```nginx
server {
    listen 443 ssl;
    server_name topocode.cn;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /static/ {
        alias /var/www/web-server/static/;
        expires 7d;
    }
}
```

---

## 依赖 (requirements.txt)

```
fastapi
uvicorn[standard]
jinja2
python-multipart
pymysql
DBUtils
passlib[bcrypt]
python-jose[cryptography]
python-dotenv
```

---

## 后续扩展

- 管理后台（资源 CRUD，用户管理）
- 付费资源下载（Stripe/PayPal）
- 每日/用户下载限流
- OAuth 第三方登录（微信/GitHub）
- 桌面应用内绑定账号（Electron app 登录态同步）
