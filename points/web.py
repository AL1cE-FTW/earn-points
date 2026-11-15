"""サービス版の Web サーバ。

- /admin/...  スタッフ画面（HTML）。スタッフは1人ずつアカウントでログインする
- /app/       会員アプリ（PWA）。ホーム画面に追加するとアプリのように使える
- /api/...    会員アプリが使う JSON API
- /rules      ポイント制度のご案内（だれでも見られる）

Python 標準ライブラリの HTTP サーバだけで動き、外部サービス・CDN は読み込まない。
インターネットに公開するときは、前に HTTPS のリバースプロキシ（Caddy など）を置く（docs/運用ガイド.md）。
"""

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
import traceback
from datetime import date, timedelta
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from . import rules, service
from . import staff_views as V
from .db import connect
from .service import PointError

STATIC = Path(__file__).parent / "static"
STAFF_SESSION_SECONDS = 10 * 3600          # スタッフは1日の勤務時間ほど
MEMBER_SESSION_SECONDS = 90 * 86400        # 会員アプリは毎回ログインしなくて済むよう長めに
MAX_FAILURES = 5
MAX_FAILURES_PER_IP = 30     # 同じ接続元から、いろいろな会員番号を試すのを防ぐ
LOCK_SECONDS = 15 * 60
MAX_BODY = 100_000

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".webmanifest": "application/manifest+json",
    ".png": "image/png", ".svg": "image/svg+xml", ".json": "application/json",
}
SECURITY_HEADERS = [
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "same-origin"),
    ("Content-Security-Policy",
     "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:;"
     " connect-src 'self'; manifest-src 'self'; worker-src 'self'; frame-ancestors 'none';"
     " base-uri 'none'; form-action 'self'"),
]


class App:
    """HTTP に依存しない形でリクエストを処理する（テストから直接呼び出せる）。"""

    def __init__(self, db_path, today=date.today, admin_password=None, secure_cookies=False):
        self.conn = connect(db_path)
        self.today = today
        self.secure_cookies = secure_cookies
        self.lock = threading.Lock()
        self._failures = {}
        self.secret = service.get_setting(self.conn, "session_secret")
        if not self.secret:
            self.secret = secrets.token_hex(32)
            service.set_setting(self.conn, "session_secret", self.secret)
        # 最初の起動：管理者アカウント admin を作る
        self.initial_admin = None
        if not self.conn.execute("SELECT 1 FROM staff").fetchone():
            pw = admin_password or secrets.token_urlsafe(9)
            service.create_staff(self.conn, "admin", "管理者", pw, "admin", self.today())
            self.initial_admin = ("admin", None if admin_password else pw)

    # --- セッション（署名付きクッキー） -------------------------------------------
    def _sign(self, payload):
        raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
        sig = hmac.new(self.secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
        return f"{raw}.{sig}"

    def _unsign(self, token):
        try:
            raw, sig = token.rsplit(".", 1)
            good = hmac.new(self.secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, good):
                return None
            payload = json.loads(base64.urlsafe_b64decode(raw))
            return payload if payload.get("exp", 0) > time.time() else None
        except (ValueError, json.JSONDecodeError):
            return None

    def _cookie(self, name, payload, seconds):
        value = self._sign(dict(payload, exp=time.time() + seconds))
        secure = " Secure;" if self.secure_cookies else ""
        return ("Set-Cookie", f"{name}={value}; Path=/; HttpOnly; SameSite=Strict;{secure} Max-Age={seconds}")

    @staticmethod
    def _clear(name):
        return ("Set-Cookie", f"{name}=; Path=/; Max-Age=0")

    def _csrf(self, nonce):
        return hmac.new(self.secret.encode(), f"csrf:{nonce}".encode(), hashlib.sha256).hexdigest()[:32]

    # --- ログイン失敗の回数制限 ------------------------------------------------------
    def _locked(self, key, limit=MAX_FAILURES):
        fails, since = self._failures.get(key, (0, 0))
        return fails >= limit and time.time() - since < LOCK_SECONDS

    def _login_blocked(self, key, ctx):
        return self._locked(key) or self._locked("ip:" + ctx["ip"], MAX_FAILURES_PER_IP)

    def _login_failed(self, key, ctx):
        self._fail(key)
        self._fail("ip:" + ctx["ip"])
        if len(self._failures) > 10000:   # 古い記録を捨てて、メモリを使いすぎないようにする
            now = time.time()
            self._failures = {k: v for k, v in self._failures.items() if now - v[1] < LOCK_SECONDS}

    def _fail(self, key):
        fails, since = self._failures.get(key, (0, 0))
        self._failures[key] = (fails + 1 if time.time() - since < LOCK_SECONDS else 1, time.time())

    # --- 応答 -------------------------------------------------------------------
    @staticmethod
    def html(body, status=200, headers=()):
        return status, [("Content-Type", "text/html; charset=utf-8"), ("Cache-Control", "no-store"), *headers], body

    @staticmethod
    def json(data, status=200, headers=()):
        return status, [("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store"), *headers], \
            json.dumps(data, ensure_ascii=False)

    @staticmethod
    def redirect(location, flash=None, headers=()):
        if flash:
            kind, text = flash
            location += f"{'&' if '?' in location else '?'}{kind}={quote(text)}"
        return 303, [("Location", location), *headers], ""

    def static(self, rel):
        path = (STATIC / rel).resolve()
        if STATIC.resolve() not in path.parents or not path.is_file():
            return self.html("ページが見つかりません", 404)
        ctype = CONTENT_TYPES.get(path.suffix, "application/octet-stream")
        return 200, [("Content-Type", ctype), ("Cache-Control", "no-cache")], path.read_bytes()

    # --- 入口 -------------------------------------------------------------------
    def handle(self, method, raw_path, form=None, cookie_header="", headers=None):
        url = urlsplit(raw_path)
        path = url.path
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        jar = cookies.SimpleCookie()
        try:
            jar.load(cookie_header or "")
        except cookies.CookieError:
            pass
        ctx = {"method": method, "path": path, "form": form or {}, "query": query, "jar": jar,
               "headers": {k.lower(): v for k, v in (headers or {}).items()}}
        ctx["ip"] = ctx["headers"].get("x-points-client", "")
        if path == "/":
            return self.redirect("/app/")
        if path == "/app":
            return self.redirect("/app/")
        if path == "/app/":
            return self.static("app/index.html")
        if path.startswith("/app/") or path.startswith("/static/"):
            return self.static(path.lstrip("/").removeprefix("static/"))
        if path == "/rules":
            return self.html(V.rules_page())
        if path.startswith("/api/"):
            return self.api(ctx)
        if path == "/admin" or path.startswith("/admin/"):
            return self.admin(ctx)
        return self.html("ページが見つかりません", 404)

    # --- 会員アプリの API -------------------------------------------------------------
    def _member(self, jar):
        s = self._unsign(jar["member"].value) if "member" in jar else None
        if not s:
            return None
        m = self.conn.execute("SELECT * FROM members WHERE id=?", (s.get("mid"),)).fetchone()
        if m is None or m["status"] != "active" or m["session_gen"] != s.get("gen"):
            return None
        return m

    def api(self, ctx):
        method, path, form = ctx["method"], ctx["path"], ctx["form"]
        if method == "POST" and ctx["headers"].get("x-requested-with") != "fetch":
            # ほかのサイトからの送信を防ぐ（フォーム送信ではこのヘッダーを付けられない）
            return self.json({"error": "不正なリクエストです"}, 403)
        try:
            if path == "/api/login" and method == "POST":
                key = "m:" + str(form.get("member_no", "")).strip().upper()
                if self._login_blocked(key, ctx):
                    return self.json({"error": "ログインの失敗が続いたため、15分間ログインできません"}, 429)
                m = service.authenticate_member(self.conn, str(form.get("member_no", "")), str(form.get("pin", "")))
                if not m:
                    self._login_failed(key, ctx)
                    return self.json({"error": "会員番号または暗証番号が正しくありません"}, 401)
                self._failures.pop(key, None)
                return self.json({"ok": True}, headers=[self._cookie(
                    "member", {"mid": m["id"], "gen": m["session_gen"]}, MEMBER_SESSION_SECONDS)])
            if path == "/api/logout" and method == "POST":
                return self.json({"ok": True}, headers=[self._clear("member")])
            m = self._member(ctx["jar"])
            if m is None:
                return self.json({"error": "ログインしてください", "login": True}, 401, [self._clear("member")])
            today = self.today()
            if path == "/api/me" and method == "GET":
                return self.json(self.member_summary(m, today))
            if path == "/api/history" and method == "GET":
                return self.json(self.member_history(m))
            if path == "/api/tours" and method == "GET":
                return self.json(self.member_tours(m, today))
            if path == "/api/pin" and method == "POST":
                if not service.authenticate_member(self.conn, m["member_no"], str(form.get("current", ""))):
                    return self.json({"error": "現在の暗証番号が正しくありません"}, 400)
                service.change_pin(self.conn, m["member_no"], str(form.get("next", "")))
                m = service.get_member(self.conn, m["member_no"])
                return self.json({"ok": True}, headers=[self._cookie(
                    "member", {"mid": m["id"], "gen": m["session_gen"]}, MEMBER_SESSION_SECONDS)])
            parts = path.split("/")
            if len(parts) == 5 and parts[2] == "invites" and parts[4] == "request" and method == "POST":
                service.request_join(self.conn, _int(parts[3], "招待番号"), m["id"], today)
                return self.json({"ok": True})
            return self.json({"error": "見つかりません"}, 404)
        except PointError as ex:
            return self.json({"error": str(ex)}, 400)

    def _txn(self, r):
        reason = r["reason"]
        if r["tour_name"] and r["kind"] in ("earn", "bonus") and r["tour_name"] not in reason:
            reason += f"／{r['tour_name']}"
        return {"date": r["created_on"], "kind": V.KIND_LABELS.get(r["kind"], r["kind"]), "code": r["kind"],
                "reason": reason, "tour": r["tour_name"] or "", "points": r["points"]}

    def _gain(self, m, t, paid):
        return sum(p for _, p in service.estimate_earn(self.conn, m, t, paid)[1])

    def member_summary(self, m, today):
        rank = service.rank_for(self.conn, m["id"], today)
        sched = [{"date": r["expires_on"], "points": r["points"]}
                 for r in service.expiring_schedule(self.conn, m["id"], today)]
        soon_limit = (today + timedelta(days=90)).isoformat()
        soon = [x for x in sched if x["date"] <= soon_limit]
        nxt = self.conn.execute(
            "SELECT b.*, t.name AS tour_name FROM bookings b JOIN tours t ON t.id=b.tour_id"
            " WHERE b.member_id=? AND b.status='booked' AND t.depart_date >= ?"
            " ORDER BY t.depart_date LIMIT 1", (m["id"], today.isoformat())).fetchone()
        next_tour = None
        if nxt:
            t = service.get_tour(self.conn, nxt["tour_id"])
            next_tour = {"name": t["name"], "depart_date": t["depart_date"], "pay": nxt["price"] - nxt["points_used"],
                         "points_used": nxt["points_used"], "gain": self._gain(m, t, nxt["price"] - nxt["points_used"]),
                         "days": (date.fromisoformat(t["depart_date"]) - today).days, "michi": t["kind"] == "michi"}
        invites = []
        for i in service.my_invites(self.conn, m["id"], today):
            invites.append({"id": i["id"], "tour_name": i["tour_name"], "depart_date": i["depart_date"],
                            "price": i["price"], "bonus": i["bonus_points"],
                            "state": service.invite_state(self.conn, i)})
        return {
            "today": today.isoformat(),
            "member": {"member_no": m["member_no"], "name": m["name"], "joined_on": m["joined_on"]},
            "balance": service.balance(self.conn, m["id"], today),
            "rank": rank,
            "ranks": [{"code": c, "name": n, "need": need, "mult": mult} for c, n, need, mult in rules.RANKS],
            "expiring": sched,
            "soon": {"points": sum(x["points"] for x in soon), "date": soon[0]["date"]} if soon else None,
            "next_tour": next_tour,
            "recent": [self._txn(r) for r in service.history(self.conn, m["id"], 4)],
            "invites": invites,
            "normal_tours": service.normal_tours_in(self.conn, m["id"], today),
            "goal": service.invite_goal(self.conn, m["id"], today),
            "rules": {"yen_per_point": rules.YEN_PER_POINT, "redeem_unit": rules.REDEEM_UNIT,
                      "birthday": rules.BIRTHDAY_BONUS, "referral": rules.REFERRAL_BONUS,
                      "expiry_years": rules.EXPIRY_YEARS},
        }

    def member_history(self, m):
        rows = service.history(self.conn, m["id"], 1000)
        return {"items": [self._txn(r) for r in rows],
                "earned": sum(r["points"] for r in rows if r["points"] > 0),
                "used": -sum(r["points"] for r in rows if r["kind"] == "redeem")}

    def member_tours(self, m, today):
        out = {"upcoming": [], "past": []}
        for b in service.member_bookings(self.conn, m["id"]):
            t = service.get_tour(self.conn, b["tour_id"])
            item = {"name": t["name"], "depart_date": t["depart_date"], "price": b["price"],
                    "points_used": b["points_used"], "status": b["status"],
                    "status_label": V.BOOKING_LABELS[b["status"]], "michi": t["kind"] == "michi"}
            if b["status"] == "booked":
                item["gain"] = self._gain(m, t, b["price"] - b["points_used"])
                out["upcoming"].append(item)
            else:
                item["earned"] = self.conn.execute(
                    "SELECT COALESCE(SUM(points),0) FROM point_txns WHERE booking_id=? AND kind IN ('earn','bonus')",
                    (b["id"],)).fetchone()[0]
                out["past"].append(item)
        out["upcoming"].sort(key=lambda x: x["depart_date"])
        return out

    # --- スタッフ画面 -------------------------------------------------------------------
    def _staff(self, jar):
        s = self._unsign(jar["staff"].value) if "staff" in jar else None
        if not s:
            return None, None
        row = self.conn.execute("SELECT * FROM staff WHERE id=?", (s.get("sid"),)).fetchone()
        if row is None or not row["active"] or row["session_gen"] != s.get("gen"):
            return None, None
        return row, self._csrf(s.get("n", ""))

    def admin(self, ctx):
        method, path, form, q = ctx["method"], ctx["path"].rstrip("/") or "/", ctx["form"], ctx["query"]
        flash = ("ok", q["ok"]) if "ok" in q else ("err", q["err"]) if "err" in q else None
        if path == "/admin/login":
            if method == "POST":
                key = "s:" + str(form.get("login", "")).strip().lower()
                if self._login_blocked(key, ctx):
                    return self.redirect("/admin/login", ("err", "ログインの失敗が続いたため、15分間ログインできません"))
                st = service.authenticate_staff(self.conn, form.get("login", ""), form.get("password", ""))
                if not st:
                    self._login_failed(key, ctx)
                    return self.redirect("/admin/login", ("err", "ログインIDまたはパスワードが正しくありません"))
                self._failures.pop(key, None)
                return self.redirect("/admin", headers=[self._cookie(
                    "staff", {"sid": st["id"], "gen": st["session_gen"], "n": secrets.token_hex(16)}, STAFF_SESSION_SECONDS)])
            return self.html(V.login_page(flash))
        staff, token = self._staff(ctx["jar"])
        if staff is None:
            return self.redirect("/admin/login", headers=[self._clear("staff")])
        if method == "POST" and not hmac.compare_digest(str(form.get("csrf", "")), token):
            return self.html(V.layout("エラー", "<div class='toast err'>画面が古くなっています。もう一度開き直してから操作してください。</div>",
                                      staff, token), 403)
        page = lambda title, body, current="": self.html(V.layout(title, body, staff, token, current, flash))
        try:
            return self._admin_route(method, path, form, q, staff, token, page, ctx)
        except PointError as ex:
            if method == "GET":
                return page("エラー", f"<div class='toast err'>{V.e(ex)}</div>")
            back = form.get("back", "")
            if not back.startswith("/admin"):
                back = path if path in ("/admin/members/new", "/admin/tours", "/admin/staff",
                                        "/admin/settings", "/admin/password") else path.rsplit("/", 1)[0]
            return self.redirect(back, ("err", str(ex)))

    def _admin_route(self, method, path, form, q, staff, token, page, ctx):
        today = self.today()
        op = staff["name"]
        conn = self.conn
        is_admin = staff["role"] == "admin"

        if path == "/admin/logout" and method == "POST":
            return self.redirect("/admin/login", ("ok", "ログアウトしました"), [self._clear("staff")])
        if path == "/admin" and method == "GET":
            return page("ホーム", V.home(conn, today, q.get("q", "").strip(), token), "home")
        if path == "/admin/expire" and method == "POST":
            n = service.expire_points(conn, today)
            return self.redirect("/admin", ("ok", f"失効処理を実行しました（{n:,}pt 失効）"))
        if path == "/admin/password":
            if method == "POST":
                if not service.authenticate_staff(conn, staff["login"], form.get("current", "")):
                    raise PointError("今のパスワードが正しくありません")
                if form.get("new", "") != form.get("confirm", ""):
                    raise PointError("確認用のパスワードが一致しません")
                service.set_staff_password(conn, staff["id"], form.get("new", ""))
                return self.redirect("/admin/login", ("ok", "パスワードを変更しました。新しいパスワードでログインしてください"),
                                     [self._clear("staff")])
            return page("パスワード変更", V.password_page(token))

        # 会員
        if path == "/admin/members/new":
            if method == "POST":
                m = service.register_member(
                    conn, form.get("name", ""), form.get("pin", ""), today, kana=form.get("kana", ""),
                    phone=form.get("phone", ""), email=form.get("email", ""), birthdate=form.get("birthdate") or None,
                    referrer_no=form.get("referrer_no") or None, operator=op)
                return self.redirect(f"/admin/members/{m['member_no']}", ("ok", f"入会登録しました。会員番号は {m['member_no']} です"))
            return page("新規入会", V.member_form(token, "BT00000017"), "new")
        if path.startswith("/admin/members/"):
            parts = path.split("/")[3:]
            m = service.get_member(conn, parts[0])
            base = f"/admin/members/{m['member_no']}"
            action = parts[1] if len(parts) > 1 else ""
            if action == "" and method == "GET":
                return page(m["name"] + " 様", V.member_detail(conn, m, today, token), "home")
            if action == "card" and method == "GET":
                host = ctx["headers"].get("host", "")
                url = f"https://{host}/app/" if host else "/app/"
                return page("会員証の印刷", V.member_card(conn, m, today, url), "home")
            if action == "adjust" and method == "POST":
                pts = _int(form.get("points"), "調整ポイント")
                service.adjust_points(conn, m["member_no"], pts, form.get("reason", ""), today, op)
                return self.redirect(base, ("ok", f"{pts:+,}pt 調整しました"))
            if action == "pin" and method == "POST":
                service.change_pin(conn, m["member_no"], form.get("pin", ""))
                return self.redirect(base, ("ok", "暗証番号を再設定しました"))
            if action == "withdraw" and method == "POST":
                if form.get("confirm") != "yes":
                    raise PointError("確認のチェックを入れてください")
                service.withdraw_member(conn, m["member_no"], today, op)
                return self.redirect(base, ("ok", "退会処理を行いました"))

        # ツアー
        if path == "/admin/tours":
            if method == "POST":
                kind = form.get("kind", "normal")
                bonus_raw = (form.get("bonus_points") or "").strip()
                t = service.create_tour(
                    conn, form.get("code"), form.get("name"), form.get("depart_date", ""),
                    _int(form.get("price"), "代金"), _float(form.get("bonus_multiplier") or "1", "キャンペーン倍率"),
                    _int(bonus_raw, "加算ポイント") if bonus_raw else None, kind=kind,
                    invite_min_tours=_int(form.get("invite_min_tours"), "招待条件") if kind == "michi" else None)
                return self.redirect(f"/admin/tours/{t['id']}", ("ok", "ツアーを登録しました"))
            return page("ツアー", V.tours(conn, token), "tours")
        if path.startswith("/admin/tours/"):
            parts = path.split("/")[3:]
            t = service.get_tour(conn, _int(parts[0], "ツアー番号"))
            base = f"/admin/tours/{t['id']}"
            action = parts[1] if len(parts) > 1 else ""
            if action == "" and method == "GET":
                return page(t["name"], V.tour_detail(conn, t, today, q.get("check", "").strip(), token), "tours")
            if action == "book" and method == "POST":
                service.book_tour(conn, form.get("member_no", ""), t["id"], _int(form.get("points") or "0", "利用ポイント"), today, op)
                return self.redirect(base, ("ok", "予約を登録しました"))
            if action == "complete" and method == "POST":
                absent = [_int(v, "予約番号") for v in form.get("absent_list", [])]
                n = service.complete_tour(conn, t["id"], today, op, absent)
                return self.redirect(base, ("ok", f"催行完了として {n:,}pt を付与しました"))
            if action == "cancel" and method == "POST":
                if form.get("confirm") != "yes":
                    raise PointError("確認のチェックを入れてください")
                service.cancel_tour(conn, t["id"], today, op)
                return self.redirect(base, ("ok", "ツアーを中止し、使ったポイントをお戻ししました"))
            if action == "invite" and method == "POST":
                n = service.send_invites(conn, t["id"], today, op)
                return self.redirect(base, ("ok", f"{n}名に招待を送りました（会員ページに表示されます）"))
            if action == "contact" and method == "POST":
                ch = form.get("channel", "")
                service.mark_contacted(conn, _int(form.get("invite_id"), "招待番号"), ch, today, op)
                return self.redirect(base, ("ok", f"{service.CONTACT_CHANNELS.get(ch, ch)}で案内したことを記録しました"))
        if path.startswith("/admin/bookings/") and path.endswith("/cancel") and method == "POST":
            service.cancel_booking(conn, _int(path.split("/")[3], "予約番号"), today, op)
            back = form.get("back", "")
            return self.redirect(back if back.startswith("/admin") else "/admin", ("ok", "予約を取り消し、使ったポイントをお戻ししました"))

        # 管理者だけ
        if path in ("/admin/staff", "/admin/settings") or path.startswith("/admin/staff/"):
            if not is_admin:
                return page("権限がありません", "<div class='toast err'>この画面は管理者だけが使えます。</div>")
        if path == "/admin/staff":
            if method == "POST":
                s = service.create_staff(conn, form.get("login"), form.get("name"), form.get("password", ""), form.get("role", "staff"), today)
                return self.redirect("/admin/staff", ("ok", f"{s['name']} さんのアカウント（{s['login']}）を作りました"))
            return page("スタッフ管理", V.staff_list(conn, staff, token), "staff")
        if path.startswith("/admin/staff/") and method == "POST":
            parts = path.split("/")[3:]
            sid = _int(parts[0], "スタッフ番号")
            if parts[1:] == ["password"]:
                service.set_staff_password(conn, sid, form.get("password", ""))
                return self.redirect("/admin/staff", ("ok", "パスワードを再設定しました"))
            if parts[1:] == ["active"]:
                if sid == staff["id"]:
                    raise PointError("自分のアカウントは停止できません")
                service.set_staff_active(conn, sid, form.get("active") == "1")
                return self.redirect("/admin/staff", ("ok", "変更しました"))
        if path == "/admin/settings":
            if method == "POST":
                service.update_michi_settings(conn, _int(form.get("michi_min_tours"), "招待条件"), _int(form.get("michi_bonus"), "特典ポイント"))
                return self.redirect("/admin/settings", ("ok", "保存しました"))
            return page("設定", V.settings_page(conn, token), "settings")

        return page("見つかりません", "<div class='toast err'>ページが見つかりません。</div>")


def _int(value, label):
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        raise PointError(f"{label}は整数で入力してください")


def _float(value, label):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        raise PointError(f"{label}は数値で入力してください")


def parse_form(body):
    """フォームを辞書にする。同じ名前が複数ある項目（不参加のチェックなど）は name_list にも入れる。"""
    pairs = parse_qs(body, keep_blank_values=True)
    form = {k: v[0] for k, v in pairs.items()}
    for k, v in pairs.items():
        form[k + "_list"] = v
    return form


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "points"
        sys_version = ""

        def _run(self, method):
            form = {}
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    self.send_error(413)
                    return
                body = self.rfile.read(length).decode("utf-8", "replace")
                if (self.headers.get("Content-Type") or "").startswith("application/json"):
                    try:
                        form = json.loads(body or "{}")
                    except json.JSONDecodeError:
                        form = {}
                    if not isinstance(form, dict):
                        form = {}
                else:
                    form = parse_form(body)
            hdrs = {k: v for k, v in self.headers.items() if k.lower() != "x-points-client"}
            # 接続元。HTTPS のリバースプロキシの後ろでは、プロキシが最後に付け足した X-Forwarded-For を使う
            fwd = self.headers.get("X-Forwarded-For", "")
            hdrs["X-Points-Client"] = fwd.split(",")[-1].strip() if app.secure_cookies and fwd else self.client_address[0]
            try:
                with app.lock:
                    status, headers, body = app.handle("GET" if method == "HEAD" else method, self.path, form,
                                                       self.headers.get("Cookie", ""), hdrs)
            except Exception:
                traceback.print_exc()
                status, headers, body = app.html("エラーが発生しました。もう一度お試しください。", 500)
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(status)
            for k, v in [*headers, *SECURITY_HEADERS]:
                self.send_header(k, v)
            if app.secure_cookies:
                self.send_header("Strict-Transport-Security", "max-age=31536000")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if method != "HEAD":
                self.wfile.write(data)

        def do_GET(self):
            self._run("GET")

        def do_HEAD(self):
            self._run("HEAD")

        def do_POST(self):
            self._run("POST")

    return Handler


def serve(db_path, host="127.0.0.1", port=8000, admin_password=None, secure_cookies=False):
    app = App(db_path, admin_password=admin_password, secure_cookies=secure_cookies)
    if app.initial_admin:
        login, pw = app.initial_admin
        print(f"[初回起動] 管理者アカウントを作りました。ログインID: {login}")
        if pw:
            print(f"  パスワード: {pw}  （ログイン後に「パスワード変更」で変えてください）")
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    print(f"会員アプリ:   http://{host}:{port}/app/")
    print(f"スタッフ画面: http://{host}:{port}/admin")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
