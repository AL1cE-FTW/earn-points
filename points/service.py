"""マイレージ制度の業務ロジック（入会・付与・利用・取消・失効・退会、道ツアーの招待、スタッフ）。"""

import calendar
import hashlib
import hmac
import math
import secrets
from datetime import date, timedelta

from . import rules
from .db import transaction


class PointError(Exception):
    """利用者に表示してよい業務エラー。"""


# --- 共通 -----------------------------------------------------------------

def _iso(d):
    return d.isoformat() if isinstance(d, date) else d


def _date(s):
    return s if isinstance(s, date) else date.fromisoformat(s)


def expiry_date(granted_on):
    """付与日から EXPIRY_YEARS 年後の月末。"""
    g = _date(granted_on)
    year = g.year + rules.EXPIRY_YEARS
    return date(year, g.month, calendar.monthrange(year, g.month)[1])


def _check_digit(digits):
    """Luhn 方式のチェックディジット（会員番号の入力ミス検出用）。"""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return str((10 - total % 10) % 10)


def make_member_no(seq):
    body = f"{seq:07d}"
    return "BT" + body + _check_digit(body)


def normalize_member_no(text):
    s = (text or "").strip().upper().replace("-", "").replace(" ", "")
    if len(s) != 10 or not s.startswith("BT") or not s[2:].isdigit():
        raise PointError("会員番号の形式が正しくありません（例: BT00000017）")
    if _check_digit(s[2:9]) != s[9]:
        raise PointError("会員番号が正しくありません。入力内容をご確認ください")
    return s


def hash_pin(pin):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 200_000)
    return f"{salt}${digest.hex()}"


def _verify_pin(pin, stored):
    salt, digest = stored.split("$")
    test = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 200_000)
    return hmac.compare_digest(test.hex(), digest)


def _validate_pin(pin):
    if not (pin.isdigit() and 4 <= len(pin) <= 8):
        raise PointError("暗証番号は4〜8桁の数字で設定してください")


# --- 会員 -----------------------------------------------------------------

def register_member(conn, name, pin, today, kana="", phone="", email="",
                    birthdate=None, referrer_no=None, operator=""):
    name = (name or "").strip()
    if not name:
        raise PointError("氏名は必須です")
    _validate_pin(pin)
    if birthdate:
        try:
            birthdate = _iso(_date(birthdate))
        except ValueError:
            raise PointError("生年月日を正しく入力してください")
    with transaction(conn):
        referrer_id = None
        if referrer_no:
            ref = get_member(conn, referrer_no)
            if ref["status"] != "active":
                raise PointError("紹介者の会員番号は現在有効ではありません")
            referrer_id = ref["id"]
        cur = conn.execute(
            "INSERT INTO members (member_no, name, kana, phone, email, birthdate,"
            " pin_hash, referrer_id, joined_on) VALUES (?,?,?,?,?,?,?,?,?)",
            ("pending-" + secrets.token_hex(8), name, kana.strip(), phone.strip(),
             email.strip(), birthdate, hash_pin(pin), referrer_id, _iso(today)))
        member_id = cur.lastrowid
        conn.execute("UPDATE members SET member_no=? WHERE id=?",
                     (make_member_no(member_id), member_id))
        if rules.WELCOME_BONUS:
            _grant(conn, member_id, "bonus", rules.WELCOME_BONUS, "入会特典",
                   today, operator=operator)
    return conn.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()


def get_member(conn, member_no):
    row = conn.execute("SELECT * FROM members WHERE member_no=?",
                       (normalize_member_no(member_no),)).fetchone()
    if row is None:
        raise PointError("該当する会員が見つかりません")
    return row


def authenticate_member(conn, member_no, pin):
    try:
        m = get_member(conn, member_no)
    except PointError:
        return None
    if m["status"] != "active" or not _verify_pin(pin or "", m["pin_hash"]):
        return None
    return m


def change_pin(conn, member_no, new_pin):
    _validate_pin(new_pin)
    m = get_member(conn, member_no)
    conn.execute("UPDATE members SET pin_hash=?, session_gen=session_gen+1 WHERE id=?",
                 (hash_pin(new_pin), m["id"]))


def search_members(conn, query, limit=50):
    q = f"%{query.strip()}%"
    return conn.execute(
        "SELECT * FROM members WHERE member_no LIKE ? OR name LIKE ? OR kana LIKE ?"
        " OR phone LIKE ? OR email LIKE ? ORDER BY id DESC LIMIT ?",
        (q, q, q, q, q, limit)).fetchall()


def withdraw_member(conn, member_no, today, operator=""):
    """退会。保有マイルはすべて失効する。"""
    with transaction(conn):
        m = get_member(conn, member_no)
        if m["status"] != "active":
            raise PointError("すでに退会済みです")
        pending = conn.execute(
            "SELECT COUNT(*) FROM bookings WHERE member_id=? AND status='booked'",
            (m["id"],)).fetchone()[0]
        if pending:
            raise PointError("参加予定のツアーがあるため退会できません。先に予約を取り消してください")
        bal = balance(conn, m["id"], today)
        if bal:
            _consume(conn, m["id"], "forfeit", bal, "退会による失効", today, operator=operator)
        conn.execute("UPDATE members SET status='withdrawn' WHERE id=?", (m["id"],))


# --- ステイタス -----------------------------------------------------------------

def rank_for(conn, member_id, on_date):
    """on_date より前の365日間に参加完了したツアー数でステイタスを決める。"""
    end = _date(on_date)
    start = end - timedelta(days=rules.RANK_WINDOW_DAYS)
    count = conn.execute(
        "SELECT COUNT(*) FROM bookings b JOIN tours t ON t.id=b.tour_id"
        " WHERE b.member_id=? AND b.status='completed'"
        " AND t.depart_date >= ? AND t.depart_date < ?",
        (member_id, _iso(start), _iso(end))).fetchone()[0]
    current = rules.RANKS[0]
    for rank in rules.RANKS:
        if count >= rank[2]:
            current = rank
    nxt = next((r for r in rules.RANKS if r[2] > count), None)
    return {
        "code": current[0], "name": current[1], "multiplier": current[3],
        "tours": count,
        "next_name": nxt[1] if nxt else None,
        "tours_to_next": (nxt[2] - count) if nxt else 0,
    }


# --- 残高・台帳 ---------------------------------------------------------------

def balance(conn, member_id, today):
    return conn.execute(
        "SELECT COALESCE(SUM(remaining),0) FROM point_lots"
        " WHERE member_id=? AND expires_on >= ?", (member_id, _iso(today))).fetchone()[0]


def expiring_schedule(conn, member_id, today):
    """有効期限ごとの残マイル（期限が近い順）。"""
    return conn.execute(
        "SELECT expires_on, SUM(remaining) AS points FROM point_lots"
        " WHERE member_id=? AND expires_on >= ? AND remaining > 0"
        " GROUP BY expires_on ORDER BY expires_on", (member_id, _iso(today))).fetchall()


def history(conn, member_id, limit=100):
    return conn.execute(
        "SELECT p.*, t.name AS tour_name FROM point_txns p"
        " LEFT JOIN bookings b ON b.id=p.booking_id LEFT JOIN tours t ON t.id=b.tour_id"
        " WHERE p.member_id=? ORDER BY p.id DESC LIMIT ?", (member_id, limit)).fetchall()


def _add_txn(conn, member_id, kind, points, reason, today, booking_id, operator):
    cur = conn.execute(
        "INSERT INTO point_txns (member_id, kind, points, reason, booking_id, created_on, operator)"
        " VALUES (?,?,?,?,?,?,?)",
        (member_id, kind, points, reason, booking_id, _iso(today), operator))
    return cur.lastrowid


def _grant(conn, member_id, kind, points, reason, today, booking_id=None, operator=""):
    if points <= 0:
        return None
    txn_id = _add_txn(conn, member_id, kind, points, reason, today, booking_id, operator)
    conn.execute(
        "INSERT INTO point_lots (member_id, txn_id, amount, remaining, granted_on, expires_on)"
        " VALUES (?,?,?,?,?,?)",
        (member_id, txn_id, points, points, _iso(today), _iso(expiry_date(today))))
    return txn_id


def _consume(conn, member_id, kind, points, reason, today, booking_id=None, operator=""):
    """有効期限の近い付与分から順に消費する。"""
    if points <= 0:
        return None
    if balance(conn, member_id, today) < points:
        raise PointError("マイル残高が不足しています")
    txn_id = _add_txn(conn, member_id, kind, -points, reason, today, booking_id, operator)
    left = points
    lots = conn.execute(
        "SELECT id, remaining FROM point_lots WHERE member_id=? AND expires_on >= ?"
        " AND remaining > 0 ORDER BY expires_on, id", (member_id, _iso(today))).fetchall()
    for lot in lots:
        use = min(left, lot["remaining"])
        conn.execute("UPDATE point_lots SET remaining=remaining-? WHERE id=?", (use, lot["id"]))
        conn.execute("INSERT INTO lot_usages (txn_id, lot_id, points) VALUES (?,?,?)",
                     (txn_id, lot["id"], use))
        left -= use
        if left == 0:
            break
    return txn_id


def adjust_points(conn, member_no, points, reason, today, operator=""):
    """スタッフによる手動加算・減算（お詫び・訂正など）。理由は必須。"""
    reason = (reason or "").strip()
    if not reason:
        raise PointError("調整理由を入力してください")
    if points == 0:
        raise PointError("調整マイルを入力してください")
    with transaction(conn):
        m = get_member(conn, member_no)
        if m["status"] != "active":
            raise PointError("退会済み会員のマイルは調整できません")
        if points > 0:
            _grant(conn, m["id"], "adjust", points, reason, today, operator=operator)
        else:
            _consume(conn, m["id"], "adjust", -points, reason, today, operator=operator)


def expire_points(conn, today):
    """有効期限を過ぎたマイルを失効させ、台帳に記録する。失効マイル合計を返す。"""
    total = 0
    with transaction(conn):
        lots = conn.execute(
            "SELECT id, member_id, remaining, expires_on FROM point_lots"
            " WHERE expires_on < ? AND remaining > 0 ORDER BY member_id, expires_on",
            (_iso(today),)).fetchall()
        by_member = {}
        for lot in lots:
            by_member.setdefault(lot["member_id"], []).append(lot)
        for member_id, member_lots in by_member.items():
            pts = sum(l["remaining"] for l in member_lots)
            txn_id = _add_txn(conn, member_id, "expire", -pts, "有効期限切れによる失効",
                              today, None, "system")
            for lot in member_lots:
                conn.execute("UPDATE point_lots SET remaining=0 WHERE id=?", (lot["id"],))
                conn.execute("INSERT INTO lot_usages (txn_id, lot_id, points) VALUES (?,?,?)",
                             (txn_id, lot["id"], lot["remaining"]))
            total += pts
    return total


# --- ツアー・予約 ---------------------------------------------------------------

def create_tour(conn, code, name, depart_date, price, bonus_multiplier=1.0, bonus_points=None,
                kind="normal", invite_min_tours=None):
    """ツアーを登録する。kind="michi" は招待制の道ツアー。

    道ツアーで invite_min_tours / bonus_points を省略（None）した場合は、設定の既定値を使う。
    """
    code, name = (code or "").strip(), (name or "").strip()
    if kind not in TOUR_KINDS:
        raise PointError("ツアーの種類が正しくありません")
    if kind == "michi":
        d = michi_settings(conn)
        invite_min_tours = d["min_tours"] if invite_min_tours is None else invite_min_tours
        bonus_points = d["bonus"] if bonus_points is None else bonus_points
        if not isinstance(invite_min_tours, int) or invite_min_tours < 1:
            raise PointError("招待条件の参加回数は1以上の整数で入力してください")
    else:
        invite_min_tours = None
        bonus_points = bonus_points or 0
    if not code or not name:
        raise PointError("ツアーコードとツアー名は必須です")
    if price <= 0:
        raise PointError("代金は1円以上で入力してください")
    if bonus_multiplier < 1 or bonus_points < 0:
        raise PointError("キャンペーン倍率は1以上、加算マイルは0以上で入力してください")
    if conn.execute("SELECT 1 FROM tours WHERE code=?", (code,)).fetchone():
        raise PointError("同じツアーコードがすでに登録されています")
    try:
        depart = _iso(_date(depart_date))
    except ValueError:
        raise PointError("出発日を正しく入力してください")
    cur = conn.execute(
        "INSERT INTO tours (code, name, depart_date, price, bonus_multiplier, bonus_points,"
        " kind, invite_min_tours) VALUES (?,?,?,?,?,?,?,?)",
        (code, name, depart, price, bonus_multiplier, bonus_points, kind, invite_min_tours))
    return get_tour(conn, cur.lastrowid)


def get_tour(conn, tour_id):
    row = conn.execute("SELECT * FROM tours WHERE id=?", (tour_id,)).fetchone()
    if row is None:
        raise PointError("ツアーが見つかりません")
    return row


def list_tours(conn):
    return conn.execute(
        "SELECT t.*, (SELECT COUNT(*) FROM bookings b WHERE b.tour_id=t.id"
        " AND b.status!='cancelled') AS participants FROM tours t"
        " ORDER BY t.depart_date DESC, t.id DESC").fetchall()


def tour_bookings(conn, tour_id):
    return conn.execute(
        "SELECT b.*, m.member_no, m.name FROM bookings b JOIN members m ON m.id=b.member_id"
        " WHERE b.tour_id=? ORDER BY b.id", (tour_id,)).fetchall()


def member_bookings(conn, member_id):
    return conn.execute(
        "SELECT b.*, t.code, t.name AS tour_name, t.depart_date FROM bookings b"
        " JOIN tours t ON t.id=b.tour_id WHERE b.member_id=?"
        " ORDER BY t.depart_date DESC", (member_id,)).fetchall()


def max_redeemable(conn, member_id, price, today):
    bal = min(balance(conn, member_id, today), price // rules.YEN_PER_REDEEMED_POINT)
    return bal - bal % rules.REDEEM_UNIT


def book_tour(conn, member_no, tour_id, points_to_use, today, operator=""):
    """ツアー予約を登録し、指定があればマイルを代金に充当する。"""
    with transaction(conn):
        m = get_member(conn, member_no)
        if m["status"] != "active":
            raise PointError("退会済みの会員です")
        tour = get_tour(conn, tour_id)
        if tour["status"] != "scheduled":
            raise PointError("このツアーは予約を受け付けていません")
        if tour["kind"] == "michi" and not invite_for(conn, tour_id, m["id"]):
            raise PointError("道ツアーは招待された会員だけが予約できます。先に招待を送ってください")
        if conn.execute("SELECT 1 FROM bookings WHERE member_id=? AND tour_id=?"
                        " AND status!='cancelled'", (m["id"], tour_id)).fetchone():
            raise PointError("この会員はすでにこのツアーを予約しています")
        if points_to_use < 0 or points_to_use % rules.REDEEM_UNIT:
            raise PointError(f"マイルは{rules.REDEEM_UNIT}マイル単位でご利用いただけます")
        if points_to_use > max_redeemable(conn, m["id"], tour["price"], today):
            raise PointError("利用マイルが残高またはツアー代金を超えています")
        cur = conn.execute(
            "INSERT INTO bookings (member_id, tour_id, price, points_used, booked_on)"
            " VALUES (?,?,?,?,?)",
            (m["id"], tour_id, tour["price"], points_to_use, _iso(today)))
        booking_id = cur.lastrowid
        if points_to_use:
            _consume(conn, m["id"], "redeem", points_to_use,
                     f"ツアー代金に利用（{tour['name']}）", today, booking_id, operator)
    return conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()


def _restore_points(conn, booking, today, operator):
    """予約時に利用したマイルを元の付与分（元の有効期限）に戻す。"""
    usages = conn.execute(
        "SELECT u.lot_id, u.points FROM lot_usages u JOIN point_txns p ON p.id=u.txn_id"
        " WHERE p.booking_id=? AND p.kind='redeem'", (booking["id"],)).fetchall()
    total = sum(u["points"] for u in usages)
    if not total:
        return
    _add_txn(conn, booking["member_id"], "restore", total, "予約取消によるマイル返還",
             today, booking["id"], operator)
    for u in usages:
        conn.execute("UPDATE point_lots SET remaining=remaining+? WHERE id=?",
                     (u["points"], u["lot_id"]))


def cancel_booking(conn, booking_id, today, operator=""):
    with transaction(conn):
        b = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        if b is None:
            raise PointError("予約が見つかりません")
        if b["status"] != "booked":
            raise PointError("参加予定の予約のみ取り消せます")
        conn.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))
        _restore_points(conn, b, today, operator)


def cancel_tour(conn, tour_id, today, operator=""):
    """催行中止。全予約を取り消し、利用マイルを返還する。"""
    with transaction(conn):
        tour = get_tour(conn, tour_id)
        if tour["status"] != "scheduled":
            raise PointError("催行予定のツアーのみ中止できます")
        for b in conn.execute("SELECT * FROM bookings WHERE tour_id=? AND status='booked'",
                              (tour_id,)).fetchall():
            conn.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (b["id"],))
            _restore_points(conn, b, today, operator)
        conn.execute("UPDATE tours SET status='cancelled' WHERE id=?", (tour_id,))


def estimate_earn(conn, member, tour, paid_amount):
    """参加完了時に付与されるマイルの内訳を計算する。"""
    rank = rank_for(conn, member["id"], tour["depart_date"])
    base = paid_amount // rules.YEN_PER_POINT
    items = [("基本", math.floor(base * rank["multiplier"] * tour["bonus_multiplier"]))]
    if tour["bonus_points"]:
        items.append(("道ツアー特典" if tour["kind"] == "michi" else "キャンペーン加算",
                      tour["bonus_points"]))
    if member["birthdate"] and member["birthdate"][5:7] == tour["depart_date"][5:7]:
        items.append(("誕生月特典", rules.BIRTHDAY_BONUS))
    return rank, items


def complete_tour(conn, tour_id, today, operator="", absent_booking_ids=()):
    """ツアー催行完了。参加者へマイルを付与する。

    absent_booking_ids に含めた予約は不参加（マイル付与なし・利用分は返還しない）。
    """
    absent = set(absent_booking_ids)
    granted = 0
    with transaction(conn):
        tour = get_tour(conn, tour_id)
        if tour["status"] != "scheduled":
            raise PointError("催行予定のツアーのみ完了処理できます")
        if _date(tour["depart_date"]) > _date(today):
            raise PointError("出発日より前に完了処理はできません")
        bookings = conn.execute("SELECT * FROM bookings WHERE tour_id=? AND status='booked'",
                                (tour_id,)).fetchall()
        for b in bookings:
            if b["id"] in absent:
                conn.execute("UPDATE bookings SET status='no_show' WHERE id=?", (b["id"],))
                continue
            member = conn.execute("SELECT * FROM members WHERE id=?", (b["member_id"],)).fetchone()
            first_tour = not conn.execute(
                "SELECT 1 FROM bookings WHERE member_id=? AND status='completed'",
                (member["id"],)).fetchone()
            rank, items = estimate_earn(conn, member, tour, b["price"] - b["points_used"])
            conn.execute("UPDATE bookings SET status='completed' WHERE id=?", (b["id"],))
            if member["status"] != "active":
                continue
            for label, pts in items:
                kind, reason = "bonus", f"ツアー参加 {label}"
                if label == "基本":
                    detail = f"{rank['name']}×{rank['multiplier']:g}"
                    if tour["bonus_multiplier"] != 1:
                        detail += f"・キャンペーン×{tour['bonus_multiplier']:g}"
                    kind, reason = "earn", f"{reason}（{detail}）"
                if _grant(conn, member["id"], kind, pts, reason, today, b["id"], operator):
                    granted += pts
            if first_tour and member["referrer_id"]:
                ref = conn.execute("SELECT * FROM members WHERE id=?",
                                   (member["referrer_id"],)).fetchone()
                if ref["status"] == "active":
                    _grant(conn, ref["id"], "bonus", rules.REFERRAL_BONUS,
                           f"ご紹介特典（{member['name']}様 初参加）", today, operator=operator)
                    granted += rules.REFERRAL_BONUS
        conn.execute("UPDATE tours SET status='completed' WHERE id=?", (tour_id,))
    return granted


# --- 集計 -----------------------------------------------------------------

def dashboard(conn, today, horizon_days=90):
    t = _iso(today)
    soon = _iso(_date(today) + timedelta(days=horizon_days))
    q = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
    return {
        "members": q("SELECT COUNT(*) FROM members WHERE status='active'"),
        "outstanding": q("SELECT COALESCE(SUM(remaining),0) FROM point_lots WHERE expires_on >= ?", t),
        "expiring_soon": q("SELECT COALESCE(SUM(remaining),0) FROM point_lots"
                           " WHERE expires_on >= ? AND expires_on <= ?", t, soon),
        "horizon_days": horizon_days,
        "scheduled_tours": q("SELECT COUNT(*) FROM tours WHERE status='scheduled'"),
    }


# --- 設定 -----------------------------------------------------------------

TOUR_KINDS = {"normal": "通常ツアー", "michi": "道ツアー"}
CONTACT_CHANNELS = {"app": "会員ページ", "phone": "電話", "mail": "郵送"}

# 管理者が画面から変えられる値（道ツアーの既定値）。仕様が決まるまでの仮の値
MICHI_DEFAULTS = {"michi_min_tours": 3, "michi_bonus": 1000}
MICHI_WINDOW_DAYS = 365


def get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, str(value)))


def michi_settings(conn):
    return {"min_tours": int(get_setting(conn, "michi_min_tours", MICHI_DEFAULTS["michi_min_tours"])),
            "bonus": int(get_setting(conn, "michi_bonus", MICHI_DEFAULTS["michi_bonus"]))}


def update_michi_settings(conn, min_tours, bonus):
    if min_tours < 1:
        raise PointError("招待条件の参加回数は1以上にしてください")
    if bonus < 0:
        raise PointError("特典マイルは0以上にしてください")
    set_setting(conn, "michi_min_tours", min_tours)
    set_setting(conn, "michi_bonus", bonus)


# --- 道ツアー（招待制） ----------------------------------------------------------

def normal_tours_in(conn, member_id, on_date):
    """on_date までの直近1年に参加完了した通常ツアーの回数（招待条件の判定に使う）。"""
    end = _date(on_date)
    start = end - timedelta(days=MICHI_WINDOW_DAYS)
    return conn.execute(
        "SELECT COUNT(*) FROM bookings b JOIN tours t ON t.id=b.tour_id"
        " WHERE b.member_id=? AND b.status='completed' AND t.kind='normal'"
        " AND t.depart_date >= ? AND t.depart_date <= ?",
        (member_id, _iso(start), _iso(end))).fetchone()[0]


def invite_for(conn, tour_id, member_id):
    return conn.execute("SELECT * FROM invites WHERE tour_id=? AND member_id=?",
                        (tour_id, member_id)).fetchone()


def eligible_for(conn, tour, today):
    """招待条件を満たす有効会員 [(会員, 参加回数)]（回数の多い順）。"""
    out = []
    for m in conn.execute("SELECT * FROM members WHERE status='active' ORDER BY id").fetchall():
        n = normal_tours_in(conn, m["id"], today)
        if n >= tour["invite_min_tours"]:
            out.append((m, n))
    return sorted(out, key=lambda x: -x[1])


def invite_contacts(conn, invite_id):
    return [r["channel"] for r in conn.execute(
        "SELECT channel FROM invite_contacts WHERE invite_id=? ORDER BY contacted_on, rowid",
        (invite_id,))]


def invite_state(conn, inv):
    """招待の状態 {code, label}。code は none / invited / requested / booked。"""
    if inv is None:
        return {"code": "none", "label": "未招待"}
    b = conn.execute("SELECT status FROM bookings WHERE tour_id=? AND member_id=?"
                     " AND status!='cancelled'", (inv["tour_id"], inv["member_id"])).fetchone()
    if b:
        return {"code": "booked", "label": "参加済" if b["status"] == "completed" else "予約済"}
    if inv["requested_on"]:
        return {"code": "requested", "label": "参加希望"}
    ch = "・".join(CONTACT_CHANNELS[c] for c in invite_contacts(conn, inv["id"]))
    return {"code": "invited", "label": f"案内済（{ch}）" if ch else "招待済"}


def invites_of(conn, tour_id):
    return conn.execute("SELECT * FROM invites WHERE tour_id=? ORDER BY id", (tour_id,)).fetchall()


def invite_summary(conn, tour, today):
    invs = invites_of(conn, tour["id"])
    states = [invite_state(conn, i)["code"] for i in invs]
    return {"eligible": len(eligible_for(conn, tour, today)), "invited": len(invs),
            "requested": states.count("requested"), "booked": states.count("booked")}


def send_invites(conn, tour_id, today, operator=""):
    """条件を満たし、まだ招待していない会員に招待を出す（会員ページに表示される）。人数を返す。"""
    with transaction(conn):
        t = get_tour(conn, tour_id)
        if t["kind"] != "michi" or t["status"] != "scheduled":
            raise PointError("催行予定の道ツアーのみ招待できます")
        n = 0
        for m, _ in eligible_for(conn, t, today):
            if invite_for(conn, t["id"], m["id"]):
                continue
            cur = conn.execute("INSERT INTO invites (tour_id, member_id, invited_on, operator)"
                               " VALUES (?,?,?,?)", (t["id"], m["id"], _iso(today), operator))
            conn.execute("INSERT INTO invite_contacts (invite_id, channel, contacted_on, operator)"
                         " VALUES (?,?,?,?)", (cur.lastrowid, "app", _iso(today), operator))
            n += 1
    return n


def mark_contacted(conn, invite_id, channel, today, operator=""):
    """電話・郵送で案内したことを記録する。"""
    if channel not in CONTACT_CHANNELS:
        raise PointError("案内の手段が正しくありません")
    if not conn.execute("SELECT 1 FROM invites WHERE id=?", (invite_id,)).fetchone():
        raise PointError("招待が見つかりません")
    conn.execute("INSERT OR IGNORE INTO invite_contacts (invite_id, channel, contacted_on, operator)"
                 " VALUES (?,?,?,?)", (invite_id, channel, _iso(today), operator))


def request_join(conn, invite_id, member_id, today):
    """会員ページから「参加を希望する」。本人あての招待のみ受け付ける。"""
    inv = conn.execute("SELECT * FROM invites WHERE id=? AND member_id=?",
                       (invite_id, member_id)).fetchone()
    if inv is None:
        raise PointError("招待が見つかりません")
    if get_tour(conn, inv["tour_id"])["status"] != "scheduled":
        raise PointError("このツアーの受付は終了しました")
    if not inv["requested_on"]:
        conn.execute("UPDATE invites SET requested_on=? WHERE id=?", (_iso(today), invite_id))


def my_invites(conn, member_id, today):
    """会員に届いている招待（催行予定で出発前のもの、出発日が近い順）。"""
    return conn.execute(
        "SELECT i.*, t.name AS tour_name, t.depart_date, t.price, t.bonus_points FROM invites i"
        " JOIN tours t ON t.id=i.tour_id WHERE i.member_id=? AND t.status='scheduled'"
        " AND t.depart_date >= ? ORDER BY t.depart_date", (member_id, _iso(today))).fetchall()


def invite_goal(conn, member_id, today):
    """まだ招待されていない会員に「あと何回で招待」を示すための目安。"""
    row = conn.execute("SELECT MIN(invite_min_tours) FROM tours"
                       " WHERE kind='michi' AND status='scheduled'").fetchone()
    need = row[0] or michi_settings(conn)["min_tours"]
    have = normal_tours_in(conn, member_id, today)
    return {"need": need, "have": have, "left": max(0, need - have)}


# --- スタッフ -----------------------------------------------------------------

STAFF_ROLES = {"admin": "管理者", "staff": "スタッフ"}
MIN_PASSWORD = 8


def _validate_password(pw):
    if len(pw or "") < MIN_PASSWORD:
        raise PointError(f"パスワードは{MIN_PASSWORD}文字以上にしてください")


def create_staff(conn, login, name, password, role, today):
    login, name = (login or "").strip().lower(), (name or "").strip()
    if not login or not login.replace("-", "").replace("_", "").replace(".", "").isalnum() or not login.isascii():
        raise PointError("ログインIDは半角英数字（- _ . も可）で入力してください")
    if not name:
        raise PointError("氏名を入力してください")
    if role not in STAFF_ROLES:
        raise PointError("権限が正しくありません")
    _validate_password(password)
    if conn.execute("SELECT 1 FROM staff WHERE login=?", (login,)).fetchone():
        raise PointError("同じログインIDがすでに使われています")
    cur = conn.execute("INSERT INTO staff (login, name, password_hash, role, created_on)"
                       " VALUES (?,?,?,?,?)", (login, name, hash_pin(password), role, _iso(today)))
    return get_staff(conn, cur.lastrowid)


def get_staff(conn, staff_id):
    row = conn.execute("SELECT * FROM staff WHERE id=?", (staff_id,)).fetchone()
    if row is None:
        raise PointError("スタッフが見つかりません")
    return row


def list_staff(conn):
    return conn.execute("SELECT * FROM staff ORDER BY active DESC, role, id").fetchall()


def authenticate_staff(conn, login, password):
    row = conn.execute("SELECT * FROM staff WHERE login=?", ((login or "").strip().lower(),)).fetchone()
    if row is None or not row["active"] or not _verify_pin(password or "", row["password_hash"]):
        return None
    return row


def set_staff_password(conn, staff_id, password):
    """パスワードを変える。発行済みのログインはすべて無効になる。"""
    _validate_password(password)
    get_staff(conn, staff_id)
    conn.execute("UPDATE staff SET password_hash=?, session_gen=session_gen+1 WHERE id=?",
                 (hash_pin(password), staff_id))


def set_staff_active(conn, staff_id, active):
    s = get_staff(conn, staff_id)
    if not active and s["role"] == "admin" and conn.execute(
            "SELECT COUNT(*) FROM staff WHERE role='admin' AND active=1").fetchone()[0] <= 1:
        raise PointError("有効な管理者が1人もいなくなるため、停止できません")
    conn.execute("UPDATE staff SET active=?, session_gen=session_gen+1 WHERE id=?",
                 (1 if active else 0, staff_id))
