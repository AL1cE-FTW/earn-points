"""ポイント制度の業務ロジック（入会・付与・利用・取消・失効・退会）。"""

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
        birthdate = _iso(_date(birthdate))
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
    conn.execute("UPDATE members SET pin_hash=? WHERE id=?", (hash_pin(new_pin), m["id"]))


def search_members(conn, query, limit=50):
    q = f"%{query.strip()}%"
    return conn.execute(
        "SELECT * FROM members WHERE member_no LIKE ? OR name LIKE ? OR kana LIKE ?"
        " OR phone LIKE ? OR email LIKE ? ORDER BY id DESC LIMIT ?",
        (q, q, q, q, q, limit)).fetchall()


def withdraw_member(conn, member_no, today, operator=""):
    """退会。保有ポイントはすべて失効する。"""
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


# --- ランク -----------------------------------------------------------------

def rank_for(conn, member_id, on_date):
    """on_date より前の365日間に参加完了したツアー数でランクを決める。"""
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
    """有効期限ごとの残ポイント（期限が近い順）。"""
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
        raise PointError("ポイント残高が不足しています")
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
        raise PointError("調整ポイントを入力してください")
    with transaction(conn):
        m = get_member(conn, member_no)
        if m["status"] != "active":
            raise PointError("退会済み会員のポイントは調整できません")
        if points > 0:
            _grant(conn, m["id"], "adjust", points, reason, today, operator=operator)
        else:
            _consume(conn, m["id"], "adjust", -points, reason, today, operator=operator)


def expire_points(conn, today):
    """有効期限を過ぎたポイントを失効させ、台帳に記録する。失効ポイント合計を返す。"""
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

def create_tour(conn, code, name, depart_date, price, bonus_multiplier=1.0, bonus_points=0):
    code, name = (code or "").strip(), (name or "").strip()
    if not code or not name:
        raise PointError("ツアーコードとツアー名は必須です")
    if price <= 0:
        raise PointError("代金は1円以上で入力してください")
    if bonus_multiplier < 1 or bonus_points < 0:
        raise PointError("キャンペーン倍率は1以上、加算ポイントは0以上で入力してください")
    if conn.execute("SELECT 1 FROM tours WHERE code=?", (code,)).fetchone():
        raise PointError("同じツアーコードがすでに登録されています")
    cur = conn.execute(
        "INSERT INTO tours (code, name, depart_date, price, bonus_multiplier, bonus_points)"
        " VALUES (?,?,?,?,?,?)",
        (code, name, _iso(_date(depart_date)), price, bonus_multiplier, bonus_points))
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
    """ツアー予約を登録し、指定があればポイントを代金に充当する。"""
    with transaction(conn):
        m = get_member(conn, member_no)
        if m["status"] != "active":
            raise PointError("退会済みの会員です")
        tour = get_tour(conn, tour_id)
        if tour["status"] != "scheduled":
            raise PointError("このツアーは予約を受け付けていません")
        if conn.execute("SELECT 1 FROM bookings WHERE member_id=? AND tour_id=?"
                        " AND status!='cancelled'", (m["id"], tour_id)).fetchone():
            raise PointError("この会員はすでにこのツアーを予約しています")
        if points_to_use < 0 or points_to_use % rules.REDEEM_UNIT:
            raise PointError(f"ポイントは{rules.REDEEM_UNIT}ポイント単位でご利用いただけます")
        if points_to_use > max_redeemable(conn, m["id"], tour["price"], today):
            raise PointError("利用ポイントが残高またはツアー代金を超えています")
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
    """予約時に利用したポイントを元の付与分（元の有効期限）に戻す。"""
    usages = conn.execute(
        "SELECT u.lot_id, u.points FROM lot_usages u JOIN point_txns p ON p.id=u.txn_id"
        " WHERE p.booking_id=? AND p.kind='redeem'", (booking["id"],)).fetchall()
    total = sum(u["points"] for u in usages)
    if not total:
        return
    _add_txn(conn, booking["member_id"], "restore", total, "予約取消によるポイント返還",
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
    """催行中止。全予約を取り消し、利用ポイントを返還する。"""
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
    """参加完了時に付与されるポイントの内訳を計算する。"""
    rank = rank_for(conn, member["id"], tour["depart_date"])
    base = paid_amount // rules.YEN_PER_POINT
    items = [("基本", math.floor(base * rank["multiplier"] * tour["bonus_multiplier"]))]
    if tour["bonus_points"]:
        items.append(("キャンペーン加算", tour["bonus_points"]))
    if member["birthdate"] and member["birthdate"][5:7] == tour["depart_date"][5:7]:
        items.append(("誕生月特典", rules.BIRTHDAY_BONUS))
    return rank, items


def complete_tour(conn, tour_id, today, operator="", absent_booking_ids=()):
    """ツアー催行完了。参加者へポイントを付与する。

    absent_booking_ids に含めた予約は不参加（ポイント付与なし・利用分は返還しない）。
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
