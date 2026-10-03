import unittest
from datetime import date

from points import rules, service
from points.db import connect
from points.service import PointError

D = date.fromisoformat


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")

    def member(self, name="山田 花子", today="2026-01-10", **kw):
        return service.register_member(self.conn, name, "1234", D(today), **kw)

    def bal(self, m, today="2026-06-01"):
        return service.balance(self.conn, m["id"], D(today))

    def tour(self, code, depart, price=10000, **kw):
        return service.create_tour(self.conn, code, f"ツアー{code}", D(depart), price, **kw)

    def join(self, m, code, depart, price=10000, points=0, **kw):
        t = self.tour(code, depart, price, **kw)
        service.book_tour(self.conn, m["member_no"], t["id"], points, D(depart))
        return t

    def test_member_no_has_check_digit(self):
        m = self.member()
        self.assertRegex(m["member_no"], r"^BT\d{8}$")
        self.assertEqual(service.normalize_member_no(m["member_no"].lower()), m["member_no"])
        broken = m["member_no"][:-1] + str((int(m["member_no"][-1]) + 1) % 10)
        with self.assertRaises(PointError):
            service.normalize_member_no(broken)

    def test_welcome_bonus_and_pin(self):
        m = self.member()
        self.assertEqual(self.bal(m), rules.WELCOME_BONUS)
        self.assertIsNotNone(service.authenticate_member(self.conn, m["member_no"], "1234"))
        self.assertIsNone(service.authenticate_member(self.conn, m["member_no"], "9999"))
        with self.assertRaises(PointError):
            service.register_member(self.conn, "x", "12", D("2026-01-01"))

    def test_expiry_is_end_of_month_two_years_later(self):
        self.assertEqual(service.expiry_date(D("2026-10-02")), D("2028-10-31"))
        self.assertEqual(service.expiry_date(D("2026-02-28")), D("2028-02-29"))

    def test_earn_base_points_on_paid_amount(self):
        m = self.member(birthdate="1960-12-01")
        t = self.join(m, "A", "2026-03-01", price=12800, points=300)
        n = service.complete_tour(self.conn, t["id"], D("2026-03-01"))
        self.assertEqual(n, (12800 - 300) // 100)  # 125pt
        self.assertEqual(self.bal(m), rules.WELCOME_BONUS - 300 + 125)

    def test_cannot_complete_before_departure(self):
        m = self.member()
        t = self.join(m, "A", "2026-03-01")
        with self.assertRaises(PointError):
            service.complete_tour(self.conn, t["id"], D("2026-02-28"))

    def test_rank_multiplier_and_campaign(self):
        m = self.member()
        for i in range(3):
            t = self.join(m, f"R{i}", f"2026-0{i + 2}-01")
            service.complete_tour(self.conn, t["id"], D(f"2026-0{i + 2}-01"))
        rank = service.rank_for(self.conn, m["id"], D("2026-05-01"))
        self.assertEqual(rank["code"], "silver")
        t = self.join(m, "C", "2026-05-01", price=10000, bonus_multiplier=2, bonus_points=50)
        n = service.complete_tour(self.conn, t["id"], D("2026-05-01"))
        self.assertEqual(n, int(100 * 1.5 * 2) + 50)

    def test_rank_window_is_one_year(self):
        m = self.member(today="2024-01-01")
        for i in range(6):
            t = self.join(m, f"R{i}", f"2024-0{i + 2}-01")
            service.complete_tour(self.conn, t["id"], D(f"2024-0{i + 2}-01"))
        self.assertEqual(service.rank_for(self.conn, m["id"], D("2024-08-01"))["code"], "gold")
        self.assertEqual(service.rank_for(self.conn, m["id"], D("2025-06-15"))["code"], "regular")

    def test_birthday_bonus(self):
        m = self.member(birthdate="1955-04-20")
        t = self.join(m, "B", "2026-04-05")
        n = service.complete_tour(self.conn, t["id"], D("2026-04-06"))
        self.assertEqual(n, 100 + rules.BIRTHDAY_BONUS)

    def test_referral_bonus_only_on_first_tour(self):
        ref = self.member("紹介者")
        new = self.member("新規", referrer_no=ref["member_no"])
        for i, d in enumerate(["2026-02-01", "2026-03-01"]):
            t = self.join(new, f"F{i}", d)
            service.complete_tour(self.conn, t["id"], D(d))
        self.assertEqual(self.bal(ref), rules.WELCOME_BONUS + rules.REFERRAL_BONUS)

    def test_redeem_rules(self):
        m = self.member()
        t = self.tour("X", "2026-05-01", price=10000)
        with self.assertRaises(PointError):  # 単位外
            service.book_tour(self.conn, m["member_no"], t["id"], 150, D("2026-04-01"))
        with self.assertRaises(PointError):  # 残高超過
            service.book_tour(self.conn, m["member_no"], t["id"], 400, D("2026-04-01"))
        service.book_tour(self.conn, m["member_no"], t["id"], 300, D("2026-04-01"))
        self.assertEqual(self.bal(m), 0)
        with self.assertRaises(PointError):  # 二重予約
            service.book_tour(self.conn, m["member_no"], t["id"], 0, D("2026-04-01"))

    def test_redeem_cannot_exceed_price(self):
        m = self.member()
        service.adjust_points(self.conn, m["member_no"], 5000, "テスト", D("2026-01-10"))
        t = self.tour("S", "2026-05-01", price=1000)
        self.assertEqual(service.max_redeemable(self.conn, m["id"], 1000, D("2026-04-01")), 1000)
        with self.assertRaises(PointError):
            service.book_tour(self.conn, m["member_no"], t["id"], 1100, D("2026-04-01"))

    def test_fifo_consumption_and_restore_on_cancel(self):
        m = self.member(today="2025-01-10")              # 300pt 期限 2027-01-31
        service.adjust_points(self.conn, m["member_no"], 500, "付与", D("2026-01-10"))  # 期限 2028-01-31
        t = self.tour("Y", "2026-12-01")
        b = service.book_tour(self.conn, m["member_no"], t["id"], 400, D("2026-06-01"))
        sched = service.expiring_schedule(self.conn, m["id"], D("2026-06-01"))
        self.assertEqual([(r["expires_on"], r["points"]) for r in sched], [("2028-01-31", 400)])
        service.cancel_booking(self.conn, b["id"], D("2026-07-01"))
        sched = service.expiring_schedule(self.conn, m["id"], D("2026-07-01"))
        self.assertEqual([(r["expires_on"], r["points"]) for r in sched],
                         [("2027-01-31", 300), ("2028-01-31", 500)])

    def test_tour_cancel_restores_and_no_points(self):
        m = self.member()
        t = self.join(m, "Z", "2026-05-01", points=300)
        service.cancel_tour(self.conn, t["id"], D("2026-04-20"))
        self.assertEqual(self.bal(m), 300)
        with self.assertRaises(PointError):
            service.complete_tour(self.conn, t["id"], D("2026-05-01"))

    def test_no_show_gets_no_points(self):
        a, b = self.member("A"), self.member("B")
        t = self.tour("N", "2026-05-01")
        service.book_tour(self.conn, a["member_no"], t["id"], 0, D("2026-04-01"))
        bb = service.book_tour(self.conn, b["member_no"], t["id"], 0, D("2026-04-01"))
        service.complete_tour(self.conn, t["id"], D("2026-05-01"), absent_booking_ids=[bb["id"]])
        self.assertEqual(self.bal(a), 400)
        self.assertEqual(self.bal(b), 300)

    def test_expiration(self):
        m = self.member(today="2024-01-10")  # 期限 2026-01-31
        self.assertEqual(self.bal(m, "2026-01-31"), 300)
        self.assertEqual(self.bal(m, "2026-02-01"), 0)
        self.assertEqual(service.expire_points(self.conn, D("2026-02-01")), 300)
        self.assertEqual(service.expire_points(self.conn, D("2026-02-01")), 0)
        kinds = [r["kind"] for r in service.history(self.conn, m["id"])]
        self.assertEqual(kinds, ["expire", "bonus"])

    def test_ledger_always_matches_lots(self):
        m = self.member(today="2024-01-10")
        t = self.join(m, "L", "2024-03-01", points=200)
        service.complete_tour(self.conn, t["id"], D("2024-03-01"))
        service.adjust_points(self.conn, m["member_no"], -50, "訂正", D("2024-04-01"))
        service.expire_points(self.conn, D("2027-01-01"))
        ledger = self.conn.execute("SELECT SUM(points) FROM point_txns WHERE member_id=?",
                                   (m["id"],)).fetchone()[0]
        lots = self.conn.execute("SELECT SUM(remaining) FROM point_lots WHERE member_id=?",
                                 (m["id"],)).fetchone()[0]
        self.assertEqual(ledger, lots)
        self.assertEqual(lots, 0)

    def test_adjust_requires_reason_and_balance(self):
        m = self.member()
        with self.assertRaises(PointError):
            service.adjust_points(self.conn, m["member_no"], 100, " ", D("2026-02-01"))
        with self.assertRaises(PointError):
            service.adjust_points(self.conn, m["member_no"], -301, "訂正", D("2026-02-01"))

    def test_withdraw_forfeits_points(self):
        m = self.member()
        t = self.join(m, "W", "2026-05-01")
        with self.assertRaises(PointError):  # 予約中は退会不可
            service.withdraw_member(self.conn, m["member_no"], D("2026-04-01"))
        service.cancel_booking(self.conn, 1, D("2026-04-01"))
        service.withdraw_member(self.conn, m["member_no"], D("2026-04-01"))
        self.assertEqual(self.bal(m), 0)
        self.assertIsNone(service.authenticate_member(self.conn, m["member_no"], "1234"))
        with self.assertRaises(PointError):
            service.book_tour(self.conn, m["member_no"], t["id"], 0, D("2026-04-02"))


if __name__ == "__main__":
    unittest.main()
