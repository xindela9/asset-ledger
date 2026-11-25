#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
固定资产台账 —— 后端服务（含登录与角色权限）
技术栈：Flask + SQLite
角色：admin（管理员，全权 + 管理用户）、user（普通用户，默认只读，可由管理员单独开编辑权限）
运行后通过 http://服务器IP:8000 访问。
"""
import os
import json
import sqlite3
import secrets
from functools import wraps
from flask import Flask, request, jsonify, send_file, g, session, redirect
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "assets.db")
SEED_PATH = os.path.join(BASE_DIR, "seed.json")
INDEX_PATH = os.path.join(BASE_DIR, "index.html")
LOGIN_PATH = os.path.join(BASE_DIR, "login.html")
SECRET_PATH = os.path.join(BASE_DIR, "secret.key")

FIELDS = ["owner", "dept", "user", "type", "model", "qty",
          "code", "info", "date", "amount", "status", "loc", "notes"]

# 门禁卡字段（独立于资产表）
# code=卡号 name=持卡人 dept=部门 owner=所属 ctype=卡类型
# status=状态 date=发放日期 area=门禁区域 notes=备注
CARD_FIELDS = ["code", "name", "dept", "owner", "ctype",
               "status", "date", "area", "notes"]

DEFAULT_ADMIN = ("admin", "admin123")   # 首次运行创建；请登录后立即改密码

app = Flask(__name__)

# 会话密钥：持久化到文件，重启后登录状态不失效
if os.path.exists(SECRET_PATH):
    app.secret_key = open(SECRET_PATH, "rb").read()
else:
    key = secrets.token_bytes(32)
    with open(SECRET_PATH, "wb") as f:
        f.write(key)
    app.secret_key = key


# ---------- 数据库 ----------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("""
        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT, dept TEXT, user TEXT, type TEXT, model TEXT,
            qty TEXT, code TEXT, info TEXT, date TEXT, amount TEXT,
            status TEXT, loc TEXT, notes TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT, name TEXT, dept TEXT, owner TEXT, ctype TEXT,
            status TEXT, date TEXT, area TEXT, notes TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            pw_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            can_edit INTEGER NOT NULL DEFAULT 0
        )
    """)
    db.commit()
    # 资产初始数据
    if db.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0 and os.path.exists(SEED_PATH):
        with open(SEED_PATH, encoding="utf-8") as f:
            seed = json.load(f)
        seed_into(db, seed)
        db.commit()
        print(f"[init] 已导入初始资产数据 {len(seed)} 条")
    # 默认管理员
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        db.execute("INSERT INTO users (username, pw_hash, role, can_edit) VALUES (?,?,?,?)",
                   (DEFAULT_ADMIN[0], generate_password_hash(DEFAULT_ADMIN[1]), "admin", 1))
        db.commit()
        print(f"[init] 已创建默认管理员：账号 {DEFAULT_ADMIN[0]} / 密码 {DEFAULT_ADMIN[1]}（请尽快修改）")
    db.close()


def seed_into(db, rows):
    cols = ",".join(FIELDS)
    ph = ",".join(["?"] * len(FIELDS))
    for r in rows:
        vals = [str(r.get(k, "") if r.get(k) is not None else "") for k in FIELDS]
        db.execute(f"INSERT INTO assets ({cols}) VALUES ({ph})", vals)


def row_to_dict(row):
    d = {k: row[k] for k in FIELDS}
    d["id"] = row["id"]
    return d


def clean_payload(data):
    out = {}
    for k in FIELDS:
        v = data.get(k, "")
        out[k] = "" if v is None else str(v).strip()
    if not out.get("qty"):
        out["qty"] = "1"
    if not out.get("status"):
        out["status"] = "在使用"
    return out


# 无编码资产的“自然键”：缺少 code 时用这几项判重
# 含义：所属+部门+使用人+类型+型号+设备信息 全一致 → 视为同一台资产
# 若想更严或更松，改这里即可（例如加入 loc 存放区、或去掉 info 设备信息）
NATURAL_KEY = ["owner", "dept", "user", "type", "model", "info"]


def natural_sig(c):
    return "\u0001".join((str(c.get(k, "") or "")).strip() for k in NATURAL_KEY)


# ---------- 门禁卡 ----------
def card_to_dict(row):
    d = {k: row[k] for k in CARD_FIELDS}
    d["id"] = row["id"]
    return d


def clean_card(data):
    out = {}
    for k in CARD_FIELDS:
        v = data.get(k, "")
        out[k] = "" if v is None else str(v).strip()
    if not out.get("status"):
        out["status"] = "在用"
    return out


# 无卡号时的判重依据：持卡人+部门+所属+卡类型 全一致视为同一张卡
CARD_NKEY = ["name", "dept", "owner", "ctype"]


def card_sig(c):
    return "\u0001".join((str(c.get(k, "") or "")).strip() for k in CARD_NKEY)


# ---------- 当前用户与权限装饰器 ----------
def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    row = get_db().execute("SELECT id, username, role, can_edit FROM users WHERE id=?", (uid,)).fetchone()
    return dict(row) if row else None


def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if not current_user():
            return jsonify({"error": "未登录"}), 401
        return f(*a, **k)
    return w


def require_edit(f):
    @wraps(f)
    def w(*a, **k):
        u = current_user()
        if not u:
            return jsonify({"error": "未登录"}), 401
        if u["role"] != "admin" and not u["can_edit"]:
            return jsonify({"error": "无编辑权限"}), 403
        return f(*a, **k)
    return w


def require_admin(f):
    @wraps(f)
    def w(*a, **k):
        u = current_user()
        if not u:
            return jsonify({"error": "未登录"}), 401
        if u["role"] != "admin":
            return jsonify({"error": "需要管理员权限"}), 403
        return f(*a, **k)
    return w


# ---------- 页面 ----------
@app.route("/")
def index():
    if not current_user():
        return redirect("/login")
    return send_file(INDEX_PATH)


@app.route("/login")
def login_page():
    if current_user():
        return redirect("/")
    return send_file(LOGIN_PATH)


# ---------- 认证 ----------
@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    row = get_db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not row or not check_password_hash(row["pw_hash"], password):
        return jsonify({"error": "账号或密码错误"}), 401
    session["uid"] = row["id"]
    return jsonify({"username": row["username"], "role": row["role"], "can_edit": row["can_edit"]})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me", methods=["GET"])
@login_required
def api_me():
    return jsonify(current_user())


@app.route("/api/change-password", methods=["POST"])
@login_required
def change_password():
    data = request.get_json(force=True) or {}
    old = str(data.get("old", ""))
    new = str(data.get("new", "")).strip()
    if len(new) < 4:
        return jsonify({"error": "新密码至少 4 位"}), 400
    u = current_user()
    row = get_db().execute("SELECT pw_hash FROM users WHERE id=?", (u["id"],)).fetchone()
    if not check_password_hash(row["pw_hash"], old):
        return jsonify({"error": "原密码错误"}), 400
    db = get_db()
    db.execute("UPDATE users SET pw_hash=? WHERE id=?", (generate_password_hash(new), u["id"]))
    db.commit()
    return jsonify({"ok": True})


# ---------- 用户管理（仅管理员） ----------
@app.route("/api/users", methods=["GET"])
@require_admin
def list_users():
    rows = get_db().execute("SELECT id, username, role, can_edit FROM users ORDER BY id").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/users", methods=["POST"])
@require_admin
def create_user():
    data = request.get_json(force=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()
    role = "admin" if data.get("role") == "admin" else "user"
    can_edit = 1 if (role == "admin" or data.get("can_edit")) else 0
    if not username or len(password) < 4:
        return jsonify({"error": "用户名不能为空，密码至少 4 位"}), 400
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        return jsonify({"error": "用户名已存在"}), 400
    db.execute("INSERT INTO users (username, pw_hash, role, can_edit) VALUES (?,?,?,?)",
               (username, generate_password_hash(password), role, can_edit))
    db.commit()
    return jsonify({"ok": True}), 201


@app.route("/api/users/<int:uid>", methods=["PUT"])
@require_admin
def update_user(uid):
    data = request.get_json(force=True) or {}
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        return jsonify({"error": "用户不存在"}), 404
    role = data.get("role", row["role"])
    role = "admin" if role == "admin" else "user"
    can_edit = 1 if (role == "admin" or data.get("can_edit")) else 0
    # 不允许取消最后一个管理员
    if row["role"] == "admin" and role != "admin":
        admins = db.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]
        if admins <= 1:
            return jsonify({"error": "至少保留一个管理员"}), 400
    # 改用户名（可选）
    new_name = str(data.get("username", "") or "").strip()
    if new_name and new_name != row["username"]:
        dup = db.execute("SELECT id FROM users WHERE username=? AND id<>?", (new_name, uid)).fetchone()
        if dup:
            return jsonify({"error": "用户名已存在"}), 400
        db.execute("UPDATE users SET username=? WHERE id=?", (new_name, uid))
    db.execute("UPDATE users SET role=?, can_edit=? WHERE id=?", (role, can_edit, uid))
    if data.get("password"):
        pw = str(data["password"]).strip()
        if len(pw) < 4:
            return jsonify({"error": "密码至少 4 位"}), 400
        db.execute("UPDATE users SET pw_hash=? WHERE id=?", (generate_password_hash(pw), uid))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/users/<int:uid>", methods=["DELETE"])
@require_admin
def delete_user(uid):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        return jsonify({"error": "用户不存在"}), 404
    if uid == session.get("uid"):
        return jsonify({"error": "不能删除自己"}), 400
    if row["role"] == "admin":
        admins = db.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]
        if admins <= 1:
            return jsonify({"error": "至少保留一个管理员"}), 400
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    db.commit()
    return jsonify({"ok": True})


# ---------- 资产 API ----------
@app.route("/api/assets", methods=["GET"])
@login_required
def list_assets():
    rows = get_db().execute("SELECT * FROM assets ORDER BY id DESC").fetchall()
    return jsonify([row_to_dict(r) for r in rows])


@app.route("/api/assets", methods=["POST"])
@require_edit
def create_asset():
    data = clean_payload(request.get_json(force=True) or {})
    if not data["type"] and not data["model"]:
        return jsonify({"error": "类型和型号至少填一个"}), 400
    db = get_db()
    cols = ",".join(FIELDS); ph = ",".join(["?"] * len(FIELDS))
    cur = db.execute(f"INSERT INTO assets ({cols}) VALUES ({ph})", [data[k] for k in FIELDS])
    db.commit()
    row = db.execute("SELECT * FROM assets WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(row_to_dict(row)), 201


@app.route("/api/assets/<int:aid>", methods=["PUT"])
@require_edit
def update_asset(aid):
    data = clean_payload(request.get_json(force=True) or {})
    db = get_db()
    if not db.execute("SELECT id FROM assets WHERE id=?", (aid,)).fetchone():
        return jsonify({"error": "记录不存在"}), 404
    sets = ",".join([f"{k}=?" for k in FIELDS])
    db.execute(f"UPDATE assets SET {sets} WHERE id=?", [data[k] for k in FIELDS] + [aid])
    db.commit()
    row = db.execute("SELECT * FROM assets WHERE id=?", (aid,)).fetchone()
    return jsonify(row_to_dict(row))


@app.route("/api/assets/<int:aid>", methods=["DELETE"])
@require_admin
def delete_asset(aid):
    db = get_db()
    db.execute("DELETE FROM assets WHERE id=?", (aid,))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/assets/bulk", methods=["POST"])
@require_edit
def bulk_create():
    """导入 upsert：
       - 有资产编码：编码已存在 → 覆盖更新；不存在 → 新增。
       - 无资产编码：按自然键(所属+部门+使用人+类型+型号+设备信息)判重，
         命中 → 覆盖更新那一条；未命中 → 新增。
       返回 no_code = 本次涉及的无编码行数（仅作提醒，建议尽量补全编码）。
    """
    data = request.get_json(force=True) or []
    if not isinstance(data, list):
        return jsonify({"error": "格式应为数组"}), 400
    db = get_db()
    inserted = updated = no_code = 0
    cols = ",".join(FIELDS); ph = ",".join(["?"] * len(FIELDS))
    sets = ",".join([f"{k}=?" for k in FIELDS])

    # 预建无编码资产的自然键索引：签名 -> id（用于无编码行判重，避免逐行全表扫描）
    nocode_index = {}
    for r in db.execute("SELECT * FROM assets WHERE code IS NULL OR code=''").fetchall():
        sig = natural_sig({k: r[k] for k in FIELDS})
        nocode_index.setdefault(sig, r["id"])

    for item in data:
        c = clean_payload(item)
        if not c["type"] and not c["model"]:
            continue
        code = c["code"].strip()
        if code:
            rows = db.execute("SELECT id FROM assets WHERE code=?", (code,)).fetchall()
            if rows:
                for r in rows:
                    db.execute(f"UPDATE assets SET {sets} WHERE id=?",
                               [c[k] for k in FIELDS] + [r["id"]])
                updated += 1
                continue
            cur = db.execute(f"INSERT INTO assets ({cols}) VALUES ({ph})", [c[k] for k in FIELDS])
            inserted += 1
        else:
            no_code += 1
            sig = natural_sig(c)
            hit = nocode_index.get(sig)
            if hit:
                db.execute(f"UPDATE assets SET {sets} WHERE id=?", [c[k] for k in FIELDS] + [hit])
                updated += 1
            else:
                cur = db.execute(f"INSERT INTO assets ({cols}) VALUES ({ph})", [c[k] for k in FIELDS])
                nocode_index[sig] = cur.lastrowid   # 同一批次内后续相同行也会命中，不重复
                inserted += 1
    db.commit()
    return jsonify({"inserted": inserted, "updated": updated, "no_code": no_code})


def _asset_key(c):
    """一条资产的判重键，与导入 upsert 的规则完全一致。"""
    code = (c.get("code") or "").strip()
    return "C:" + code if code else "N:" + natural_sig(c)


@app.route("/api/assets/sync", methods=["POST"])
@require_admin
def sync_assets():
    """全量同步导入（以表格为准）：
       在普通导入(新增+更新)的基础上，额外删除「表格里已经没有、但系统里还留着」的记录。

       安全设计：
       1. 同步范围 = 表格中出现过的「所属」值集合。表格里没有的所属（如只导易点云时的致鑫）
          绝不会被删除，避免误伤。
       2. dry_run=1 只做预览，返回将新增/更新/删除的条数和待删清单，不改动任何数据。
       3. 真正执行删除前，自动把 assets.db 复制一份备份，万一删错可以还原。
       4. 仅管理员可用。
    """
    payload = request.get_json(force=True) or {}
    rows = payload.get("rows")
    dry_run = bool(payload.get("dry_run"))
    if not isinstance(rows, list):
        return jsonify({"error": "格式应为数组"}), 400

    # 清洗表格数据，算出键集合与同步范围
    cleaned, file_keys, file_owners = [], set(), set()
    for item in rows:
        c = clean_payload(item)
        if not c["type"] and not c["model"]:
            continue
        cleaned.append(c)
        file_keys.add(_asset_key(c))
        file_owners.add(c["owner"].strip())
    if not cleaned:
        return jsonify({"error": "表格里没有识别到有效数据"}), 400

    db = get_db()
    all_rows = db.execute("SELECT * FROM assets").fetchall()
    db_index = {}
    for r in all_rows:
        db_index.setdefault(_asset_key({k: r[k] for k in FIELDS}), []).append(r)

    # 待删除：所属在同步范围内、但表格里已经没有的记录
    to_delete = []
    for r in all_rows:
        if r["owner"] and r["owner"].strip() not in file_owners:
            continue
        if not r["owner"] and "" not in file_owners:
            continue
        if _asset_key({k: r[k] for k in FIELDS}) not in file_keys:
            to_delete.append(r)

    # 预估新增/更新
    will_insert = will_update = 0
    seen = set()
    for c in cleaned:
        k = _asset_key(c)
        if k in db_index or k in seen:
            will_update += 1
        else:
            will_insert += 1
            seen.add(k)

    scoped_total = sum(1 for r in all_rows
                       if (r["owner"] or "").strip() in file_owners)
    samples = [{"owner": r["owner"], "user": r["user"], "type": r["type"],
                "model": r["model"], "code": r["code"]} for r in to_delete[:12]]

    if dry_run:
        return jsonify({"dry_run": True, "inserted": will_insert, "updated": will_update,
                        "deleted": len(to_delete), "scope": sorted(file_owners),
                        "scope_total": scoped_total, "samples": samples})

    # ---- 真正执行 ----
    backup = ""
    if to_delete:
        try:
            import shutil
            from datetime import datetime
            backup = DB_PATH + ".bak." + datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(DB_PATH, backup)
        except Exception as e:
            return jsonify({"error": f"备份失败，已中止同步：{e}"}), 500

    cols = ",".join(FIELDS); ph = ",".join(["?"] * len(FIELDS))
    sets = ",".join([f"{k}=?" for k in FIELDS])
    inserted = updated = 0
    live_index = {k: [r["id"] for r in v] for k, v in db_index.items()}
    for c in cleaned:
        k = _asset_key(c)
        ids = live_index.get(k)
        if ids:
            for i in ids:
                db.execute(f"UPDATE assets SET {sets} WHERE id=?",
                           [c[x] for x in FIELDS] + [i])
            updated += 1
        else:
            cur = db.execute(f"INSERT INTO assets ({cols}) VALUES ({ph})",
                             [c[x] for x in FIELDS])
            live_index[k] = [cur.lastrowid]
            inserted += 1

    for r in to_delete:
        db.execute("DELETE FROM assets WHERE id=?", (r["id"],))
    db.commit()
    return jsonify({"inserted": inserted, "updated": updated, "deleted": len(to_delete),
                    "scope": sorted(file_owners), "backup": os.path.basename(backup) if backup else ""})


@app.route("/api/assets/clear", methods=["POST"])
@require_admin
def clear_assets():
    db = get_db()
    db.execute("DELETE FROM assets")
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/assets/dedup", methods=["POST"])
@require_admin
def dedup_assets():
    """清理历史重复：
       1) 有编码的：同一资产编码只保留 id 最大的一条（最新），其余删除，并建唯一索引。
       2) 无编码的：按自然键(所属+部门+使用人+类型+型号+设备信息)判重，
          同一自然键只保留 id 最大的一条，其余删除。
    """
    db = get_db()
    removed = 0
    # —— 1) 有编码去重 ——
    dups = db.execute("""
        SELECT code FROM assets
        WHERE code IS NOT NULL AND code <> ''
        GROUP BY code HAVING COUNT(*) > 1
    """).fetchall()
    for d in dups:
        keep = db.execute("SELECT MAX(id) FROM assets WHERE code=?", (d["code"],)).fetchone()[0]
        cur = db.execute("DELETE FROM assets WHERE code=? AND id<>?", (d["code"], keep))
        removed += cur.rowcount
    code_groups = len(dups)
    # —— 2) 无编码去重（按自然键，保留最新一条）——
    seen = {}
    nocode_removed = 0
    for r in db.execute("SELECT * FROM assets WHERE code IS NULL OR code='' ORDER BY id").fetchall():
        sig = natural_sig({k: r[k] for k in FIELDS})
        if sig in seen:
            db.execute("DELETE FROM assets WHERE id=?", (seen[sig],))  # 删旧的，留新的
            nocode_removed += 1
        seen[sig] = r["id"]
    removed += nocode_removed
    db.commit()
    # 有编码部分加唯一约束（仅约束非空编码；SQLite 部分索引，允许多条空编码并存）
    indexed = False
    try:
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_assets_code ON assets(code) WHERE code <> ''")
        db.commit()
        indexed = True
    except Exception as e:
        print(f"[dedup] 建唯一索引失败（可能仍有重复未清理）：{e}")
    no_code = db.execute("SELECT COUNT(*) FROM assets WHERE code IS NULL OR code=''").fetchone()[0]
    return jsonify({"removed": removed, "code_removed": removed - nocode_removed,
                    "nocode_removed": nocode_removed, "groups": code_groups,
                    "no_code": no_code, "indexed": indexed})


@app.route("/api/assets/autocode", methods=["POST"])
@require_admin
def autocode_assets():
    """给所有无编码资产生成唯一编码（格式 AUTO-000001）。
       建议先「清理重复编码」去重，再生成编码，最后导出这份带全编码的表作为今后的主表——
       之后每次导入都能按编码精确判重，彻底告别重复。
    """
    db = get_db()
    rows = db.execute("SELECT id FROM assets WHERE code IS NULL OR code='' ORDER BY id").fetchall()
    # 接着已有的 AUTO- 序号往后编，避免撞号
    maxn = 0
    for e in db.execute("SELECT code FROM assets WHERE code LIKE 'AUTO-%'").fetchall():
        try:
            maxn = max(maxn, int(str(e["code"]).split("-")[1]))
        except Exception:
            pass
    n = 0
    for r in rows:
        maxn += 1
        db.execute("UPDATE assets SET code=? WHERE id=?", (f"AUTO-{maxn:06d}", r["id"]))
        n += 1
    db.commit()
    return jsonify({"coded": n})


# ---------- 门禁卡接口 ----------
@app.route("/api/cards", methods=["GET"])
@login_required
def list_cards():
    db = get_db()
    rows = db.execute("SELECT * FROM cards ORDER BY id").fetchall()
    return jsonify([card_to_dict(r) for r in rows])


@app.route("/api/cards", methods=["POST"])
@require_edit
def create_card():
    c = clean_card(request.get_json(force=True) or {})
    if not c["code"] and not c["name"]:
        return jsonify({"error": "至少填写卡号或持卡人"}), 400
    db = get_db()
    cols = ",".join(CARD_FIELDS); ph = ",".join(["?"] * len(CARD_FIELDS))
    cur = db.execute(f"INSERT INTO cards ({cols}) VALUES ({ph})", [c[k] for k in CARD_FIELDS])
    db.commit()
    c["id"] = cur.lastrowid
    return jsonify(c), 201


@app.route("/api/cards/<int:cid>", methods=["PUT"])
@require_edit
def update_card(cid):
    c = clean_card(request.get_json(force=True) or {})
    db = get_db()
    sets = ",".join([f"{k}=?" for k in CARD_FIELDS])
    cur = db.execute(f"UPDATE cards SET {sets} WHERE id=?", [c[k] for k in CARD_FIELDS] + [cid])
    db.commit()
    if cur.rowcount == 0:
        return jsonify({"error": "未找到"}), 404
    c["id"] = cid
    return jsonify(c)


@app.route("/api/cards/<int:cid>", methods=["DELETE"])
@require_admin
def delete_card(cid):
    db = get_db()
    db.execute("DELETE FROM cards WHERE id=?", (cid,))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/cards/bulk", methods=["POST"])
@require_edit
def bulk_cards():
    """门禁卡导入 upsert：
       - 有卡号：卡号已存在 → 覆盖更新；不存在 → 新增。
       - 无卡号：按 持卡人+部门+所属+卡类型 判重，命中则更新，否则新增。
       和资产导入一样，重复导入同一张表不会产生副本。
    """
    data = request.get_json(force=True) or []
    if not isinstance(data, list):
        return jsonify({"error": "格式应为数组"}), 400
    db = get_db()
    inserted = updated = no_code = 0
    cols = ",".join(CARD_FIELDS); ph = ",".join(["?"] * len(CARD_FIELDS))
    sets = ",".join([f"{k}=?" for k in CARD_FIELDS])

    nocode_index = {}
    for r in db.execute("SELECT * FROM cards WHERE code IS NULL OR code=''").fetchall():
        nocode_index.setdefault(card_sig({k: r[k] for k in CARD_FIELDS}), r["id"])

    for item in data:
        c = clean_card(item)
        if not c["code"] and not c["name"]:
            continue
        code = c["code"].strip()
        if code:
            rows = db.execute("SELECT id FROM cards WHERE code=?", (code,)).fetchall()
            if rows:
                for r in rows:
                    db.execute(f"UPDATE cards SET {sets} WHERE id=?",
                               [c[k] for k in CARD_FIELDS] + [r["id"]])
                updated += 1
                continue
            db.execute(f"INSERT INTO cards ({cols}) VALUES ({ph})", [c[k] for k in CARD_FIELDS])
            inserted += 1
        else:
            no_code += 1
            sig = card_sig(c)
            hit = nocode_index.get(sig)
            if hit:
                db.execute(f"UPDATE cards SET {sets} WHERE id=?",
                           [c[k] for k in CARD_FIELDS] + [hit])
                updated += 1
            else:
                cur = db.execute(f"INSERT INTO cards ({cols}) VALUES ({ph})",
                                 [c[k] for k in CARD_FIELDS])
                nocode_index[sig] = cur.lastrowid
                inserted += 1
    db.commit()
    return jsonify({"inserted": inserted, "updated": updated, "no_code": no_code})


@app.route("/api/assets/reset-seed", methods=["POST"])
@require_admin
def reset_seed():
    db = get_db()
    db.execute("DELETE FROM assets")
    if os.path.exists(SEED_PATH):
        with open(SEED_PATH, encoding="utf-8") as f:
            seed = json.load(f)
        seed_into(db, seed)
    db.commit()
    n = db.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
    return jsonify({"count": n})


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000, debug=False)
