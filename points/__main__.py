"""コマンドライン入口。

  python -m points serve [--db FILE] [--host H] [--port P]   画面を起動
  python -m points expire [--db FILE]                       期限切れポイントを失効（日次でcron等から実行）
  python -m points passwd [--db FILE]                       スタッフ用管理パスワードを変更
  python -m points demo [--db FILE]                         動作確認用のサンプルデータを投入
"""

import argparse
import getpass
import os
import sys
from datetime import date, timedelta

from . import service
from .db import connect
from .web import App, serve


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m points", description="バスツアー会員ポイント制度")
    p.add_argument("command", choices=["serve", "expire", "passwd", "demo"])
    p.add_argument("--db", default=os.environ.get("POINTS_DB", "points.sqlite3"))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    a = p.parse_args(argv)

    if a.command == "serve":
        serve(a.db, a.host, a.port, os.environ.get("POINTS_ADMIN_PASSWORD"))
    elif a.command == "expire":
        n = service.expire_points(connect(a.db), date.today())
        print(f"{n}ポイントを失効させました")
    elif a.command == "passwd":
        pw = getpass.getpass("新しい管理パスワード: ")
        if len(pw) < 8 or pw != getpass.getpass("確認のため再入力: "):
            sys.exit("8文字以上で、2回同じものを入力してください")
        App(a.db, admin_password=pw)
        print("変更しました")
    elif a.command == "demo":
        seed_demo(connect(a.db))


def seed_demo(conn):
    today = date.today()
    past = today - timedelta(days=30)
    hanako = service.register_member(conn, "山田 花子", "1234", past - timedelta(days=200),
                                     kana="ヤマダ ハナコ", birthdate=f"1960-{past.month:02d}-15")
    taro = service.register_member(conn, "鈴木 太郎", "5678", past - timedelta(days=100),
                                   kana="スズキ タロウ", referrer_no=hanako["member_no"])
    t1 = service.create_tour(conn, "DEMO-01", "紅葉の日光・鬼怒川 日帰りバスツアー", past, 12800)
    service.book_tour(conn, hanako["member_no"], t1["id"], 0, past - timedelta(days=20))
    service.book_tour(conn, taro["member_no"], t1["id"], 300, past - timedelta(days=20))
    service.complete_tour(conn, t1["id"], past)
    t2 = service.create_tour(conn, "DEMO-02", "冬の味覚 カニ食べ放題ツアー（ポイント2倍）",
                             today + timedelta(days=40), 15800, bonus_multiplier=2)
    service.book_tour(conn, hanako["member_no"], t2["id"], 500, today)
    print("サンプル会員を登録しました（会員番号 / 暗証番号）")
    print(f"  {hanako['member_no']} / 1234  山田 花子")
    print(f"  {taro['member_no']} / 5678  鈴木 太郎")


if __name__ == "__main__":
    main()
