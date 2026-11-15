"""スタッフ画面の HTML。見た目は画面デモ（site/michi/admin）と同じ。

ここでは画面を組み立てるだけで、データの変更は web.py から service を呼んで行う。
フォームにはすべて CSRF 対策の合言葉（csrf）を入れる。
"""

from datetime import date, timedelta
from html import escape

from . import rules, service

KIND_LABELS = {
    "earn": "ツアー参加", "bonus": "特典", "redeem": "利用", "restore": "返還",
    "expire": "失効", "adjust": "調整", "forfeit": "退会失効",
}
BOOKING_LABELS = {"booked": "参加予定", "completed": "参加済", "no_show": "不参加", "cancelled": "取消"}
TOUR_LABELS = {"scheduled": "催行予定", "completed": "催行完了", "cancelled": "中止"}
TOUR_STATUS_CLS = {"scheduled": "st-booked", "completed": "st-completed", "cancelled": "st-cancelled"}
INVITE_CLS = {"none": "st-none", "invited": "st-invited", "requested": "st-requested", "booked": "st-booked2"}
WEEK = "月火水木金土日"
NORMAL_TAG = '<span class="muted small">通常</span>'

ICON = {
    "home": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/></svg>',
    "tours": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="3.5" width="17" height="14" rx="3"/><path d="M3.5 11h17M7.5 17.5V20M16.5 17.5V20"/></svg>',
    "new": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10" cy="8" r="3.5"/><path d="M3.5 20c.8-3.6 3.4-5.5 6.5-5.5s5.7 1.9 6.5 5.5M18 7v6M15 10h6"/></svg>',
    "staff": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="8" r="3.2"/><circle cx="17" cy="9" r="2.6"/><path d="M3 20c.6-3.4 3-5.2 6-5.2s5.4 1.8 6 5.2M15.5 14.6c2.6-.3 4.8 1.2 5.5 4.4"/></svg>',
    "settings": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/></svg>',
}


def e(v):
    return "" if v is None else escape(str(v))


def yen(n):
    return f"{n:,}"


def slash(d):
    return str(d).replace("-", "/")


def wday(d):
    return WEEK[date.fromisoformat(str(d)).weekday()]


def badge(cls, text):
    return f'<span class="badge {cls}">{e(text)}</span>'


def rank_badge(rank):
    return badge("rank-" + rank["code"], rank["name"])


def csrf_field(token):
    return f'<input type="hidden" name="csrf" value="{e(token)}">'


def head(title, actions="", back=""):
    return (f"{f'<div>{back}</div>' if back else ''}<div class=\"head\"><h1>{e(title)}</h1>"
            f"{f'<div class=actions>{actions}</div>' if actions else ''}</div>")


def back_link(href, label):
    return f'<a class="back" href="{href}">← {e(label)}</a>'


def flash_html(flash):
    if not flash:
        return ""
    kind, text = flash
    return f'<div class="toast {"err" if kind == "err" else "ok"}" role="status">{e(text)}</div>'


def _doc(title, body):
    return ("<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<meta name='theme-color' content='#0a3d8f'>"
            f"<title>{e(title)}｜スタッフ画面</title>"
            "<link rel='stylesheet' href='/static/ui.css'><link rel='stylesheet' href='/static/staff.css'>"
            "<script src='/static/staff.js' defer></script>"
            f"</head><body>{body}</body></html>")


def layout(title, body, staff, token, current="", flash=None):
    menu = [("home", "/admin", "ホーム"), ("tours", "/admin/tours", "ツアー"), ("new", "/admin/members/new", "新規入会")]
    if staff["role"] == "admin":
        menu += [("staff", "/admin/staff", "スタッフ管理"), ("settings", "/admin/settings", "設定")]
    nav = "".join(f'<a href="{href}" {"aria-current=page" if current == k else ""}>{ICON[k]}{label}</a>'
                  for k, href, label in menu)
    return _doc(title, f"""
<header class="topbar">
  <a class="brand" href="/admin">バスツアー会員<small>スタッフ画面</small></a>
  <div class="who"><span>{e(staff['name'])}（{service.STAFF_ROLES[staff['role']]}）</span>
    <a href="/admin/password" style="color:inherit">パスワード変更</a>
    <form method="post" action="/admin/logout">{csrf_field(token)}<button>ログアウト</button></form></div>
</header>
<div class="shell">
  <aside class="side">
    <nav class="menu" aria-label="スタッフメニュー">{nav}</nav>
    <div class="links"><a href="/rules">制度のご案内</a><a href="/app/">会員ページ</a></div>
  </aside>
  <main class="work">{flash_html(flash)}{body}</main>
</div>""")


def login_page(flash=None):
    return _doc("ログイン", f"""
<header class="topbar"><span class="brand">バスツアー会員<small>スタッフ画面</small></span></header>
<main class="login-box">
  <h1>スタッフログイン</h1>
  {flash_html(flash)}
  <section class="card"><form method="post" action="/admin/login" class="form-grid" style="grid-template-columns:1fr">
    <label class="field"><span>ログインID</span><input class="input" name="login" autocomplete="username" autocapitalize="none" required></label>
    <label class="field"><span>パスワード</span><input class="input" name="password" type="password" autocomplete="current-password" required></label>
    <div><button class="btn block">ログイン</button></div>
  </form></section>
  <p class="small muted">アカウントは管理者が「スタッフ管理」で発行します。パスワードを忘れた場合は管理者に再設定を依頼してください。</p>
</main>""")


def ticket(m, rank):
    joined = m["joined_on"]
    return f"""<div class="ticket" role="img" aria-label="会員証 {m['member_no']}">
  <div class="t-head"><span>バスツアー会員証</span><span>{e(rank['name'])}</span></div>
  <div class="t-body"><div class="t-no">{m['member_no']}</div><div class="t-name">{e(m['name'])} 様</div>
    <dl><div><dt>入会</dt><dd>{joined[:4]}年{int(joined[5:7])}月</dd></div><div><dt>ポイント倍率</dt><dd>{rank['multiplier']:g}倍</dd></div></dl></div></div>"""


def history_table(rows):
    if not rows:
        return '<p class="muted small">履歴はまだありません。</p>'
    out = []
    for r in rows:
        reason = r["reason"]
        if r["tour_name"] and r["kind"] in ("earn", "bonus") and r["tour_name"] not in reason:
            reason += f"／{r['tour_name']}"
        sign = "+" if r["points"] > 0 else "−"
        out.append(f'<tr><td class="nowrap num">{slash(r["created_on"])}</td><td>{badge("plain", KIND_LABELS.get(r["kind"], r["kind"]))}</td>'
                   f'<td>{e(reason)}</td><td class="muted nowrap">{e(r["operator"] or "-")}</td>'
                   f'<td class="r {"plus" if r["points"] > 0 else "minus"}"><b>{sign}{yen(abs(r["points"]))}</b></td></tr>')
    return ('<div class="tablewrap"><table class="t"><thead><tr><th>日付</th><th>区分</th><th>内容</th><th>担当</th>'
            f'<th class="r">ポイント</th></tr></thead><tbody>{"".join(out)}</tbody></table></div>')


def cancel_button(b, back, token):
    if b["status"] != "booked":
        return ""
    return (f'<form class="inline" method="post" action="/admin/bookings/{b["id"]}/cancel" data-confirm="この予約を取り消し、使ったポイントをお戻しします。よろしいですか？">'
            f'{csrf_field(token)}<input type="hidden" name="back" value="{e(back)}"><button class="btn sm ghost">取消</button></form>')


def tour_line(conn, t, extra=""):
    camp = []
    if t["bonus_multiplier"] != 1:
        camp.append(f"ポイント×{t['bonus_multiplier']:g}")
    if t["bonus_points"]:
        camp.append(f"+{yen(t['bonus_points'])}pt")
    return (f'<a href="/admin/tours/{t["id"]}"><span class="d">{int(t["depart_date"][5:7])}/{int(t["depart_date"][8:])}（{wday(t["depart_date"])}）</span>'
            f'<span><span class="nm">{"【道ツアー】" if t["kind"] == "michi" else ""}{e(t["name"])}</span>'
            f'<span class="sub">{yen(t["price"])}円{"・" + "・".join(camp) if camp else ""}</span></span>'
            f'<span class="small muted nowrap">{extra}</span></a>')


# --- 画面 -----------------------------------------------------------------

def home(conn, today, q, token):
    d = service.dashboard(conn, today)
    soon = today + timedelta(days=d["horizon_days"])
    members = service.search_members(conn, q) if q else service.search_members(conn, "", 50)
    rows = "".join(
        f'<tr><td><a class="linkish mono" href="/admin/members/{m["member_no"]}">{m["member_no"]}</a></td>'
        f'<td>{e(m["name"])}<span class="sub">{e(m["kana"])}</span></td>'
        f'<td>{rank_badge(service.rank_for(conn, m["id"], today))}</td>'
        f'<td class="r"><b>{yen(service.balance(conn, m["id"], today))}</b> pt</td>'
        f'<td>{badge("st-booked", "有効") if m["status"] == "active" else badge("st-cancelled", "退会")}</td></tr>'
        for m in members) or '<tr><td colspan="5" class="muted">該当する会員はいません</td></tr>'
    scheduled = conn.execute("SELECT * FROM tours WHERE status='scheduled' ORDER BY depart_date, id").fetchall()
    normal_next = "".join(tour_line(conn, t, f"{conn.execute('SELECT COUNT(*) FROM bookings WHERE tour_id=? AND status=?', (t['id'], 'booked')).fetchone()[0]}名")
                          for t in scheduled[:5]) or '<p class="muted small">催行予定のツアーはありません。</p>'
    michi = [t for t in scheduled if t["kind"] == "michi"]
    michi_card = ""
    if michi:
        lines = []
        for t in michi:
            s = service.invite_summary(conn, t, today)
            lines.append(tour_line(conn, t, "" if s["invited"] else "未招待").replace(
                '<span class="sub">', f'<span class="sub">対象 {s["eligible"]}名・招待 {s["invited"]}名・希望 {s["requested"]}名・予約 {s["booked"]}名　', 1))
        michi_card = f'<section class="card michi-card"><h2>道ツアーの招待 {badge("rank-gold", "招待制")}</h2><div class="depart">{"".join(lines)}</div></section>'
    first = scheduled[0]["depart_date"] if scheduled else None
    return f"""{head("ホーム", '<a class="btn" href="/admin/members/new">＋ 新規入会</a>')}
<div class="kpis">
  <div class="kpi"><span>未使用ポイント残高</span><b class="num">{yen(d['outstanding'])}<small>pt</small></b><em>{yen(d['outstanding'])}円相当の値引き予定</em></div>
  <div class="kpi"><span>有効会員数</span><b class="num">{yen(d['members'])}<small>名</small></b><em>退会者を除く</em></div>
  <div class="kpi {'warn' if d['expiring_soon'] else ''}"><span>{d['horizon_days']}日以内に失効予定</span><b class="num">{yen(d['expiring_soon'])}<small>pt</small></b><em>{slash(soon.isoformat())} まで</em></div>
  <div class="kpi"><span>催行予定ツアー</span><b class="num">{d['scheduled_tours']}<small>件</small></b><em>{f'次の出発 {slash(first)}' if first else '予定なし'}</em></div>
</div>
<div class="grid two">
  <section class="card"><h2>会員 <span class="muted">{f'「{e(q)}」の検索結果 {len(members)}件' if q else '最近入会した順'}</span></h2>
    <form method="get" action="/admin" class="search" role="search"><input class="input" name="q" value="{e(q)}" placeholder="会員番号・氏名・カナ・電話で検索" aria-label="会員を検索"><button class="btn ghost">検索</button></form>
    <div class="tablewrap"><table class="t members"><thead><tr><th>会員番号</th><th>氏名</th><th>ステイタス</th><th class="r">残高</th><th>状態</th></tr></thead><tbody>{rows}</tbody></table></div>
  </section>
  <div class="grid" style="gap:1rem">
    {michi_card}
    <section class="card"><h2>次の出発</h2><div class="depart">{normal_next}</div></section>
    <section class="card"><h2>期限切れポイントの失効処理</h2><p class="small muted">残高の表示では期限切れを自動で除いています。台帳に失効の記録を残すため、毎日自動で実行する設定にしてください（運用ガイド参照）。手動でも実行できます。</p>
      <form method="post" action="/admin/expire">{csrf_field(token)}<button class="btn ghost">失効処理を実行</button></form></section>
  </div>
</div>"""


def member_form(token, referrer_hint=""):
    return f"""{head("新規入会")}
<section class="card" style="max-width:860px"><form method="post" action="/admin/members/new" class="form-grid">{csrf_field(token)}
  <label class="field"><span>氏名（必須）</span><input class="input" name="name" required></label>
  <label class="field"><span>フリガナ</span><input class="input" name="kana"></label>
  <label class="field"><span>電話番号</span><input class="input" name="phone" inputmode="tel"></label>
  <label class="field"><span>メールアドレス</span><input class="input" name="email" type="email"></label>
  <label class="field"><span>生年月日</span><input class="input" name="birthdate" type="date"><small>誕生月特典に使います</small></label>
  <label class="field"><span>紹介者の会員番号（任意）</span><input class="input mono" name="referrer_no" placeholder="{e(referrer_hint)}"></label>
  <label class="field"><span>会員ページの暗証番号（必須）</span><input class="input" name="pin" type="password" inputmode="numeric" autocomplete="off" required><small>4〜8桁の数字。お客様に決めていただきます</small></label>
  <div class="field"><span>入会特典</span><p class="small muted" style="padding-top:.5rem">登録すると {rules.WELCOME_BONUS}pt が付き、会員番号が発行されます。</p></div>
  <div class="form-actions full"><button class="btn">入会登録</button></div>
</form></section>"""


def member_detail(conn, m, today, token):
    rank = service.rank_for(conn, m["id"], today)
    bal = service.balance(conn, m["id"], today)
    sched = service.expiring_schedule(conn, m["id"], today)
    base = f"/admin/members/{m['member_no']}"
    ref = None
    if m["referrer_id"]:
        ref = conn.execute("SELECT member_no, name FROM members WHERE id=?", (m["referrer_id"],)).fetchone()
    bookings = service.member_bookings(conn, m["id"])
    brows = "".join(
        f'<tr><td class="nowrap num">{slash(b["depart_date"])}</td><td><a class="linkish" href="/admin/tours/{b["tour_id"]}">{e(b["tour_name"])}</a></td>'
        f'<td class="r">{yen(b["price"])}</td><td class="r">{yen(b["points_used"])}</td>'
        f'<td>{badge("st-" + b["status"], BOOKING_LABELS[b["status"]])}</td><td class="r">{cancel_button(b, base, token)}</td></tr>'
        for b in bookings)
    btable = (f'<div class="tablewrap"><table class="t"><thead><tr><th>出発日</th><th>ツアー</th><th class="r">代金</th><th class="r">利用pt</th><th>状態</th><th></th></tr></thead><tbody>{brows}</tbody></table></div>'
              if bookings else '<p class="muted small">ツアーの予約・参加はまだありません。</p>')
    nxt = f"・あと{rank['tours_to_next']}回で{rank['next_name']}" if rank["next_name"] else "・最上位ステイタス"
    facts = "".join(f'<span>{slash(r["expires_on"])} まで <b>{yen(r["points"])}pt</b></span>' for r in sched) or "<span>有効なポイントはありません</span>"
    tools = "" if m["status"] != "active" else f"""
<div class="grid two-even">
  <section class="card"><h2>ポイント調整</h2><form method="post" action="{base}/adjust" class="form-grid">{csrf_field(token)}
    <label class="field"><span>ポイント</span><input class="input num" name="points" inputmode="numeric" required placeholder="例: 200 / -100"><small>減らすときはマイナス</small></label>
    <label class="field"><span>理由</span><input class="input" name="reason" required placeholder="例: 付与漏れの訂正"><small>履歴に残ります</small></label>
    <div class="form-actions full"><button class="btn">調整する</button></div></form></section>
  <section class="card"><h2>暗証番号の再設定</h2><form method="post" action="{base}/pin" class="form-grid" style="grid-template-columns:1fr">{csrf_field(token)}
    <label class="field"><span>新しい暗証番号</span><input class="input" name="pin" type="password" inputmode="numeric" autocomplete="off" required><small>本人確認のうえ、お客様に決めていただきます。ほかの端末のログインは解除されます</small></label>
    <div><button class="btn">再設定する</button></div></form></section>
</div>
<section class="card danger-zone"><h2>退会</h2><form method="post" action="{base}/withdraw" style="display:grid;gap:.8rem" data-confirm="退会処理をします。元に戻せません。よろしいですか？">{csrf_field(token)}
  <p class="small muted">退会すると保有ポイント {yen(bal)}pt はすべて失効します。参加予定のツアーがある場合は先に取り消してください。</p>
  <label class="check"><input type="checkbox" name="confirm" value="yes"> 保有ポイントが失効することをお客様に説明済み</label>
  <div><button class="btn danger">退会処理</button></div></form></section>"""
    return f"""{head(m['name'] + ' 様', f'<a class="btn ghost" href="{base}/card">会員証を印刷</a>', back_link('/admin', 'ホームに戻る'))}
<section class="card"><div class="profile">
  <div>{ticket(m, rank)}</div>
  <div class="grid" style="gap:1rem">
    <div style="display:flex;gap:.6rem;flex-wrap:wrap;align-items:center">{rank_badge(rank)}{'' if m['status'] == 'active' else badge('st-cancelled', '退会済')}<span class="small muted">直近1年の参加 {rank['tours']}回{nxt}</span></div>
    <div><div class="lbl">保有ポイント</div><div class="bal"><b class="num">{yen(bal)}</b><span>pt</span></div></div>
    <div class="facts-row">{facts}</div>
  </div></div></section>
<div class="grid two">
  <section class="card"><h2>ツアー</h2>{btable}</section>
  <section class="card"><h2>登録情報</h2><dl class="kv">
    <dt>フリガナ</dt><dd>{e(m['kana']) or '-'}</dd><dt>電話</dt><dd>{e(m['phone']) or '-'}</dd><dt>メール</dt><dd>{e(m['email']) or '-'}</dd>
    <dt>生年月日</dt><dd>{slash(m['birthdate']) if m['birthdate'] else '-'}</dd><dt>入会日</dt><dd>{slash(m['joined_on'])}</dd>
    {f'<dt>紹介者</dt><dd><a class="linkish mono" href="/admin/members/{ref["member_no"]}">{ref["member_no"]}</a> {e(ref["name"])}</dd>' if ref else ''}</dl></section>
</div>
<section class="card"><h2>ポイント履歴</h2>{history_table(service.history(conn, m['id'], 500))}</section>
{tools}"""


def member_card(conn, m, today, app_url):
    rank = service.rank_for(conn, m["id"], today)
    return f"""{head('会員証の印刷', '<button class="btn noprint" type="button" data-print>印刷する</button>', back_link('/admin/members/' + m['member_no'], m['name'] + ' 様に戻る'))}
<section class="card print-card">{ticket(m, rank)}
<p class="small">会員ページ：{e(app_url)}<br>会員番号と、ご自身で決めた暗証番号でログインできます。スマートフォンでは「ホーム画面に追加」すると、アプリのように使えます。</p></section>"""


def tours(conn, token):
    rows = []
    for t in service.list_tours(conn):
        camp = []
        if t["bonus_multiplier"] != 1:
            camp.append(f"ポイント×{t['bonus_multiplier']:g}")
        if t["bonus_points"] and t["kind"] != "michi":
            camp.append(f"+{yen(t['bonus_points'])}pt")
        if t["kind"] == "michi":
            camp.append(f"道ツアー特典 +{yen(t['bonus_points'])}pt")
        rows.append(f'<tr><td class="nowrap num">{slash(t["depart_date"])}（{wday(t["depart_date"])}）</td>'
                    f'<td><a class="linkish" href="/admin/tours/{t["id"]}">{e(t["name"])}</a><span class="sub mono">{e(t["code"])}</span></td>'
                    f'<td>{badge("rank-gold", "道ツアー") if t["kind"] == "michi" else NORMAL_TAG}</td>'
                    f'<td class="r">{yen(t["price"])}円</td><td>{badge("rank-gold", "・".join(camp)) if camp else "<span class=muted>-</span>"}</td>'
                    f'<td class="r">{t["participants"]}名</td><td>{badge(TOUR_STATUS_CLS[t["status"]], TOUR_LABELS[t["status"]])}</td></tr>')
    md = service.michi_settings(conn)
    return f"""{head("ツアー")}
<section class="card"><div class="tablewrap"><table class="t"><thead><tr><th>出発日</th><th>ツアー</th><th>種類</th><th class="r">代金</th><th>キャンペーン・特典</th><th class="r">人数</th><th>状態</th></tr></thead>
<tbody>{"".join(rows) or '<tr><td colspan="7" class="muted">登録されたツアーはありません</td></tr>'}</tbody></table></div></section>
<section class="card"><h2>ツアーを登録する</h2><form method="post" action="/admin/tours" class="form-grid">{csrf_field(token)}
  <label class="field"><span>ツアーコード</span><input class="input mono" name="code" required placeholder="例: 2026-12-HAKONE"></label>
  <label class="field"><span>ツアー名</span><input class="input" name="name" required></label>
  <label class="field"><span>種類</span><select class="input" name="kind"><option value="normal">通常ツアー</option><option value="michi">道ツアー（招待制）</option></select><small>道ツアーは招待された会員だけが予約できます</small></label>
  <label class="field"><span>招待条件（道ツアーのみ）</span><input class="input num" name="invite_min_tours" value="{md['min_tours']}" inputmode="numeric"><small>直近1年の通常ツアー参加回数がこの回数以上の会員を招待</small></label>
  <label class="field"><span>出発日</span><input class="input" name="depart_date" type="date" required></label>
  <label class="field"><span>代金（税込・1名）</span><input class="input num" name="price" inputmode="numeric" required></label>
  <label class="field"><span>キャンペーン倍率</span><input class="input num" name="bonus_multiplier" value="1"><small>通常は 1。2 にするとポイント2倍</small></label>
  <label class="field"><span>加算ポイント</span><input class="input num" name="bonus_points" inputmode="numeric" placeholder="0"><small>通常ツアーはキャンペーン加算（空欄は0）。道ツアーは特典（空欄は {yen(md['bonus'])}pt）</small></label>
  <div class="form-actions full"><button class="btn">登録する</button></div></form></section>"""


def invite_section(conn, t, today, open_, token):
    base = f"/admin/tours/{t['id']}"
    elig = service.eligible_for(conn, t, today)
    ids = [m["id"] for m, _ in elig] + [i["member_id"] for i in service.invites_of(conn, t["id"])]
    seen, rows = set(), []
    for mid in ids:
        if mid in seen:
            continue
        seen.add(mid)
        m = conn.execute("SELECT * FROM members WHERE id=?", (mid,)).fetchone()
        inv = service.invite_for(conn, t["id"], mid)
        st = service.invite_state(conn, inv)
        ops = ""
        if open_ and inv and st["code"] != "booked":
            have = service.invite_contacts(conn, inv["id"])
            ops = "".join(
                f'<form class="inline" method="post" action="{base}/contact">{csrf_field(token)}<input type="hidden" name="invite_id" value="{inv["id"]}">'
                f'<input type="hidden" name="channel" value="{c}"><button class="btn sm ghost">{service.CONTACT_CHANNELS[c]}で案内済</button></form> '
                for c in ("phone", "mail") if c not in have)
            ops += f'<a class="btn sm" href="{base}?check={m["member_no"]}#book">予約へ</a>'
        rows.append(f'<tr><td><a class="linkish mono" href="/admin/members/{m["member_no"]}">{m["member_no"]}</a></td>'
                    f'<td>{e(m["name"])}<span class="sub">{e(m["phone"])}</span></td>'
                    f'<td class="r">{service.normal_tours_in(conn, mid, today)}回</td>'
                    f'<td>{badge(INVITE_CLS[st["code"]], st["label"])}</td><td class="r nowrap">{ops}</td></tr>')
    s = service.invite_summary(conn, t, today)
    waiting = sum(1 for m, _ in elig if not service.invite_for(conn, t["id"], m["id"]))
    send = ""
    if open_:
        send = (f'<div class="form-actions"><form method="post" action="{base}/invite">{csrf_field(token)}'
                f'<button class="btn" {"" if waiting else "disabled"}>{f"条件を満たす {waiting}名に招待を送る" if waiting else "招待を送る対象はいません"}</button></form>'
                '<span class="small muted">招待は会員ページに表示されます。会員ページを使わない方には、電話・郵送でご案内して記録してください。</span></div>')
    table = (f'<div class="tablewrap"><table class="t"><thead><tr><th>会員番号</th><th>氏名・電話</th><th class="r">通常ツアー参加（直近1年）</th><th>招待の状態</th><th></th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
             if rows else '<p class="muted small">今のところ条件を満たす会員はいません。</p>')
    return f"""<section class="card michi-card"><h2>招待 {badge("rank-gold", "招待制")}</h2>
  <div class="inv-stats"><span>条件を満たす会員 <b>{s['eligible']}名</b></span><span>招待済 <b>{s['invited']}名</b></span><span>参加希望 <b>{s['requested']}名</b></span><span>予約 <b>{s['booked']}名</b></span></div>
  {table}{send}</section>"""


def tour_detail(conn, t, today, check, token):
    base = f"/admin/tours/{t['id']}"
    open_ = t["status"] == "scheduled"
    michi = t["kind"] == "michi"
    bookings = service.tour_bookings(conn, t["id"])
    rows = []
    for b in bookings:
        est = '<span class="muted">-</span>'
        if b["status"] == "booked":
            m = conn.execute("SELECT * FROM members WHERE id=?", (b["member_id"],)).fetchone()
            rank, items = service.estimate_earn(conn, m, t, b["price"] - b["points_used"])
            est = f'<b class="plus">+{yen(sum(p for _, p in items))}</b> <span class="sub" style="display:inline">{e(rank["name"])}</span>'
        rows.append(f'<tr><td><a class="linkish mono" href="/admin/members/{b["member_no"]}">{b["member_no"]}</a></td><td>{e(b["name"])}</td>'
                    f'<td class="r">{yen(b["points_used"])}</td><td class="r">{yen(b["price"] - b["points_used"])}円</td><td class="r nowrap">{est}</td>'
                    f'<td>{badge("st-" + b["status"], BOOKING_LABELS[b["status"]])}</td><td class="r">{cancel_button(b, base, token) if open_ else ""}</td></tr>')
    camp = []
    if t["bonus_multiplier"] != 1:
        camp.append(f"ポイント×{t['bonus_multiplier']:g}")
    if t["bonus_points"] and not michi:
        camp.append(f"+{yen(t['bonus_points'])}pt")
    facts = (f'<span>{badge(TOUR_STATUS_CLS[t["status"]], TOUR_LABELS[t["status"]])} {badge("rank-gold", "道ツアー") if michi else ""}</span>'
             + (f'<span>招待条件 <b>直近1年で通常ツアー {t["invite_min_tours"]}回以上</b></span><span>道ツアー特典 <b>+{yen(t["bonus_points"])}pt</b></span>' if michi else "")
             + f'<span>出発日 <b>{slash(t["depart_date"])}（{wday(t["depart_date"])}）</b></span><span>代金 <b>{yen(t["price"])}円</b></span>'
             f'<span>コード <b class="mono">{e(t["code"])}</b></span>' + (f'<span>キャンペーン <b>{"・".join(camp)}</b></span>' if camp else ""))
    active = [b for b in bookings if b["status"] != "cancelled"]
    body = f"""{head(t['name'], '', back_link('/admin/tours', 'ツアー一覧に戻る'))}
<section class="card"><div class="facts-row" style="font-size:var(--t-md)">{facts}</div></section>
{invite_section(conn, t, today, open_, token) if michi else ''}
<section class="card"><h2>予約者 <span class="muted">{len(active)}名</span></h2>{f'<div class="tablewrap"><table class="t"><thead><tr><th>会員番号</th><th>氏名</th><th class="r">利用pt</th><th class="r">支払額</th><th class="r">付与予定</th><th>状態</th><th></th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>' if rows else '<p class="muted small">予約はまだありません。</p>'}</section>"""
    if not open_:
        return body
    hint, checked = "", None
    if check:
        try:
            cm = service.get_member(conn, check)
            if michi and not service.invite_for(conn, t["id"], cm["id"]):
                hint = f'<div class="hint bad">{e(cm["name"])} 様はこの道ツアーに招待されていません。招待された会員だけが予約できます。</div>'
            elif cm["status"] != "active":
                hint = f'<div class="hint bad">{e(cm["name"])} 様は退会済みです。</div>'
            else:
                checked = cm
                hint = (f'<div class="hint"><b>{e(cm["name"])} 様</b>　残高 <b>{yen(service.balance(conn, cm["id"], today))}pt</b>'
                        f' ／ このツアーで使えるのは最大 <b>{yen(service.max_redeemable(conn, cm["id"], t["price"], today))}pt</b></div>')
        except service.PointError as ex:
            hint = f'<div class="hint bad">{e(ex)}</div>'
    booked = [b for b in bookings if b["status"] == "booked"]
    checks = "".join(f'<label class="check"><input type="checkbox" name="absent" value="{b["id"]}"> {e(b["name"])} 様は当日不参加</label>' for b in booked)
    early = date.fromisoformat(t["depart_date"]) > today
    return body + f"""
<div class="grid two-even">
  <section class="card" id="book"><h2>予約を登録する</h2>
    <form method="get" action="{base}#book" class="search"><input class="input mono" name="check" value="{e(check)}" placeholder="会員番号（例: BT00000017）" aria-label="会員番号"><button class="btn ghost">残高を確認</button></form>
    {hint}
    <form method="post" action="{base}/book" class="search">{csrf_field(token)}<input type="hidden" name="member_no" value="{e(checked['member_no'] if checked else '')}">
      <input class="input num" name="points" value="0" inputmode="numeric" aria-label="利用ポイント" {'' if checked else 'disabled'}><button class="btn" {'' if checked else 'disabled'}>予約を登録</button></form>
    <p class="small muted">{f'使うポイントを {rules.REDEEM_UNIT}pt 単位で入力してください（使わない場合は 0）。' if checked else '先に会員番号を入れて「残高を確認」を押してください。'}</p>
  </section>
  <section class="card"><h2>催行完了・ポイント付与</h2><form method="post" action="{base}/complete" style="display:grid;gap:.6rem" data-confirm="参加者にポイントを付与します。よろしいですか？">{csrf_field(token)}
    {checks or '<p class="muted small">参加予定の方はいません。</p>'}
    <div><button class="btn" {'disabled' if early else ''}>催行完了として付与</button></div></form>
    <p class="small muted">{f'出発日（{slash(t["depart_date"])}）以降に実行できます。' if early else '不参加の方には付与されず、使ったポイントも戻りません（取消扱いにする場合は先に「取消」してください）。'}</p></section>
</div>
<section class="card danger-zone"><h2>催行中止</h2><form method="post" action="{base}/cancel" style="display:grid;gap:.8rem" data-confirm="ツアーを中止します。元に戻せません。よろしいですか？">{csrf_field(token)}
  <label class="check"><input type="checkbox" name="confirm" value="yes"> 全員の予約を取り消し、使ったポイントをお戻しする</label>
  <div><button class="btn danger">ツアーを中止する</button></div></form></section>"""


def staff_list(conn, me, token):
    rows = []
    for s in service.list_staff(conn):
        toggle = ""
        if s["id"] != me["id"]:
            toggle = (f'<form class="inline" method="post" action="/admin/staff/{s["id"]}/active">{csrf_field(token)}'
                      f'<input type="hidden" name="active" value="{0 if s["active"] else 1}"><button class="btn sm ghost">{"停止する" if s["active"] else "再開する"}</button></form>')
        reset = (f'<form class="inline" method="post" action="/admin/staff/{s["id"]}/password">{csrf_field(token)}'
                 f'<input class="input" style="width:11em;display:inline-block;min-height:2rem;padding:.2rem .5rem" name="password" type="password" autocomplete="new-password" placeholder="新しいパスワード" required> '
                 f'<button class="btn sm ghost">再設定</button></form>')
        rows.append(f'<tr><td class="mono">{e(s["login"])}</td><td>{e(s["name"])}</td><td>{service.STAFF_ROLES[s["role"]]}</td>'
                    f'<td>{badge("st-booked", "有効") if s["active"] else badge("st-cancelled", "停止中")}</td><td class="nowrap">{slash(s["created_on"])}</td>'
                    f'<td class="r nowrap">{reset} {toggle}</td></tr>')
    return f"""{head("スタッフ管理")}
<section class="card"><p class="small muted">操作の記録（ポイント履歴の「担当」）には、ログインしたスタッフの氏名が残ります。退職した人のアカウントは「停止する」にしてください。</p>
<div class="tablewrap"><table class="t"><thead><tr><th>ログインID</th><th>氏名</th><th>権限</th><th>状態</th><th>作成日</th><th></th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></section>
<section class="card"><h2>スタッフを追加する</h2><form method="post" action="/admin/staff" class="form-grid">{csrf_field(token)}
  <label class="field"><span>ログインID</span><input class="input mono" name="login" required autocapitalize="none" placeholder="例: suzuki"><small>半角英数字</small></label>
  <label class="field"><span>氏名</span><input class="input" name="name" required></label>
  <label class="field"><span>最初のパスワード</span><input class="input" name="password" type="password" autocomplete="new-password" required><small>{service.MIN_PASSWORD}文字以上。本人にログイン後に変えてもらいます</small></label>
  <label class="field"><span>権限</span><select class="input" name="role"><option value="staff">スタッフ（日々の窓口業務）</option><option value="admin">管理者（スタッフ管理・設定も可）</option></select></label>
  <div class="form-actions full"><button class="btn">追加する</button></div></form></section>"""


def settings_page(conn, token):
    md = service.michi_settings(conn)
    return f"""{head("設定")}
<section class="card" style="max-width:760px"><h2>道ツアー（招待制）の既定値</h2>
<p class="small muted">新しく道ツアーを登録するときの初期値です。登録済みのツアーには影響しません。仕様が決まるまでの仮の値です。</p>
<form method="post" action="/admin/settings" class="form-grid">{csrf_field(token)}
  <label class="field"><span>招待条件（直近1年の通常ツアー参加回数）</span><input class="input num" name="michi_min_tours" value="{md['min_tours']}" inputmode="numeric" required></label>
  <label class="field"><span>道ツアー参加の特典ポイント</span><input class="input num" name="michi_bonus" value="{md['bonus']}" inputmode="numeric" required></label>
  <div class="form-actions full"><button class="btn">保存する</button></div></form></section>
<section class="card" style="max-width:760px"><h2>ポイント制度の数値</h2>
<p class="small muted">付与率・ステイタス・有効期限は、会員規約と一緒に変える必要があるため画面からは変えられません。points/rules.py を直してください。</p>
<dl class="kv"><dt>ツアー参加</dt><dd>{rules.YEN_PER_POINT}円ごとに1pt × ステイタス倍率</dd><dt>入会特典</dt><dd>{rules.WELCOME_BONUS}pt</dd>
<dt>誕生月特典</dt><dd>{rules.BIRTHDAY_BONUS}pt</dd><dt>ご紹介特典</dt><dd>{rules.REFERRAL_BONUS}pt</dd>
<dt>ステイタス</dt><dd>{"／".join(f"{n} {need}回〜 {mult:g}倍" for _, n, need, mult in rules.RANKS)}</dd>
<dt>利用単位</dt><dd>{rules.REDEEM_UNIT}pt</dd><dt>有効期限</dt><dd>付与日から{rules.EXPIRY_YEARS}年後の月末</dd></dl></section>"""


def password_page(token):
    return f"""{head("パスワード変更")}
<section class="card" style="max-width:520px"><form method="post" action="/admin/password" class="form-grid" style="grid-template-columns:1fr">{csrf_field(token)}
  <label class="field"><span>今のパスワード</span><input class="input" name="current" type="password" autocomplete="current-password" required></label>
  <label class="field"><span>新しいパスワード</span><input class="input" name="new" type="password" autocomplete="new-password" required><small>{service.MIN_PASSWORD}文字以上</small></label>
  <label class="field"><span>新しいパスワード（確認）</span><input class="input" name="confirm" type="password" autocomplete="new-password" required></label>
  <div><button class="btn">変更する</button></div></form>
<p class="small muted">変更すると、ほかの端末でのログインは解除されます。</p></section>"""


def rules_page():
    rank_rows = "".join(f"<tr><th>{e(name)}</th><td>{'ご入会時' if not need else f'直近1年で{need}回以上ご参加'}</td><td class='v'>{mult:g}倍</td></tr>"
                        for _, name, need, mult in rules.RANKS)
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#0a3d8f"><title>ポイント制度のご案内</title><link rel="stylesheet" href="/static/ui.css">
<style>main{{max-width:860px;margin:0 auto;padding:1rem 16px 3rem;display:grid;gap:1rem}}.box{{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:1.2rem;display:grid;gap:.8rem}}
table.list{{width:100%;border-collapse:collapse;font-size:var(--t-sm)}}table.list th,table.list td{{border:1px solid var(--line);padding:.55rem .7rem;text-align:left}}table.list th{{background:var(--surface-2);white-space:nowrap}}
ul{{margin:0;padding-left:1.2rem;display:grid;gap:.3rem}}header{{background:var(--bar);color:var(--on-bar);padding:.7rem 16px;font-weight:700}}header a{{color:inherit;text-decoration:none}}</style></head>
<body><header><a href="/app/">バスツアー会員</a></header><main>
<section class="box"><h1>ポイント制度のご案内</h1>
<h2 class="h-bar">ためる</h2><ul>
<li>ご入会で <b>{rules.WELCOME_BONUS}ポイント</b></li>
<li>ツアーにご参加いただくと、お支払額（ポイント利用分を除く税込代金）<b>{rules.YEN_PER_POINT}円ごとに1ポイント</b> × ステイタスの倍率。ツアー終了後に付与します。</li>
<li>お誕生月に出発するツアーにご参加で <b>{rules.BIRTHDAY_BONUS}ポイント</b></li>
<li>ご紹介した方が初めてツアーに参加されると、ご紹介者に <b>{rules.REFERRAL_BONUS}ポイント</b></li>
<li>対象ツアーでは、キャンペーンによるポイントの倍増・加算があります</li></ul>
<h2 class="h-bar">ステイタス</h2>
<table class="list"><tr><th>ステイタス</th><th>条件</th><th>ポイント倍率</th></tr>{rank_rows}</table>
<p class="small muted">ステイタスはツアー出発日より前の1年間の参加回数で、自動で決まります。</p>
<h2 class="h-bar">つかう</h2><ul><li>{rules.REDEEM_UNIT}ポイント単位で、1ポイント＝1円としてツアー代金にお使いいただけます。</li>
<li>予約を取り消した場合、使ったポイントは元の有効期限のままお戻しします。</li></ul>
<h2 class="h-bar">有効期限</h2><ul><li>付与日から{rules.EXPIRY_YEARS}年後の月末まで有効です。期限の近いポイントから使われます。</li>
<li>退会された場合、保有ポイントはすべて失効します。換金・譲渡はできません。</li></ul>
</section></main></body></html>"""
