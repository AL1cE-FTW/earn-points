"""スタッフ用管理画面と会員用マイページ。

Python 標準ライブラリの HTTP サーバのみで動作し、外部サービス・CDN は一切読み込まない。
"""

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from datetime import date
from html import escape
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlsplit

from . import rules, service
from .db import connect
from .service import PointError

SESSION_SECONDS = 8 * 3600
MAX_PIN_FAILURES = 5
LOCK_SECONDS = 15 * 60

KIND_LABELS = {
    "earn": "ツアー参加", "bonus": "特典", "redeem": "利用", "restore": "返還",
    "expire": "失効", "adjust": "調整", "forfeit": "退会失効",
}
BOOKING_LABELS = {
    "booked": "参加予定", "completed": "参加済", "no_show": "不参加", "cancelled": "取消",
}
TOUR_LABELS = {"scheduled": "催行予定", "completed": "催行完了", "cancelled": "中止"}

CSS = """
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,"Hiragino Sans","Noto Sans JP",sans-serif;
 background:#f4f6f8;color:#1d2733;line-height:1.6}
header{background:#14532d;color:#fff;padding:.7rem 1rem;display:flex;gap:1rem;align-items:center;flex-wrap:wrap}
header a{color:#fff;text-decoration:none;font-weight:600}
header .brand{font-size:1.1rem;margin-right:auto}
main{max-width:960px;margin:0 auto;padding:1rem}
.card{background:#fff;border-radius:10px;padding:1rem 1.2rem;margin-bottom:1rem;box-shadow:0 1px 3px rgba(0,0,0,.08)}
h1{font-size:1.4rem;margin:.2rem 0 1rem}h2{font-size:1.1rem;margin:.2rem 0 .8rem}
table{width:100%;border-collapse:collapse;font-size:.92rem}
th,td{padding:.45rem .5rem;border-bottom:1px solid #e3e8ee;text-align:left;vertical-align:top}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.plus{color:#15803d}.minus{color:#b91c1c}
.big{font-size:2.2rem;font-weight:700;color:#14532d}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:.8rem}
.stats div{background:#f0fdf4;border-radius:8px;padding:.6rem .8rem}
.stats b{display:block;font-size:1.4rem}
form.inline{display:inline}
label{display:block;margin:.4rem 0 .2rem;font-weight:600;font-size:.9rem}
input,select{font:inherit;padding:.45rem .55rem;border:1px solid #c5ced8;border-radius:6px;width:100%;max-width:360px}
input[type=checkbox]{width:auto}
button{font:inherit;padding:.45rem 1rem;border:0;border-radius:6px;background:#15803d;color:#fff;cursor:pointer;margin-top:.6rem}
button.secondary{background:#64748b}button.danger{background:#b91c1c}
button.small{padding:.2rem .6rem;margin:0;font-size:.85rem}
.msg{padding:.6rem 1rem;border-radius:8px;margin-bottom:1rem}
.msg.ok{background:#dcfce7}.msg.err{background:#fee2e2}
.muted{color:#64748b;font-size:.88rem}
.rank{display:inline-block;padding:.1rem .6rem;border-radius:99px;background:#e2e8f0;font-weight:700}
.rank.silver{background:#e5e7eb}.rank.gold{background:#fde68a}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1rem}
.membercard{width:86mm;height:54mm;border-radius:4mm;padding:5mm;color:#fff;
 background:linear-gradient(135deg,#14532d,#15803d);display:flex;flex-direction:column;justify-content:space-between}
.membercard .no{font-size:7mm;letter-spacing:1mm;font-weight:700;font-family:ui-monospace,monospace}
.scroll{overflow-x:auto}.scroll table{min-width:560px}
@media print{header,.noprint{display:none}body{background:#fff}.card{box-shadow:none}}
"""


def yen(n):
    return f"{n:,}"


def page(title, body, nav="", flash=None):
    msg = ""
    if flash:
        kind, text = flash
        msg = f'<div class="msg {kind}">{escape(text)}</div>'
    return (
        "<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(title)}</title><style>{CSS}</style></head><body>"
        f"<header>{nav}</header><main>{msg}{body}</main></body></html>"
    )


ADMIN_NAV = (
    "<a class='brand' href='/admin'>バスツアー会員ポイント 管理</a>"
    "<a href='/admin'>会員</a><a href='/admin/tours'>ツアー</a>"
    "<a href='/admin/members/new'>新規入会</a><a href='/rules'>制度概要</a>"
    "<form class='inline' method='post' action='/admin/logout'>"
    "<button class='small secondary'>ログアウト</button></form>"
)
MEMBER_NAV = (
    "<a class='brand' href='/me'>バスツアー会員ポイント</a><a href='/rules'>ポイント制度</a>"
)


def rank_badge(rank):
    return f"<span class='rank {rank['code']}'>{escape(rank['name'])}</span>"


def history_table(rows):
    if not rows:
        return "<p class='muted'>履歴はまだありません。</p>"
    out = ["<div class='scroll'><table><tr><th>日付</th><th>区分</th><th>内容</th>"
           "<th class='num'>ポイント</th></tr>"]
    for r in rows:
        cls = "plus" if r["points"] > 0 else "minus"
        reason = r["reason"]
        if r["tour_name"] and r["kind"] in ("earn", "bonus") and r["tour_name"] not in reason:
            reason += f"／{r['tour_name']}"
        out.append(
            f"<tr><td>{r['created_on']}</td><td>{KIND_LABELS.get(r['kind'], r['kind'])}</td>"
            f"<td>{escape(reason)}</td><td class='num {cls}'>{r['points']:+,}</td></tr>")
    out.append("</table></div>")
    return "".join(out)


def expiry_table(rows):
    if not rows:
        return "<p class='muted'>有効なポイントはありません。</p>"
    out = ["<table><tr><th>有効期限</th><th class='num'>ポイント</th></tr>"]
    for r in rows:
        out.append(f"<tr><td>{r['expires_on']} まで</td><td class='num'>{yen(r['points'])}</td></tr>")
    out.append("</table>")
    return "".join(out)


def rules_html():
    rank_rows = "".join(
        f"<tr><td>{escape(name)}</td><td>直近1年で{need}回以上参加</td>"
        f"<td class='num'>×{mult:g}</td></tr>" for _, name, need, mult in rules.RANKS)
    return f"""
<div class="card"><h1>ポイント制度のご案内</h1>
<h2>ためる</h2>
<ul>
<li>ご入会で <b>{rules.WELCOME_BONUS}ポイント</b> プレゼント</li>
<li>ツアーにご参加いただくと、お支払額（ポイント利用分を除く税込代金）<b>{rules.YEN_PER_POINT}円ごとに1ポイント</b>
 ×会員ランク倍率。ポイントはツアー終了後に付与されます。</li>
<li>お誕生月に出発するツアーにご参加で <b>{rules.BIRTHDAY_BONUS}ポイント</b> 追加</li>
<li>ご紹介いただいた方が初めてツアーに参加されると、ご紹介者に <b>{rules.REFERRAL_BONUS}ポイント</b></li>
<li>対象ツアーではキャンペーンによるポイント倍増・加算があります</li>
</ul>
<h2>会員ランク</h2>
<table><tr><th>ランク</th><th>条件</th><th class="num">基本ポイント倍率</th></tr>{rank_rows}</table>
<p class="muted">ランクはツアー出発日より前の{rules.RANK_WINDOW_DAYS}日間の参加回数で自動判定します。</p>
<h2>つかう</h2>
<ul><li>{rules.REDEEM_UNIT}ポイント単位で、1ポイント＝{rules.YEN_PER_REDEEMED_POINT}円としてツアー代金のお支払いにご利用いただけます。</li>
<li>予約を取り消した場合、利用したポイントは元の有効期限のままお戻しします。</li></ul>
<h2>有効期限</h2>
<ul><li>ポイントは付与日から{rules.EXPIRY_YEARS}年後の月末まで有効です。期限の近いポイントから順に使われます。</li>
<li>退会された場合、保有ポイントはすべて失効します。</li>
<li>ポイントは換金・他の会員への譲渡はできません。</li></ul>
</div>"""


class App:
    """HTTP に依存しない形でリクエストを処理する（テストから直接呼び出せる）。"""

    def __init__(self, db_path, today=date.today, admin_password=None):
        self.conn = connect(db_path)
        self.today = today
        self._failures = {}
        self.lock = threading.Lock()
        self.secret = self._setting("session_secret", lambda: secrets.token_hex(32))
        self.generated_password = None
        if admin_password:
            self._store_admin_password(admin_password)
        elif not self._get_setting("admin_password_hash"):
            self.generated_password = secrets.token_urlsafe(9)
            self._store_admin_password(self.generated_password)

    # --- 設定・セッション ---------------------------------------------------
    def _get_setting(self, key):
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def _setting(self, key, default):
        value = self._get_setting(key)
        if value is None:
            value = default()
            self.conn.execute("INSERT INTO settings (key, value) VALUES (?,?)", (key, value))
        return value

    def _store_admin_password(self, password):
        self.conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES"
                          " ('admin_password_hash', ?)", (service.hash_pin(password),))

    def _check_admin_password(self, password):
        stored = self._get_setting("admin_password_hash")
        return bool(stored) and service._verify_pin(password, stored)

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

    def _session_cookie(self, payload):
        payload = dict(payload, exp=time.time() + SESSION_SECONDS)
        return ("Set-Cookie", f"sess={self._sign(payload)}; Path=/; HttpOnly; SameSite=Strict;"
                              f" Max-Age={SESSION_SECONDS}")

    # --- 応答ヘルパ -----------------------------------------------------------
    @staticmethod
    def html(body, status=200, headers=()):
        return status, [("Content-Type", "text/html; charset=utf-8"), *headers], body

    @staticmethod
    def redirect(location, flash=None, headers=()):
        if flash:
            kind, text = flash
            sep = "&" if "?" in location else "?"
            location += f"{sep}{kind}={quote(text)}"
        return 303, [("Location", location), *headers], ""

    # --- ルーティング ---------------------------------------------------------
    def handle(self, method, raw_path, form=None, cookie_header=""):
        url = urlsplit(raw_path)
        path = url.path.rstrip("/") or "/"
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        form = form or {}
        jar = cookies.SimpleCookie()
        try:
            jar.load(cookie_header or "")
        except cookies.CookieError:
            pass
        session = self._unsign(jar["sess"].value) if "sess" in jar else None
        session = session or {}
        flash = ("ok", query["ok"]) if "ok" in query else ("err", query["err"]) if "err" in query else None
        ctx = {"method": method, "path": path, "form": form, "query": query,
               "session": session, "flash": flash}
        try:
            if path == "/rules":
                nav = ADMIN_NAV if session.get("role") == "admin" else MEMBER_NAV
                return self.html(page("ポイント制度のご案内", rules_html(), nav))
            if path.startswith("/admin"):
                return self.admin(ctx)
            return self.member(ctx)
        except PointError as e:
            back = form.get("back", "")
            if not back.startswith("/") or back.startswith("//"):
                back = path if path in ("/admin/members/new", "/admin/tours") else path.rsplit("/", 1)[0]
            if method == "GET":
                return self.html(page("エラー", f"<div class='card'>{escape(str(e))}</div>",
                                      ADMIN_NAV if path.startswith("/admin") else MEMBER_NAV), 400)
            return self.redirect(back or "/", ("err", str(e)))

    # --- 会員向け -------------------------------------------------------------
    def member(self, ctx):
        method, path, form = ctx["method"], ctx["path"], ctx["form"]
        member_no = ctx["session"].get("member_no") if ctx["session"].get("role") == "member" else None
        if path == "/" and method == "GET":
            if member_no:
                return self.redirect("/me")
            return self.html(page("会員ログイン", """
<div class="card"><h1>会員ページ ログイン</h1>
<form method="post" action="/login">
<label>会員番号</label><input name="member_no" placeholder="BT00000017" autocomplete="username" required>
<label>暗証番号</label><input name="pin" type="password" inputmode="numeric" autocomplete="current-password" required>
<button>ログイン</button></form>
<p class="muted">会員番号は会員証に記載されています。暗証番号をお忘れの場合はツアー窓口へお問い合わせください。</p>
</div>""", MEMBER_NAV, ctx["flash"]))
        if path == "/login" and method == "POST":
            no = form.get("member_no", "")
            key = no.strip().upper()
            fails, since = self._failures.get(key, (0, 0))
            if fails >= MAX_PIN_FAILURES and time.time() - since < LOCK_SECONDS:
                return self.redirect("/", ("err", "ログイン失敗が続いたため一時的にロックしています。15分後に再度お試しください"))
            m = service.authenticate_member(self.conn, no, form.get("pin", ""))
            if not m:
                self._failures[key] = (fails + 1 if time.time() - since < LOCK_SECONDS else 1, time.time())
                return self.redirect("/", ("err", "会員番号または暗証番号が正しくありません"))
            self._failures.pop(key, None)
            return self.redirect("/me", headers=[self._session_cookie(
                {"role": "member", "member_no": m["member_no"]})])
        if path == "/logout" and method == "POST":
            return self.redirect("/", ("ok", "ログアウトしました"),
                                 [("Set-Cookie", "sess=; Path=/; Max-Age=0")])
        if not member_no:
            return self.redirect("/")
        m = service.get_member(self.conn, member_no)
        if m["status"] != "active":
            return self.redirect("/", headers=[("Set-Cookie", "sess=; Path=/; Max-Age=0")])
        if path == "/me" and method == "GET":
            return self.html(page("マイページ", self.member_summary(m, staff=False),
                                  MEMBER_NAV, ctx["flash"]))
        if path == "/me/pin" and method == "POST":
            if not service.authenticate_member(self.conn, member_no, form.get("current_pin", "")):
                return self.redirect("/me", ("err", "現在の暗証番号が正しくありません"))
            service.change_pin(self.conn, member_no, form.get("new_pin", ""))
            return self.redirect("/me", ("ok", "暗証番号を変更しました"))
        return self.html(page("Not Found", "<div class='card'>ページが見つかりません</div>", MEMBER_NAV), 404)

    def member_summary(self, m, staff):
        today = self.today()
        bal = service.balance(self.conn, m["id"], today)
        rank = service.rank_for(self.conn, m["id"], today)
        next_rank = (f"あと{rank['tours_to_next']}回の参加で{escape(rank['next_name'])}に"
                     if rank["next_name"] else "最上位ランクです")
        bookings = service.member_bookings(self.conn, m["id"])
        brows = "".join(
            f"<tr><td>{b['depart_date']}</td><td>{escape(b['tour_name'])}</td>"
            f"<td class='num'>{yen(b['price'])}</td><td class='num'>{yen(b['points_used'])}</td>"
            f"<td>{BOOKING_LABELS[b['status']]}</td>"
            + (f"<td>{self._cancel_button(b, '/admin/members/' + m['member_no'])}</td>" if staff else "")
            + "</tr>"
            for b in bookings)
        btable = (f"<div class='scroll'><table><tr><th>出発日</th><th>ツアー</th><th class='num'>代金</th>"
                  f"<th class='num'>利用pt</th><th>状態</th>{'<th></th>' if staff else ''}</tr>{brows}</table></div>"
                  if bookings else "<p class='muted'>ツアーのご予約・参加履歴はまだありません。</p>")
        pin_form = "" if staff else """
<div class="card"><h2>暗証番号の変更</h2><form method="post" action="/me/pin">
<label>現在の暗証番号</label><input name="current_pin" type="password" inputmode="numeric" required>
<label>新しい暗証番号（4〜8桁の数字）</label><input name="new_pin" type="password" inputmode="numeric" required>
<button>変更する</button></form>
<form method="post" action="/logout"><button class="secondary">ログアウト</button></form></div>"""
        status = "" if m["status"] == "active" else " <span class='rank'>退会済</span>"
        return f"""
<div class="card"><h1>{escape(m['name'])} 様{status}</h1>
<div class="grid2"><div>
<div class="muted">会員番号 {m['member_no']}</div>
<div class="big">{yen(bal)} <small>pt</small></div>
<div>会員ランク {rank_badge(rank)} <span class="muted">（直近1年の参加 {rank['tours']}回・{next_rank}）</span></div>
</div><div><h2>有効期限別の残高</h2>{expiry_table(service.expiring_schedule(self.conn, m['id'], today))}</div></div>
</div>
<div class="card"><h2>ツアー</h2>{btable}</div>
<div class="card"><h2>ポイント履歴</h2>{history_table(service.history(self.conn, m['id']))}</div>
{pin_form}"""

    # --- スタッフ向け ---------------------------------------------------------
    def admin(self, ctx):
        method, path, form = ctx["method"], ctx["path"], ctx["form"]
        if path == "/admin/login":
            if method == "POST":
                if self._check_admin_password(form.get("password", "")):
                    op = form.get("operator", "").strip() or "staff"
                    return self.redirect("/admin", headers=[self._session_cookie(
                        {"role": "admin", "operator": op})])
                return self.redirect("/admin/login", ("err", "パスワードが正しくありません"))
            return self.html(page("スタッフログイン", """
<div class="card"><h1>スタッフログイン</h1><form method="post" action="/admin/login">
<label>担当者名（操作履歴に記録されます）</label><input name="operator" required>
<label>管理パスワード</label><input name="password" type="password" required>
<button>ログイン</button></form></div>""", "<a class='brand' href='/admin'>バスツアー会員ポイント 管理</a>",
                                  ctx["flash"]))
        if ctx["session"].get("role") != "admin":
            return self.redirect("/admin/login")
        op = ctx["session"].get("operator", "staff")
        today = self.today()
        f = ctx["flash"]

        if path == "/admin/logout" and method == "POST":
            return self.redirect("/admin/login", ("ok", "ログアウトしました"),
                                 [("Set-Cookie", "sess=; Path=/; Max-Age=0")])
        if path == "/admin" and method == "GET":
            return self.html(page("管理トップ", self.admin_home(ctx["query"].get("q", "")), ADMIN_NAV, f))
        if path == "/admin/expire" and method == "POST":
            n = service.expire_points(self.conn, today)
            return self.redirect("/admin", ("ok", f"失効処理を実行しました（{yen(n)}ポイント失効）"))

        if path == "/admin/members/new":
            if method == "POST":
                m = service.register_member(
                    self.conn, form.get("name", ""), form.get("pin", ""), today,
                    kana=form.get("kana", ""), phone=form.get("phone", ""),
                    email=form.get("email", ""), birthdate=form.get("birthdate") or None,
                    referrer_no=form.get("referrer_no") or None, operator=op)
                return self.redirect(f"/admin/members/{m['member_no']}",
                                     ("ok", f"入会登録しました。会員番号 {m['member_no']}"))
            return self.html(page("新規入会", self.member_form(), ADMIN_NAV, f))

        if path.startswith("/admin/members/"):
            parts = path.split("/")[3:]
            m = service.get_member(self.conn, parts[0])
            base = f"/admin/members/{m['member_no']}"
            action = parts[1] if len(parts) > 1 else ""
            if action == "" and method == "GET":
                return self.html(page(m["name"], self.admin_member(m), ADMIN_NAV, f))
            if action == "card" and method == "GET":
                return self.html(page("会員証", self.member_card(m), ADMIN_NAV))
            if action == "adjust" and method == "POST":
                pts = self._int(form.get("points"), "調整ポイント")
                service.adjust_points(self.conn, m["member_no"], pts, form.get("reason", ""), today, op)
                return self.redirect(base, ("ok", f"{pts:+,}ポイント調整しました"))
            if action == "pin" and method == "POST":
                service.change_pin(self.conn, m["member_no"], form.get("pin", ""))
                return self.redirect(base, ("ok", "暗証番号を再設定しました"))
            if action == "withdraw" and method == "POST":
                if form.get("confirm") != "yes":
                    raise PointError("確認チェックを入れてください")
                service.withdraw_member(self.conn, m["member_no"], today, op)
                return self.redirect(base, ("ok", "退会処理を行いました"))

        if path == "/admin/tours":
            if method == "POST":
                t = service.create_tour(
                    self.conn, form.get("code"), form.get("name"), form.get("depart_date", ""),
                    self._int(form.get("price"), "代金"),
                    self._float(form.get("bonus_multiplier") or "1", "キャンペーン倍率"),
                    self._int(form.get("bonus_points") or "0", "加算ポイント"))
                return self.redirect(f"/admin/tours/{t['id']}", ("ok", "ツアーを登録しました"))
            return self.html(page("ツアー", self.admin_tours(), ADMIN_NAV, f))

        if path.startswith("/admin/tours/"):
            parts = path.split("/")[3:]
            tour = service.get_tour(self.conn, self._int(parts[0], "ツアーID"))
            base = f"/admin/tours/{tour['id']}"
            action = parts[1] if len(parts) > 1 else ""
            if action == "" and method == "GET":
                return self.html(page(tour["name"], self.admin_tour(tour, ctx["query"]), ADMIN_NAV, f))
            if action == "book" and method == "POST":
                service.book_tour(self.conn, form.get("member_no", ""), tour["id"],
                                  self._int(form.get("points") or "0", "利用ポイント"), today, op)
                return self.redirect(base, ("ok", "予約を登録しました"))
            if action == "complete" and method == "POST":
                absent = [self._int(v, "予約ID") for k, v in form.items() if k.startswith("absent_")]
                n = service.complete_tour(self.conn, tour["id"], today, op, absent)
                return self.redirect(base, ("ok", f"催行完了として{yen(n)}ポイントを付与しました"))
            if action == "cancel" and method == "POST":
                if form.get("confirm") != "yes":
                    raise PointError("確認チェックを入れてください")
                service.cancel_tour(self.conn, tour["id"], today, op)
                return self.redirect(base, ("ok", "ツアーを中止し、利用ポイントを返還しました"))

        if path.startswith("/admin/bookings/") and path.endswith("/cancel") and method == "POST":
            booking_id = self._int(path.split("/")[3], "予約ID")
            service.cancel_booking(self.conn, booking_id, today, op)
            back = form.get("back") or "/admin"
            if not back.startswith("/admin"):
                back = "/admin"
            return self.redirect(back, ("ok", "予約を取り消し、利用ポイントを返還しました"))

        return self.html(page("Not Found", "<div class='card'>ページが見つかりません</div>", ADMIN_NAV), 404)

    @staticmethod
    def _int(value, label):
        try:
            return int(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            raise PointError(f"{label}は整数で入力してください")

    @staticmethod
    def _float(value, label):
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            raise PointError(f"{label}は数値で入力してください")

    @staticmethod
    def _cancel_button(b, back):
        if b["status"] != "booked":
            return ""
        return (f"<form class='inline' method='post' action='/admin/bookings/{b['id']}/cancel'"
                f" onsubmit=\"return confirm('予約を取り消しますか？')\">"
                f"<input type='hidden' name='back' value='{escape(back)}'>"
                f"<button class='small danger'>取消</button></form>")

    def admin_home(self, q):
        today = self.today()
        d = service.dashboard(self.conn, today)
        rows = service.search_members(self.conn, q) if q else service.search_members(self.conn, "", 20)
        mrows = "".join(
            f"<tr><td><a href='/admin/members/{m['member_no']}'>{m['member_no']}</a></td>"
            f"<td>{escape(m['name'])}</td><td>{escape(m['phone'])}</td>"
            f"<td class='num'>{yen(service.balance(self.conn, m['id'], today))}</td>"
            f"<td>{'有効' if m['status'] == 'active' else '退会'}</td></tr>" for m in rows)
        return f"""
<div class="card"><h1>ダッシュボード <span class="muted">{today}</span></h1>
<div class="stats">
<div>有効会員数<b>{yen(d['members'])}名</b></div>
<div>未使用ポイント残高<b>{yen(d['outstanding'])}pt</b></div>
<div>{d['horizon_days']}日以内に失効予定<b>{yen(d['expiring_soon'])}pt</b></div>
<div>催行予定ツアー<b>{d['scheduled_tours']}件</b></div>
</div>
<form method="post" action="/admin/expire" class="noprint"><button class="secondary">期限切れポイントの失効処理を実行</button>
<span class="muted">（残高表示は期限切れを自動的に除外します。台帳へ失効記録を残すため定期的に実行してください）</span></form>
</div>
<div class="card"><h2>会員検索</h2>
<form method="get" action="/admin"><input name="q" value="{escape(q)}" placeholder="会員番号・氏名・カナ・電話・メール">
<button>検索</button></form>
<div class="scroll"><table><tr><th>会員番号</th><th>氏名</th><th>電話</th><th class="num">残高</th><th>状態</th></tr>
{mrows or "<tr><td colspan=5 class='muted'>該当なし</td></tr>"}</table></div>
<p class="muted">{'検索結果' if q else '最近入会した会員（20件）'}</p></div>"""

    @staticmethod
    def member_form():
        return """
<div class="card"><h1>新規入会</h1><form method="post" action="/admin/members/new">
<label>氏名 *</label><input name="name" required>
<label>フリガナ</label><input name="kana">
<label>電話番号</label><input name="phone" inputmode="tel">
<label>メールアドレス</label><input name="email" type="email">
<label>生年月日（誕生月特典に使用）</label><input name="birthdate" type="date">
<label>紹介者の会員番号（任意）</label><input name="referrer_no" placeholder="BT00000017">
<label>会員ページ用 暗証番号 *（4〜8桁の数字・お客様に決めていただく）</label>
<input name="pin" type="password" inputmode="numeric" required>
<button>入会登録</button></form>
<p class="muted">個人情報は本システム内（ローカルのデータベースファイル）にのみ保存され、外部サービスへは送信されません。</p></div>"""

    def admin_member(self, m):
        base = f"/admin/members/{m['member_no']}"
        ref = ""
        if m["referrer_id"]:
            r = self.conn.execute("SELECT member_no, name FROM members WHERE id=?",
                                  (m["referrer_id"],)).fetchone()
            ref = f"<br>紹介者: <a href='/admin/members/{r['member_no']}'>{escape(r['name'])}</a>"
        info = f"""
<div class="card"><h2>登録情報</h2>
フリガナ: {escape(m['kana'])}<br>電話: {escape(m['phone'])}<br>メール: {escape(m['email'])}<br>
生年月日: {m['birthdate'] or '-'}<br>入会日: {m['joined_on']}{ref}<br>
<a href="{base}/card">会員証を印刷</a></div>"""
        tools = "" if m["status"] != "active" else f"""
<div class="grid2">
<div class="card"><h2>ポイント調整</h2><form method="post" action="{base}/adjust">
<label>ポイント（減算はマイナス）</label><input name="points" inputmode="numeric" required>
<label>理由 *</label><input name="reason" required placeholder="例: 付与漏れ訂正、お詫び">
<button>調整する</button></form></div>
<div class="card"><h2>暗証番号の再設定</h2><form method="post" action="{base}/pin">
<label>新しい暗証番号</label><input name="pin" type="password" inputmode="numeric" required>
<button>再設定</button></form>
<h2 style="margin-top:1.2rem">退会</h2><form method="post" action="{base}/withdraw">
<label><input type="checkbox" name="confirm" value="yes"> 保有ポイントが失効することを説明済み</label>
<button class="danger">退会処理</button></form></div></div>"""
        return self.member_summary(m, staff=True).replace("<div class=\"card\"><h2>ツアー</h2>",
                                                          info + "<div class=\"card\"><h2>ツアー</h2>", 1) + tools

    def member_card(self, m):
        return f"""
<div class="card"><div class="membercard">
<div><b>バスツアー ポイント会員証</b></div>
<div class="no">{m['member_no']}</div>
<div>{escape(m['name'])} 様<br><small>入会日 {m['joined_on']}</small></div>
</div>
<p class="muted">会員ページ: このシステムのURLにアクセスし、会員番号と暗証番号でログインしてください。</p>
<button class="noprint" onclick="window.print()">印刷</button></div>"""

    def admin_tours(self):
        rows = "".join(
            f"<tr><td>{t['depart_date']}</td><td>{escape(t['code'])}</td>"
            f"<td><a href='/admin/tours/{t['id']}'>{escape(t['name'])}</a></td>"
            f"<td class='num'>{yen(t['price'])}</td>"
            f"<td>{'×%g' % t['bonus_multiplier'] if t['bonus_multiplier'] != 1 else ''}"
            f"{' +%dpt' % t['bonus_points'] if t['bonus_points'] else ''}</td>"
            f"<td class='num'>{t['participants']}</td><td>{TOUR_LABELS[t['status']]}</td></tr>"
            for t in service.list_tours(self.conn))
        return f"""
<div class="card"><h1>ツアー一覧</h1><div class="scroll"><table>
<tr><th>出発日</th><th>コード</th><th>ツアー名</th><th class="num">代金</th><th>キャンペーン</th><th class="num">人数</th><th>状態</th></tr>
{rows or "<tr><td colspan=7 class='muted'>登録されたツアーはありません</td></tr>"}</table></div></div>
<div class="card"><h2>ツアー登録</h2><form method="post" action="/admin/tours">
<label>ツアーコード *</label><input name="code" required placeholder="例: 2026-11-HAKONE">
<label>ツアー名 *</label><input name="name" required>
<label>出発日 *</label><input name="depart_date" type="date" required>
<label>代金（税込・1名） *</label><input name="price" inputmode="numeric" required>
<label>キャンペーン倍率（通常は1）</label><input name="bonus_multiplier" value="1">
<label>キャンペーン加算ポイント（通常は0）</label><input name="bonus_points" value="0" inputmode="numeric">
<button>登録</button></form></div>"""

    def admin_tour(self, tour, query):
        today = self.today()
        base = f"/admin/tours/{tour['id']}"
        bookings = service.tour_bookings(self.conn, tour["id"])
        open_ = tour["status"] == "scheduled"
        rows = []
        for b in bookings:
            est = ""
            if b["status"] == "booked":
                m = self.conn.execute("SELECT * FROM members WHERE id=?", (b["member_id"],)).fetchone()
                rank, items = service.estimate_earn(self.conn, m, tour, b["price"] - b["points_used"])
                est = f"{yen(sum(p for _, p in items))}pt（{escape(rank['name'])}）"
            rows.append(
                f"<tr><td><a href='/admin/members/{b['member_no']}'>{b['member_no']}</a></td>"
                f"<td>{escape(b['name'])}</td><td class='num'>{yen(b['points_used'])}</td>"
                f"<td class='num'>{yen(b['price'] - b['points_used'])}</td><td>{est}</td>"
                f"<td>{BOOKING_LABELS[b['status']]}</td>"
                f"<td>{self._cancel_button(b, base) if open_ else ''}</td></tr>")
        table = (
            "<div class='scroll'><table><tr><th>会員番号</th><th>氏名</th><th class='num'>利用pt</th>"
            "<th class='num'>支払額</th><th>付与予定</th><th>状態</th><th></th></tr>"
            + "".join(rows) + "</table></div>") if rows else "<p class='muted'>予約はまだありません。</p>"

        booking_form = complete_form = ""
        if open_:
            check_no = query.get("check", "")
            hint = ""
            if check_no:
                try:
                    cm = service.get_member(self.conn, check_no)
                    mx = service.max_redeemable(self.conn, cm["id"], tour["price"], today)
                    hint = (f"<p>{escape(cm['name'])} 様: 残高 {yen(service.balance(self.conn, cm['id'], today))}pt"
                            f" ／ このツアーで利用可能 最大 {yen(mx)}pt</p>")
                except PointError as e:
                    hint = f"<p class='minus'>{escape(str(e))}</p>"
            booking_form = f"""
<div class="card"><h2>予約登録</h2>
<form method="get" action="{base}"><label>会員番号</label>
<input name="check" value="{escape(check_no)}" placeholder="BT00000017"><button class="secondary">残高確認</button></form>
{hint}
<form method="post" action="{base}/book">
<input type="hidden" name="member_no" value="{escape(check_no)}">
<label>利用ポイント（{rules.REDEEM_UNIT}pt単位・利用しない場合は0）</label><input name="points" value="0" inputmode="numeric">
<button {'disabled' if not check_no else ''}>予約登録</button>
<span class="muted">{'先に会員番号で残高確認してください' if not check_no else ''}</span></form></div>"""
            booked = [b for b in bookings if b["status"] == "booked"]
            checks = "".join(
                f"<label><input type='checkbox' name='absent_{b['id']}' value='{b['id']}'> "
                f"{escape(b['name'])}（{b['member_no']}）は不参加</label>" for b in booked)
            complete_form = f"""
<div class="grid2"><div class="card"><h2>催行完了・ポイント付与</h2>
<form method="post" action="{base}/complete" onsubmit="return confirm('参加者にポイントを付与します。よろしいですか？')">
{checks or "<p class='muted'>参加予定者はいません。</p>"}
<button>催行完了として付与</button></form>
<p class="muted">出発日以降に実行できます。不参加の方には付与されず、利用ポイントも返還されません（取消扱いにする場合は先に「取消」してください）。</p></div>
<div class="card"><h2>催行中止</h2><form method="post" action="{base}/cancel">
<label><input type="checkbox" name="confirm" value="yes"> 全予約を取り消し、利用ポイントを返還する</label>
<button class="danger">ツアーを中止</button></form></div></div>"""
        camp = []
        if tour["bonus_multiplier"] != 1:
            camp.append(f"ポイント×{tour['bonus_multiplier']:g}")
        if tour["bonus_points"]:
            camp.append(f"+{tour['bonus_points']}pt")
        return f"""
<div class="card"><h1>{escape(tour['name'])}</h1>
コード {escape(tour['code'])} ／ 出発日 {tour['depart_date']} ／ 代金 {yen(tour['price'])}円 ／
{TOUR_LABELS[tour['status']]}{' ／ キャンペーン ' + '・'.join(camp) if camp else ''}</div>
<div class="card"><h2>予約者</h2>{table}</div>{booking_form}{complete_form}"""


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def _run(self, method):
            form = {}
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(min(length, 1_000_000)).decode("utf-8", "replace")
                form = {k: v[0] for k, v in parse_qs(body).items()}
            with app.lock:
                status, headers, body = app.handle(method, self.path, form,
                                                   self.headers.get("Cookie", ""))
            data = body.encode("utf-8")
            self.send_response(status)
            for k, v in headers:
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._run("GET")

        def do_POST(self):
            self._run("POST")

    return Handler


def serve(db_path, host="127.0.0.1", port=8000, admin_password=None):
    app = App(db_path, admin_password=admin_password)
    if app.generated_password:
        print(f"[初回起動] スタッフ用管理パスワードを生成しました: {app.generated_password}")
        print("  変更する場合: python -m points passwd")
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    print(f"会員ページ:   http://{host}:{port}/")
    print(f"スタッフ画面: http://{host}:{port}/admin")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
