import json
import re
import unittest
from datetime import date
from urllib.parse import unquote

from points import service
from points.web import App

FETCH = {"X-Requested-With": "fetch"}


class Client:
    """クッキーを覚えておく簡単なブラウザ代わり。"""

    def __init__(self, app):
        self.app = app
        self.jar = {}

    def req(self, method, path, form=None, headers=None):
        cookie = "; ".join(f"{k}={v}" for k, v in self.jar.items())
        status, hdrs, body = self.app.handle(method, path, form, cookie, headers)
        for k, v in hdrs:
            if k == "Set-Cookie":
                name, _, rest = v.partition("=")
                value = rest.split(";")[0]
                if value:
                    self.jar[name] = value
                else:
                    self.jar.pop(name, None)
        return status, unquote(dict(hdrs).get("Location", "")), body

    def api(self, method, path, data=None):
        status, _, body = self.req(method, path, data, FETCH)
        return status, json.loads(body)


class StaffWebTest(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 10, 2)
        self.app = App(":memory:", today=lambda: self.today, admin_password="staff-pass")
        self.c = Client(self.app)

    def login(self, c=None, login="admin", pw="staff-pass"):
        c = c or self.c
        status, loc, _ = c.req("POST", "/admin/login", {"login": login, "password": pw})
        self.assertEqual((status, loc), (303, "/admin"))
        _, _, body = c.req("GET", "/admin")
        return re.search(r'name="csrf" value="([0-9a-f]+)"', body).group(1)

    def post(self, path, form, token):
        return self.c.req("POST", path, dict(form, csrf=token))

    def test_requires_login(self):
        self.assertEqual(self.c.req("GET", "/admin")[1], "/admin/login")
        _, loc, _ = self.c.req("POST", "/admin/login", {"login": "admin", "password": "x"})
        self.assertIn("正しくありません", loc)

    def test_forged_cookie_rejected(self):
        self.c.jar["staff"] = "eyJzaWQiOiAxfQ.deadbeef"
        self.assertEqual(self.c.req("GET", "/admin")[1], "/admin/login")

    def test_post_without_csrf_is_rejected(self):
        self.login()
        status, _, _ = self.c.req("POST", "/admin/members/new", {"name": "x", "pin": "1234"})
        self.assertEqual(status, 403)
        self.assertEqual(self.app.conn.execute("SELECT COUNT(*) FROM members").fetchone()[0], 0)

    def test_full_flow_records_staff_name(self):
        token = self.login()
        _, loc, _ = self.post("/admin/members/new", {"name": "<b>山田</b>", "pin": "2468", "birthdate": "1950-10-05"}, token)
        member_no = re.search(r"BT\d{8}", loc).group(0)
        _, _, body = self.c.req("GET", f"/admin/members/{member_no}")
        self.assertIn("&lt;b&gt;山田&lt;/b&gt;", body)
        self.assertNotIn("<b>山田</b>", body)

        _, loc, _ = self.post("/admin/tours", {"code": "T1", "name": "箱根", "depart_date": "2026-10-02", "price": "9,800", "kind": "normal"}, token)
        tour_path = loc.split("?")[0]
        _, loc, _ = self.post(tour_path + "/book", {"member_no": member_no, "points": "150"}, token)
        self.assertIn("100ポイント単位", loc)
        self.post(tour_path + "/book", {"member_no": member_no, "points": "300"}, token)
        _, loc, _ = self.post(tour_path + "/complete", {"absent_list": []}, token)
        self.assertIn("295pt を付与", loc)  # (9800-300)//100=95 + 誕生月200
        ops = {r[0] for r in self.app.conn.execute("SELECT operator FROM point_txns WHERE kind!='bonus' OR reason!='入会特典'")}
        self.assertIn("管理者", ops)

    def test_staff_role_cannot_manage_staff(self):
        token = self.login()
        self.post("/admin/staff", {"login": "suzuki", "name": "鈴木", "password": "password1", "role": "staff"}, token)
        c2 = Client(self.app)
        t2 = self.login(c2, "suzuki", "password1")
        _, _, body = c2.req("GET", "/admin/staff")
        self.assertIn("管理者だけ", body)
        c2.req("POST", "/admin/staff", {"login": "x", "name": "x", "password": "password1", "role": "admin", "csrf": t2})
        self.assertIsNone(self.app.conn.execute("SELECT 1 FROM staff WHERE login='x'").fetchone())

    def test_disabled_staff_is_logged_out(self):
        token = self.login()
        self.post("/admin/staff", {"login": "suzuki", "name": "鈴木", "password": "password1", "role": "staff"}, token)
        c2 = Client(self.app)
        self.login(c2, "suzuki", "password1")
        sid = self.app.conn.execute("SELECT id FROM staff WHERE login='suzuki'").fetchone()[0]
        self.post(f"/admin/staff/{sid}/active", {"active": "0"}, token)
        self.assertEqual(c2.req("GET", "/admin")[1], "/admin/login")

    def test_staff_lockout(self):
        for _ in range(5):
            self.c.req("POST", "/admin/login", {"login": "admin", "password": "wrong"})
        _, loc, _ = self.c.req("POST", "/admin/login", {"login": "admin", "password": "staff-pass"})
        self.assertIn("15分間", loc)

    def test_michi_invite_via_web(self):
        token = self.login()
        _, loc, _ = self.post("/admin/tours", {"code": "M1", "name": "奥入瀬", "depart_date": "2026-12-01", "price": "89800",
                                               "kind": "michi", "invite_min_tours": "0"}, token)
        self.assertIn("1以上", loc)
        _, loc, _ = self.post("/admin/tours", {"code": "M1", "name": "奥入瀬", "depart_date": "2026-12-01", "price": "89800",
                                               "kind": "michi", "invite_min_tours": "3"}, token)
        _, _, body = self.c.req("GET", loc.split("?")[0])
        self.assertIn("招待を送る対象はいません", body)
        self.assertIn("道ツアー特典 <b>+1,000pt</b>", body)

    def test_public_pages(self):
        status, _, body = self.app.handle("GET", "/rules")
        self.assertEqual(status, 200)
        self.assertIn("100円ごとに1ポイント", body)
        self.assertNotRegex(body, r"(src|href)=['\"]https?://")  # 外部リソースを読み込まない
        self.assertEqual(self.app.handle("GET", "/")[1][0], ("Location", "/app/"))
        status, hdrs, _ = self.app.handle("GET", "/app/manifest.webmanifest")
        self.assertEqual((status, dict(hdrs)["Content-Type"]), (200, "application/manifest+json"))
        self.assertEqual(self.app.handle("GET", "/static/../web.py")[0], 404)


class MemberApiTest(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 10, 2)
        self.app = App(":memory:", today=lambda: self.today, admin_password="staff-pass")
        self.m = service.register_member(self.app.conn, "山田 花子", "1234", self.today)
        self.c = Client(self.app)

    def test_login_and_summary(self):
        status, body = self.c.api("GET", "/api/me")
        self.assertEqual(status, 401)
        status, body = self.c.api("POST", "/api/login", {"member_no": self.m["member_no"], "pin": "1234"})
        self.assertEqual(status, 200)
        status, me = self.c.api("GET", "/api/me")
        self.assertEqual((status, me["balance"], me["member"]["name"]), (200, 300, "山田 花子"))
        self.assertEqual(me["recent"][0]["reason"], "入会特典")
        _, hist = self.c.api("GET", "/api/history")
        self.assertEqual(hist["earned"], 300)

    def test_post_requires_fetch_header(self):
        status, _, _ = self.c.req("POST", "/api/login", {"member_no": self.m["member_no"], "pin": "1234"})
        self.assertEqual(status, 403)

    def test_pin_change_logs_out_other_devices(self):
        other = Client(self.app)
        other.api("POST", "/api/login", {"member_no": self.m["member_no"], "pin": "1234"})
        self.c.api("POST", "/api/login", {"member_no": self.m["member_no"], "pin": "1234"})
        status, body = self.c.api("POST", "/api/pin", {"current": "1234", "next": "9876"})
        self.assertEqual(status, 200)
        self.assertEqual(self.c.api("GET", "/api/me")[0], 200)      # 変えた本人はそのまま
        self.assertEqual(other.api("GET", "/api/me")[0], 401)       # ほかの端末はログアウト

    def test_lockout(self):
        for _ in range(5):
            self.c.api("POST", "/api/login", {"member_no": self.m["member_no"], "pin": "0000"})
        status, body = self.c.api("POST", "/api/login", {"member_no": self.m["member_no"], "pin": "1234"})
        self.assertEqual(status, 429)

    def test_ip_limit_across_members(self):
        others = [service.register_member(self.app.conn, f"会員{i}", "1234", self.today) for i in range(31)]
        ip = {"X-Requested-With": "fetch", "X-Points-Client": "203.0.113.9"}
        for o in others[:30]:
            self.c.req("POST", "/api/login", {"member_no": o["member_no"], "pin": "0000"}, ip)
        status, _, _ = self.c.req("POST", "/api/login", {"member_no": others[30]["member_no"], "pin": "1234"}, ip)
        self.assertEqual(status, 429)
        status, _, _ = self.c.req("POST", "/api/login", {"member_no": others[30]["member_no"], "pin": "1234"},
                                  {"X-Requested-With": "fetch", "X-Points-Client": "198.51.100.1"})
        self.assertEqual(status, 200)

    def test_cannot_request_someone_elses_invite(self):
        conn = self.app.conn
        other = service.register_member(conn, "佐藤 一郎", "2468", self.today)
        t = service.create_tour(conn, "M1", "奥入瀬", date(2026, 12, 1), 89800, kind="michi", invite_min_tours=1)
        n = service.create_tour(conn, "N1", "通常", date(2026, 9, 1), 9800)
        service.book_tour(conn, other["member_no"], n["id"], 0, date(2026, 8, 1))
        service.complete_tour(conn, n["id"], date(2026, 9, 1))
        service.send_invites(conn, t["id"], self.today)
        inv = service.invite_for(conn, t["id"], other["id"])
        self.c.api("POST", "/api/login", {"member_no": self.m["member_no"], "pin": "1234"})
        status, _ = self.c.api("POST", f"/api/invites/{inv['id']}/request")
        self.assertEqual(status, 400)
        c2 = Client(self.app)
        c2.api("POST", "/api/login", {"member_no": other["member_no"], "pin": "2468"})
        _, me = c2.api("GET", "/api/me")
        self.assertEqual(me["invites"][0]["state"]["code"], "invited")
        self.assertEqual(c2.api("POST", f"/api/invites/{inv['id']}/request")[0], 200)
        _, me = c2.api("GET", "/api/me")
        self.assertEqual(me["invites"][0]["state"]["code"], "requested")


if __name__ == "__main__":
    unittest.main()
