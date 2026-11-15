import sqlite3
import unittest
from datetime import date

from points import service
from points.db import connect
from points.service import PointError

D = date.fromisoformat


class MichiTest(unittest.TestCase):
    """招待制の道ツアー。"""

    def setUp(self):
        self.conn = connect(":memory:")
        self.regular = service.register_member(self.conn, "常連 一郎", "1234", D("2025-01-01"))
        self.newbie = service.register_member(self.conn, "新人 花子", "1234", D("2025-01-01"))
        for i, depart in enumerate(["2025-12-01", "2026-02-01", "2026-04-01"]):
            t = service.create_tour(self.conn, f"N{i}", f"通常{i}", D(depart), 10000)
            service.book_tour(self.conn, self.regular["member_no"], t["id"], 0, D(depart))
            service.complete_tour(self.conn, t["id"], D(depart))
        self.today = D("2026-06-01")
        self.michi = service.create_tour(self.conn, "M1", "奥入瀬 2日間", D("2026-08-01"), 89800, kind="michi")

    def test_defaults_come_from_settings(self):
        self.assertEqual(self.michi["invite_min_tours"], 3)
        self.assertEqual(self.michi["bonus_points"], 1000)
        service.update_michi_settings(self.conn, 5, 2000)
        t = service.create_tour(self.conn, "M2", "白川郷", D("2026-09-01"), 76000, kind="michi")
        self.assertEqual((t["invite_min_tours"], t["bonus_points"]), (5, 2000))
        with self.assertRaises(PointError):
            service.update_michi_settings(self.conn, 0, 100)

    def test_only_eligible_members_are_invited(self):
        self.assertEqual(service.normal_tours_in(self.conn, self.regular["id"], self.today), 3)
        self.assertEqual(service.send_invites(self.conn, self.michi["id"], self.today, "佐藤"), 1)
        self.assertEqual(service.send_invites(self.conn, self.michi["id"], self.today, "佐藤"), 0)  # 二重に送らない
        self.assertIsNotNone(service.invite_for(self.conn, self.michi["id"], self.regular["id"]))
        self.assertIsNone(service.invite_for(self.conn, self.michi["id"], self.newbie["id"]))
        goal = service.invite_goal(self.conn, self.newbie["id"], self.today)
        self.assertEqual((goal["have"], goal["left"]), (0, 3))

    def test_booking_requires_invite(self):
        with self.assertRaises(PointError):
            service.book_tour(self.conn, self.regular["member_no"], self.michi["id"], 0, self.today)
        service.send_invites(self.conn, self.michi["id"], self.today)
        service.book_tour(self.conn, self.regular["member_no"], self.michi["id"], 0, self.today)
        inv = service.invite_for(self.conn, self.michi["id"], self.regular["id"])
        self.assertEqual(service.invite_state(self.conn, inv)["code"], "booked")
        with self.assertRaises(PointError):
            service.book_tour(self.conn, self.newbie["member_no"], self.michi["id"], 0, self.today)

    def test_request_join_only_for_own_invite(self):
        service.send_invites(self.conn, self.michi["id"], self.today)
        inv = service.invite_for(self.conn, self.michi["id"], self.regular["id"])
        with self.assertRaises(PointError):
            service.request_join(self.conn, inv["id"], self.newbie["id"], self.today)
        service.request_join(self.conn, inv["id"], self.regular["id"], self.today)
        inv = service.invite_for(self.conn, self.michi["id"], self.regular["id"])
        self.assertEqual(service.invite_state(self.conn, inv)["code"], "requested")
        service.mark_contacted(self.conn, inv["id"], "phone", self.today)
        service.mark_contacted(self.conn, inv["id"], "phone", self.today)  # 二重記録しない
        self.assertEqual(service.invite_contacts(self.conn, inv["id"]), ["app", "phone"])

    def test_michi_bonus_is_granted_on_completion(self):
        service.send_invites(self.conn, self.michi["id"], self.today)
        service.book_tour(self.conn, self.regular["member_no"], self.michi["id"], 0, self.today)
        before = service.balance(self.conn, self.regular["id"], D("2026-08-01"))
        service.complete_tour(self.conn, self.michi["id"], D("2026-08-01"))
        gained = service.balance(self.conn, self.regular["id"], D("2026-08-01")) - before
        # 基本 898pt × シルバー1.5倍 = 1347pt ＋ 道ツアー特典 1000pt
        self.assertEqual(gained, 1347 + 1000)
        reasons = [r["reason"] for r in service.history(self.conn, self.regular["id"])]
        self.assertIn("ツアー参加 道ツアー特典", reasons)

    def test_michi_tours_do_not_count_toward_invites(self):
        service.send_invites(self.conn, self.michi["id"], self.today)
        service.book_tour(self.conn, self.regular["member_no"], self.michi["id"], 0, self.today)
        service.complete_tour(self.conn, self.michi["id"], D("2026-08-01"))
        self.assertEqual(service.normal_tours_in(self.conn, self.regular["id"], D("2026-08-02")), 3)


class StaffTest(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        self.admin = service.create_staff(self.conn, "Admin", "管理 太郎", "password1", "admin", D("2026-01-01"))

    def test_login_and_password(self):
        self.assertEqual(self.admin["login"], "admin")
        self.assertIsNotNone(service.authenticate_staff(self.conn, "ADMIN", "password1"))
        self.assertIsNone(service.authenticate_staff(self.conn, "admin", "wrong-pass"))
        service.set_staff_password(self.conn, self.admin["id"], "password2")
        self.assertIsNone(service.authenticate_staff(self.conn, "admin", "password1"))
        self.assertEqual(service.get_staff(self.conn, self.admin["id"])["session_gen"], 1)
        with self.assertRaises(PointError):
            service.set_staff_password(self.conn, self.admin["id"], "short")

    def test_validation(self):
        with self.assertRaises(PointError):
            service.create_staff(self.conn, "admin", "重複", "password1", "staff", D("2026-01-01"))
        with self.assertRaises(PointError):
            service.create_staff(self.conn, "山田", "日本語ID", "password1", "staff", D("2026-01-01"))
        with self.assertRaises(PointError):
            service.create_staff(self.conn, "x", "x", "password1", "owner", D("2026-01-01"))

    def test_cannot_disable_last_admin(self):
        with self.assertRaises(PointError):
            service.set_staff_active(self.conn, self.admin["id"], False)
        s = service.create_staff(self.conn, "suzuki", "鈴木", "password1", "staff", D("2026-01-01"))
        service.set_staff_active(self.conn, s["id"], False)
        self.assertIsNone(service.authenticate_staff(self.conn, "suzuki", "password1"))


class MigrationTest(unittest.TestCase):
    def test_old_database_gets_new_columns(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "old.sqlite3")
            old = sqlite3.connect(path)
            old.executescript("""CREATE TABLE tours (id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL, depart_date TEXT NOT NULL, price INTEGER NOT NULL,
                bonus_multiplier REAL NOT NULL DEFAULT 1.0, bonus_points INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'scheduled');
                INSERT INTO tours (code, name, depart_date, price) VALUES ('OLD', '旧ツアー', '2026-01-01', 5000);""")
            old.commit()
            old.close()
            conn = connect(path)
            t = conn.execute("SELECT * FROM tours WHERE code='OLD'").fetchone()
            self.assertEqual(t["kind"], "normal")
            conn.close()


if __name__ == "__main__":
    unittest.main()
