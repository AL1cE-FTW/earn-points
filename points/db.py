"""SQLite によるデータ保存。外部DBサーバやクラウドサービスは使用しない。"""

import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS members (
    id          INTEGER PRIMARY KEY,
    member_no   TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    kana        TEXT NOT NULL DEFAULT '',
    phone       TEXT NOT NULL DEFAULT '',
    email       TEXT NOT NULL DEFAULT '',
    birthdate   TEXT,               -- YYYY-MM-DD
    pin_hash    TEXT NOT NULL,      -- 会員ページ用暗証番号（PBKDF2）
    referrer_id INTEGER REFERENCES members(id),
    status      TEXT NOT NULL DEFAULT 'active',  -- active / withdrawn
    joined_on   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tours (
    id               INTEGER PRIMARY KEY,
    code             TEXT NOT NULL UNIQUE,
    name             TEXT NOT NULL,
    depart_date      TEXT NOT NULL,
    price            INTEGER NOT NULL,           -- 税込1名あたり代金（円）
    bonus_multiplier REAL NOT NULL DEFAULT 1.0,  -- キャンペーン倍率
    bonus_points     INTEGER NOT NULL DEFAULT 0, -- キャンペーン加算ポイント
    status           TEXT NOT NULL DEFAULT 'scheduled'  -- scheduled / completed / cancelled
);

CREATE TABLE IF NOT EXISTS bookings (
    id          INTEGER PRIMARY KEY,
    member_id   INTEGER NOT NULL REFERENCES members(id),
    tour_id     INTEGER NOT NULL REFERENCES tours(id),
    price       INTEGER NOT NULL,
    points_used INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'booked',  -- booked / completed / no_show / cancelled
    booked_on   TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS bookings_active_uniq
    ON bookings(member_id, tour_id) WHERE status != 'cancelled';

-- ポイント取引台帳（増減はすべてここに記録する）
CREATE TABLE IF NOT EXISTS point_txns (
    id         INTEGER PRIMARY KEY,
    member_id  INTEGER NOT NULL REFERENCES members(id),
    kind       TEXT NOT NULL,     -- earn / bonus / redeem / restore / expire / adjust / forfeit
    points     INTEGER NOT NULL,  -- 増加は正、減少は負
    reason     TEXT NOT NULL,
    booking_id INTEGER REFERENCES bookings(id),
    created_on TEXT NOT NULL,
    operator   TEXT NOT NULL DEFAULT ''
);

-- 有効期限管理のため付与単位で残高を持つ（先に期限が来るものから消費）
CREATE TABLE IF NOT EXISTS point_lots (
    id         INTEGER PRIMARY KEY,
    member_id  INTEGER NOT NULL REFERENCES members(id),
    txn_id     INTEGER NOT NULL REFERENCES point_txns(id),
    amount     INTEGER NOT NULL,
    remaining  INTEGER NOT NULL,
    granted_on TEXT NOT NULL,
    expires_on TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS point_lots_member ON point_lots(member_id, expires_on);

-- どの付与分を何ポイント消費したか（キャンセル時の返還に使う）
CREATE TABLE IF NOT EXISTS lot_usages (
    txn_id INTEGER NOT NULL REFERENCES point_txns(id),
    lot_id INTEGER NOT NULL REFERENCES point_lots(id),
    points INTEGER NOT NULL
);
"""


def connect(path):
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def transaction(conn):
    """書き込みロックを先に取り、残高計算と更新の間に割り込みが入らないようにする。"""
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
