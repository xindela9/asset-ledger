# Asset Ledger · 固定资产台账管理系统

一个轻量的固定资产台账管理系统，适合中小团队对电脑、外设等 IT 资产以及门禁卡进行登记、领用与盘点。

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![Flask](https://img.shields.io/badge/Flask-3.0%2B-lightgrey) ![SQLite](https://img.shields.io/badge/SQLite-内置于部署说明-informational)

## 功能特性

- **资产管理**：登记资产（所有人 / 部门 / 使用人 / 类型 / 型号 / 数量 / 编号 / 金额 / 状态 / 位置 / 备注），支持筛选、搜索与导出
- **门禁卡管理**：卡号、持卡人、部门、卡类型、发放日期、门禁区域独立台账
- **登录与角色权限**：`admin` 管理员（全权 + 用户管理）、`user` 普通用户（默认只读，可单独开通编辑权限）
- **零依赖部署**：Flask + SQLite 单文件后端，无需额外数据库服务
- **单页前端**：原生 HTML/JS，无前端构建流程，改起来直接

## 快速开始

```bash
git clone https://github.com/xindela9/asset-ledger.git
cd asset-ledger

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python app.py
```

浏览器打开 `http://127.0.0.1:8000` 即可访问。

### 默认账号

首次运行会自动初始化 SQLite 数据库并写入默认账号：

| 用户名 | 密码 | 角色 |
|--------|------|------|
| admin | admin123 | 管理员 |

> 生产环境请登录后立即修改默认密码。

## 生产部署（systemd 示例）

```ini
[Unit]
Description=Asset Ledger
After=network.target

[Service]
WorkingDirectory=/opt/asset-ledger
ExecStart=/opt/asset-ledger/venv/bin/python app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

## 目录结构

```
asset-ledger/
├── app.py           # Flask 后端（资产/门禁卡/用户/登录）
├── index.html       # 管理主界面（单页）
├── login.html       # 登录页
├── particle_bg.js   # 登录页粒子背景
├── static/          # 静态资源
└── requirements.txt # 依赖（flask）
```

## 数据库

运行目录下自动生成 `assets.db`（SQLite），包含三张表：

- `assets`：固定资产台账
- `cards`：门禁卡台账
- `users`：登录用户（密码 scrypt 哈希存储）

## License

MIT