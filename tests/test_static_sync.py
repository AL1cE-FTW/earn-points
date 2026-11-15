import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class StaticSyncTest(unittest.TestCase):
    """画面デモ（site/）とサービス版（points/static/）で同じ会員アプリのファイルを使っていることを確かめる。

    片方だけ直すと見た目がずれるため、直したら両方にコピーする。
    """

    def test_member_app_files_match(self):
        for demo, service in [("site/assets/member-app.js", "points/static/app/app.js"),
                              ("site/assets/member-app.css", "points/static/app/app.css")]:
            self.assertEqual((ROOT / demo).read_text(encoding="utf-8"), (ROOT / service).read_text(encoding="utf-8"),
                             f"{demo} と {service} が違います。片方を直したら、もう片方にもコピーしてください")

    def test_palette_matches(self):
        demo = (ROOT / "site/assets/ui.css").read_text(encoding="utf-8")
        service = (ROOT / "points/static/ui.css").read_text(encoding="utf-8")
        self.assertTrue(demo.startswith(service.rstrip("\n")), "site/assets/ui.css と points/static/ui.css の色・部品がずれています")


if __name__ == "__main__":
    unittest.main()
