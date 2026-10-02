import re
import unittest
from datetime import date
from urllib.parse import unquote

from points.web import App


class WebTest(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 10, 2)
        self.app = App(":memory:", today=lambda: self.today, admin_password="staff-pass")
        self.cookie = ""

    def req(self, method, path, form=None):
        status, headers, body = self.app.handle(method, path, form, self.cookie)
        for k, v in headers:
            if k == "Set-Cookie":
                self.cookie = v.split(";")[0]
        loc = dict(headers).get("Location", "")
        return status, unquote(loc), body

    def login_admin(self):
        status, loc, _ = self.req("POST", "/admin/login", {"password": "staff-pass", "operator": "佐藤"})
        self.assertEqual((status, loc), (303, "/admin"))

    def test_admin_requires_login(self):
        self.assertEqual(self.req("GET", "/admin")[1], "/admin/login")
        self.assertIn("パスワードが正しくありません",
                      self.req("POST", "/admin/login", {"password": "x", "operator": "a"})[1])
        self.assertEqual(self.req("GET", "/me")[1], "/")

    def test_forged_cookie_rejected(self):
        self.cookie = "sess=eyJyb2xlIjogImFkbWluIn0.deadbeef"
        self.assertEqual(self.req("GET", "/admin")[1], "/admin/login")

    def test_full_flow(self):
        self.login_admin()
        _, loc, _ = self.req("POST", "/admin/members/new",
                             {"name": "<b>山田</b>", "pin": "2468", "birthdate": "1950-10-05"})
        member_no = re.search(r"BT\d{8}", loc).group(0)
        _, _, body = self.req("GET", f"/admin/members/{member_no}")
        self.assertIn("&lt;b&gt;山田&lt;/b&gt;", body)
        self.assertNotIn("<b>山田</b>", body)

        _, loc, _ = self.req("POST", "/admin/tours", {"code": "T1", "name": "箱根", "depart_date": "2026-10-02",
                                                      "price": "9,800"})
        tour_path = loc.split("?")[0]
        _, loc, _ = self.req("POST", tour_path + "/book", {"member_no": member_no, "points": "150"})
        self.assertIn("100ポイント単位", loc)
        self.req("POST", tour_path + "/book", {"member_no": member_no, "points": "300"})
        _, loc, _ = self.req("POST", tour_path + "/complete", {})
        self.assertIn("295ポイントを付与", loc)  # (9800-300)//100=95 + 誕生月200

        self.req("POST", "/admin/logout")
        _, loc, _ = self.req("POST", "/login", {"member_no": member_no, "pin": "2468"})
        self.assertEqual(loc, "/me")
        _, _, body = self.req("GET", "/me")
        self.assertIn("295 <small>pt</small>", body)
        self.assertIn("誕生月特典", body)
        # 会員セッションでは管理画面に入れない
        self.assertEqual(self.req("GET", "/admin")[1], "/admin/login")

    def test_member_lockout(self):
        self.login_admin()
        _, loc, _ = self.req("POST", "/admin/members/new", {"name": "A", "pin": "1111"})
        member_no = re.search(r"BT\d{8}", loc).group(0)
        self.cookie = ""
        for _ in range(5):
            self.req("POST", "/login", {"member_no": member_no, "pin": "0000"})
        _, loc, _ = self.req("POST", "/login", {"member_no": member_no, "pin": "1111"})
        self.assertIn("ロック", loc)

    def test_rules_page_public(self):
        status, _, body = self.app.handle("GET", "/rules")
        self.assertEqual(status, 200)
        self.assertIn("100円ごとに1ポイント", body)
        self.assertNotRegex(body, r"(src|href)=['\"]https?://")  # 外部リソースを読み込まない


if __name__ == "__main__":
    unittest.main()
