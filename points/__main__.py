"""コマンドライン入口。

  python -m points serve [--db FILE] [--host H] [--port P] [--https]   サーバを起動
  python -m points expire [--db FILE]                     期限切れポイントを失効（毎日 cron などから実行）
  python -m points backup FILE [--db FILE]                動かしたままデータベースを FILE にバックアップ
  python -m points staff-password LOGIN [--db FILE]       スタッフのパスワードを再設定（管理者がログインできないとき用）
  python -m points demo [--db FILE]                       動作確認用のサンプルデータを投入

--https は、HTTPS のリバースプロキシの後ろで動かすときに付ける（クッキーに Secure を付ける）。
環境変数 POINTS_DB / POINTS_HTTPS=1 / POINTS_ADMIN_PASSWORD でも指定できる。
"""

import argparse
import getpass
import os
import sqlite3
import sys
from datetime import date, timedelta

from . import service
from .db import connect
from .web import serve


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m points", description="バスツアー会員ポイント制度（サービス版）")
    p.add_argument("command", choices=["serve", "expire", "backup", "staff-password", "demo"])
    p.add_argument("arg", nargs="?", help="backup の保存先 / staff-password のログインID")
    p.add_argument("--db", default=os.environ.get("POINTS_DB", "points.sqlite3"))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--https", action="store_true", default=os.environ.get("POINTS_HTTPS") == "1")
    a = p.parse_args(argv)

    if a.command == "serve":
        serve(a.db, a.host, a.port, os.environ.get("POINTS_ADMIN_PASSWORD"), secure_cookies=a.https)
    elif a.command == "expire":
        n = service.expire_points(connect(a.db), date.today())
        print(f"{n}ポイントを失効させました")
    elif a.command == "backup":
        if not a.arg:
            sys.exit("保存先のファイル名を指定してください（例: python -m points backup backup-2026-11-15.sqlite3）")
        src = connect(a.db)
        dst = sqlite3.connect(a.arg)
        src.backup(dst)
        dst.close()
        print(f"{a.arg} にバックアップしました")
    elif a.command == "staff-password":
        if not a.arg:
            sys.exit("ログインIDを指定してください")
        conn = connect(a.db)
        row = conn.execute("SELECT * FROM staff WHERE login=?", (a.arg.lower(),)).fetchone()
        if row is None:
            sys.exit("そのログインIDのスタッフはいません")
        pw = getpass.getpass("新しいパスワード: ")
        if pw != getpass.getpass("確認のため再入力: "):
            sys.exit("2回の入力が一致しません")
        try:
            service.set_staff_password(conn, row["id"], pw)
            if not row["active"]:
                service.set_staff_active(conn, row["id"], True)
        except service.PointError as e:
            sys.exit(str(e))
        print("再設定しました")
    elif a.command == "demo":
        seed_demo(connect(a.db))


def seed_demo(conn, today=None):
    """画面デモと同じサンプル会員・ツアー（道ツアー入り）を入れる。"""
    today = today or date.today()
    back = lambda n: today - timedelta(days=n)
    reg = lambda name, kana, phone, pin, joined, **kw: service.register_member(
        conn, name, pin, back(joined), kana=kana, phone=phone, operator="サンプル", **kw)
    hanako = reg("山田 花子", "ヤマダ ハナコ", "090-1234-5678", "1234", 230, birthdate=f"1958-{back(30).month:02d}-15")
    taro = reg("鈴木 太郎", "スズキ タロウ", "080-2222-3333", "5678", 130, referrer_no=hanako["member_no"])
    ichiro = reg("佐藤 一郎", "サトウ イチロウ", "070-4444-5555", "2468", 420, birthdate="1951-02-03")
    kazuko = reg("田中 和子", "タナカ カズコ", "090-7777-8888", "1357", 200, birthdate="1955-06-21")
    S = "サンプル"
    for code, name, ago, price in [("2025-H01", "初夏の富士五湖めぐり", 330, 9800), ("2025-H02", "上高地ハイキング日帰り", 270, 11800),
                                   ("2025-H03", "秋の京都 紅葉ライトアップ", 210, 19800), ("2025-H04", "いちご狩りと温泉の旅", 150, 8900),
                                   ("2025-H05", "河津桜と伊豆の海鮮", 90, 10800), ("2025-H06", "しだれ桜の名所めぐり", 60, 9800)]:
        t = service.create_tour(conn, code, name, back(ago), price)
        service.book_tour(conn, ichiro["member_no"], t["id"], 0, back(ago + 14), S)
        if ago <= 150:
            service.book_tour(conn, kazuko["member_no"], t["id"], 0, back(ago + 14), S)
        service.complete_tour(conn, t["id"], back(ago), S)
    t1 = service.create_tour(conn, "2026-NIKKO", "紅葉の日光・鬼怒川 日帰りバスツアー", back(30), 12800)
    service.book_tour(conn, hanako["member_no"], t1["id"], 0, back(50), S)
    service.book_tour(conn, taro["member_no"], t1["id"], 300, back(50), S)
    service.book_tour(conn, ichiro["member_no"], t1["id"], 1000, back(50), S)
    service.complete_tour(conn, t1["id"], back(30), S)
    t2 = service.create_tour(conn, "2026-KANI", "冬の味覚 カニ食べ放題ツアー（ポイント2倍）", today + timedelta(days=40), 15800, bonus_multiplier=2)
    service.book_tour(conn, hanako["member_no"], t2["id"], 500, today, S)
    service.book_tour(conn, ichiro["member_no"], t2["id"], 0, today, S)
    service.create_tour(conn, "2026-HAKONE", "箱根 彫刻の森と芦ノ湖遊覧", today + timedelta(days=18), 9800, bonus_points=100)
    m1 = service.create_tour(conn, "MICHI-OIRASE", "奥入瀬渓流と十和田湖 2日間", today + timedelta(days=55), 89800, kind="michi")
    service.send_invites(conn, m1["id"], back(6), S)
    service.mark_contacted(conn, service.invite_for(conn, m1["id"], kazuko["id"])["id"], "phone", back(4), S)
    service.book_tour(conn, ichiro["member_no"], m1["id"], 0, back(3), S)
    service.request_join(conn, service.invite_for(conn, m1["id"], kazuko["id"])["id"], kazuko["id"], back(2))
    service.create_tour(conn, "MICHI-SHIRAKAWA", "冬の白川郷ライトアップと飛騨の宿 2日間", today + timedelta(days=96), 76000, kind="michi")
    print("サンプル会員を登録しました（会員番号 / 暗証番号）")
    for m, pin in [(hanako, "1234"), (taro, "5678"), (ichiro, "2468"), (kazuko, "1357")]:
        print(f"  {m['member_no']} / {pin}  {m['name']}")


if __name__ == "__main__":
    main()
