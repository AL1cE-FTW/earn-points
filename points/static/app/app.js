// 会員アプリ（PWA）。マイレージ会員アプリのような画面を、このファイルで組み立てる。
// データはサーバの /api/ から読む。画面デモ（site/member）も同じファイルを使い、
// window.MEMBER_APP でデータの取り方（ブラウザ内のデモデータ）や表示の一部を差し替える。
// ※ site/assets/member-app.js はこのファイルのコピー（tests/test_static_sync.py で一致を確認）。
"use strict";

(() => {
const CFG = Object.assign({
  api: null,                 // (method, path, data) => Promise。省略時はサーバの /api/ を使う
  rulesUrl: "/rules",        // 制度のご案内
  serviceWorker: true,       // ホーム画面に追加したとき、電波がなくても開けるようにする
  cacheKey: "bt-member-last-v1",
  badge: "",                 // ヘッダーの右に出す表示（デモの日付など）
  loginHelp: "",             // ログイン画面の下に出す補足（デモのサンプル会員など）
  links: [],                 // PC 表示のメニュー下に出すリンク [[文字, URL], ...]
}, window.MEMBER_APP || {});

const root = document.getElementById("root");
const ui = {tab: "home", me: null, history: null, tours: null, flash: null, offlineAt: null, installEvent: null, loading: true};

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const num = n => Number(n).toLocaleString("ja-JP");
const WEEK = "日月火水木金土";
const parse = s => { const [y,m,d] = s.split("-").map(Number); return new Date(Date.UTC(y, m - 1, d)); };
const jp = s => { const [y,m,d] = s.split("-").map(Number); return `${y}年${m}月${d}日`; };
const md = s => { const [, m, d] = s.split("-").map(Number); return `${m}/${d}`; };
const slash = s => s.replace(/-/g, "/");
const weekday = s => WEEK[parse(s).getUTCDay()];
const flashHtml = () => ui.flash ? `<div class="toast ${ui.flash[0]}" role="status">${esc(ui.flash[1])}</div>` : "";

// --- サーバとのやりとり -------------------------------------------------------
class LoginRequired extends Error {}
async function fetchApi(method, path, data){
  const res = await fetch(path, {method, credentials: "same-origin",
    headers: {"X-Requested-With": "fetch", ...(data ? {"Content-Type": "application/json"} : {})},
    body: data ? JSON.stringify(data) : undefined});
  let body = {};
  try { body = await res.json(); } catch (e) {}
  if (res.status === 401 && body.login) throw new LoginRequired();
  if (!res.ok) throw new Error(body.error || "うまくいきませんでした。時間をおいてもう一度お試しください");
  return body;
}
const api = (method, path, data) => (CFG.api ? CFG.api(method, path, data, LoginRequired) : fetchApi(method, path, data));
function remember(me){ try { me ? localStorage.setItem(CFG.cacheKey, JSON.stringify({at: Date.now(), me})) : localStorage.removeItem(CFG.cacheKey); } catch (e) {} }
function recall(){ try { return JSON.parse(localStorage.getItem(CFG.cacheKey) || "null"); } catch (e) { return null; } }

async function loadMe(){
  try {
    ui.me = await api("GET", "/api/me");
    ui.offlineAt = null;
    remember(ui.me);
  } catch (e) {
    if (e instanceof LoginRequired){ ui.me = null; remember(null); }
    else {
      const last = recall();               // 電波がないときは、最後に見た内容を出す
      if (last){ ui.me = last.me; ui.offlineAt = last.at; }
      else ui.flash = ["err", "サーバにつながりません。電波の良いところでもう一度開いてください"];
    }
  }
  ui.loading = false;
}
async function loadTab(){
  try {
    if (ui.tab === "history") ui.history = await api("GET", "/api/history");
    if (ui.tab === "tours") ui.tours = await api("GET", "/api/tours");
  } catch (e) {
    if (e instanceof LoginRequired){ ui.me = null; remember(null); }
  }
}

// --- 部品 ------------------------------------------------------------------
const I = (d, extra = "") => `<svg viewBox="0 0 24 24" aria-hidden="true" ${extra}>${d}</svg>`;
const ICONS = {
  home: I(`<path d="M3.5 11 12 4l8.5 7"/><path d="M5.5 9.5V20h13V9.5"/>`),
  history: I(`<path d="M4 6h16M4 12h16M4 18h10"/>`),
  tours: I(`<rect x="3.5" y="3.5" width="17" height="14" rx="2.5"/><path d="M3.5 11h17M7.5 17.5V20M16.5 17.5V20"/>`),
  info: I(`<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.01"/>`),
  card: I(`<rect x="2.5" y="5.5" width="19" height="13" rx="2"/><path d="M2.5 10h19M6 14.5h5"/>`),
  guide: I(`<path d="M5 4.5h10.5L19 8v11.5H5z"/><path d="M8.5 11h7M8.5 15h7"/>`),
};
const TABS = [["home","ホーム"],["history","マイル履歴"],["tours","ツアー"],["info","ご案内"]];
const TAB_SHORT = {home:"ホーム", history:"履歴", tours:"ツアー", info:"ご案内"};

// 会員カード（ステイタスで色が変わる）。big=true は受付で見せる全画面表示用
function memberCard(me, big = false){
  const m = me.member, r = me.rank;
  return `<div class="mcard st-${r.code} ${big ? "big" : ""}" ${big ? "" : `role="button" tabindex="0" data-card aria-label="会員証を大きく表示する"`}>
    <div class="mc-top"><span class="mc-brand">バスツアー会員</span><span class="mc-status">${esc(r.name)}</span></div>
    <div class="mc-no mono">${m.member_no.replace(/^(BT)(\d{4})(\d{4})$/, "$1 $2 $3")}</div>
    <div class="mc-foot"><span class="mc-name">${esc(m.name)} 様</span><span>入会 ${m.joined_on.slice(0,4)}年${Number(m.joined_on.slice(5,7))}月</span></div>
  </div>`;
}

function statusProgress(me){
  const r = me.rank, ranks = me.ranks;
  const idx = ranks.findIndex(x => x.code === r.code);
  const next = ranks[idx + 1];
  const pct = next ? Math.min(100, Math.round((r.tours - ranks[idx].need) / (next.need - ranks[idx].need) * 100)) : 100;
  return `<section class="card status" aria-labelledby="st-h">
    <div class="st-head"><h2 id="st-h">ステイタス</h2><span class="badge rank-${r.code}">${esc(r.name)}・${r.multiplier}倍</span></div>
    <p class="st-next">${next ? `<b>${esc(next.name)}</b>まで あと<b class="big">${next.need - r.tours}</b>回のご参加` : `最上位のステイタスです`}</p>
    <div class="bar" role="img" aria-label="直近1年の参加 ${r.tours}回"><i style="width:${pct}%"></i></div>
    <ol class="steps">${ranks.map((x, i) => `<li class="${i < idx ? "done" : i === idx ? "here" : ""}"><b>${esc(x.name)}</b><span>${x.need ? `${x.need}回〜` : "入会時"}・${x.mult}倍</span></li>`).join("")}</ol>
    <p class="small muted">ステイタスは直近1年のご参加回数（${r.tours}回）で決まり、ツアーで付くマイルが増えます。</p>
  </section>`;
}

// 次のツアー：搭乗券のような見た目
function pass(t, opts = {}){
  const days = t.days ?? null;
  return `<article class="pass ${t.michi ? "michi" : ""}">
    <div class="p-date"><span>${t.depart_date.slice(0,4)}</span><b>${md(t.depart_date)}</b><span>（${weekday(t.depart_date)}）</span></div>
    <div class="p-body">
      <div class="p-top">${opts.label ? `<span class="p-label">${esc(opts.label)}</span>` : ""}${t.michi ? `<span class="badge rank-gold">道ツアー</span>` : ""}${days !== null ? `<span class="p-days">${days === 0 ? "本日出発" : `あと${days}日`}</span>` : ""}</div>
      <div class="p-name">${esc(t.name)}</div>
      <dl class="p-rows">
        <div><dt>お支払い</dt><dd>${num(t.pay ?? (t.price - t.points_used))}円</dd></div>
        <div><dt>マイル利用</dt><dd>${num(t.points_used)}</dd></div>
        <div><dt>獲得予定</dt><dd class="plus">+${num(t.gain)}</dd></div>
      </dl>
    </div>
  </article>`;
}

function inviteCard(inv, me){
  const st = inv.state.code;
  const action = st === "booked" ? `<div class="state">ご予約済みです。当日のご参加をお待ちしております。</div>`
    : st === "requested" ? `<div class="state">参加のご希望を承りました。スタッフからご連絡いたします。</div>`
    : `<div class="actions"><button type="button" class="btn" data-request="${inv.id}">参加を希望する</button><span class="small muted">窓口・お電話でも承ります</span></div>`;
  return `<section class="invite" aria-label="道ツアーへのご招待">
    <p class="inv-kicker">ご招待</p>
    <h2>${esc(inv.tour_name)}</h2>
    <p class="small">直近1年で通常ツアーに${me.normal_tours}回ご参加いただいた${esc(me.member.name)}様だけにご案内している、招待制の道ツアーです。</p>
    <dl><div><dt>出発日</dt><dd>${jp(inv.depart_date)}（${weekday(inv.depart_date)}）</dd></div><div><dt>代金</dt><dd>${num(inv.price)}円</dd></div><div><dt>参加特典</dt><dd>+${num(inv.bonus)}マイル</dd></div></dl>
    ${action}
  </section>`;
}

function inviteGoal(me){
  const g = me.goal;
  if (!g || !g.need) return "";
  const dots = Array.from({length: g.need}, (_, i) => `<i class="${i < g.have ? "on" : ""}"></i>`).join("");
  return `<section class="card goal"><div class="st-head"><h2>道ツアーへのご招待まで</h2><span class="badge rank-gold">招待制</span></div>
    <div class="dots" aria-hidden="true">${dots}</div>
    <p class="small">${g.left ? `直近1年の通常ツアー参加 <b>${g.have}回</b>。あと<b>${g.left}回</b>のご参加で、道ツアーへの招待が届きます。` : "招待の条件を満たしています。次の道ツアーのご案内をお待ちください。"}</p></section>`;
}

// マイル明細の行（月ごとに見出し）
function statement(items){
  let month = "", out = "";
  for (const r of items){
    const mo = r.date.slice(0, 7);
    if (mo !== month){ month = mo; out += `<li class="month">${mo.slice(0,4)}年${Number(mo.slice(5,7))}月</li>`; }
    const up = r.points > 0;
    out += `<li class="row"><span class="r-date">${md(r.date)}</span><span class="r-what">${esc(r.reason)}<small>${esc(r.kind)}</small></span>
      <span class="r-pt ${up ? "plus" : "minus"}">${up ? "+" : "−"}${num(Math.abs(r.points))}</span></li>`;
  }
  return `<ul class="stmt">${out}</ul>`;
}

function offlineNote(){
  if (!ui.offlineAt) return "";
  const d = new Date(ui.offlineAt);
  return `<div class="offline" role="status">電波が届かないため、${d.getMonth() + 1}月${d.getDate()}日 ${d.getHours()}:${String(d.getMinutes()).padStart(2, "0")} 時点の内容を表示しています</div>`;
}

// --- 画面 ------------------------------------------------------------------
const views = {
  home(me){
    const R = me.rules, t = me.next_tour;
    const nearest = me.expiring[0];
    return `
    <section class="hero">
      <p class="hello">${esc(me.member.name)} 様</p>
      ${memberCard(me)}
      <p class="hint">カードを押すと、受付で見せる会員証が大きく表示されます</p>
    </section>
    <div class="pull">
      ${offlineNote()}${flashHtml()}
      <section class="card miles" aria-labelledby="mi-h">
        <h2 id="mi-h" class="mi-label">保有マイル</h2>
        <p class="mi-num"><b class="num">${num(me.balance)}</b><span>マイル</span></p>
        <p class="mi-sub">ツアー代金 ${num(me.balance)}円分としてお使いいただけます（${R.redeem_unit}マイル単位）</p>
        ${me.soon ? `<p class="notice"><b>${num(me.soon.points)}マイル</b> の有効期限が近づいています（${jp(me.soon.date)}まで）</p>` : ""}
        <dl class="mi-facts">
          <div><dt>ステイタス</dt><dd>${esc(me.rank.name)}</dd></div>
          <div><dt>直近1年の参加</dt><dd>${me.rank.tours}回</dd></div>
          <div><dt>直近の有効期限</dt><dd>${nearest ? slash(nearest.date) : "—"}</dd></div>
        </dl>
      </section>
      <nav class="tiles" aria-label="よく使う機能">
        <button type="button" data-card>${ICONS.card}<span>会員証</span></button>
        <button type="button" data-tab="history">${ICONS.history}<span>マイル履歴</span></button>
        <button type="button" data-tab="tours">${ICONS.tours}<span>ツアー</span></button>
        <a href="${esc(CFG.rulesUrl)}">${ICONS.guide}<span>制度のご案内</span></a>
      </nav>
      ${me.invites.length ? me.invites.map(i => inviteCard(i, me)).join("") : ""}
      <div class="grid two">
        <section class="card" aria-labelledby="nx-h"><div class="st-head"><h2 id="nx-h">次のご参加予定</h2></div>
          ${t ? pass(t) : `<p class="small muted">参加予定のツアーはありません。ご予約はツアー窓口・お電話で承ります。</p>`}</section>
        ${statusProgress(me)}
      </div>
      ${me.invites.length ? "" : inviteGoal(me)}
      <section class="card"><div class="st-head"><h2>最近のマイル</h2><button type="button" class="link" data-tab="history">すべて見る</button></div>
        ${me.recent.length ? statement(me.recent) : `<p class="muted small">まだありません。</p>`}</section>
    </div>`;
  },

  history(me){
    const h = ui.history;
    const head = `<div class="page-title"><h1>マイル履歴</h1></div>${offlineNote()}`;
    if (!h) return head + `<p class="loading">${ui.offlineAt ? "電波が届くところで開くと表示されます。" : "読み込んでいます…"}</p>`;
    return head + `
    <section class="card sum"><dl>
      <div><dt>保有マイル</dt><dd class="accent">${num(me.balance)}</dd></div>
      <div><dt>これまでに獲得</dt><dd class="plus">+${num(h.earned)}</dd></div>
      <div><dt>ツアー代金に利用</dt><dd>${num(h.used)}</dd></div></dl></section>
    <section class="card">${h.items.length ? statement(h.items) : `<p class="muted">マイルの履歴はまだありません。</p>`}</section>`;
  },

  tours(me){
    const ts = ui.tours;
    const head = `<div class="page-title"><h1>ツアー</h1></div>${offlineNote()}${flashHtml()}${me.invites.map(i => inviteCard(i, me)).join("")}`;
    if (!ts) return head + `<p class="loading">${ui.offlineAt ? "電波が届くところで開くと表示されます。" : "読み込んでいます…"}</p>`;
    const today = me.today;
    const past = t => `<li class="row"><span class="r-date">${slash(t.depart_date)}</span><span class="r-what">${esc(t.name)}<small>${esc(t.status_label)}${t.michi ? "・道ツアー" : ""}${t.points_used ? `・マイル利用 ${num(t.points_used)}` : ""}</small></span>
      <span class="r-pt ${t.status === "completed" ? "plus" : "muted"}">${t.status === "completed" ? `+${num(t.earned)}` : "—"}</span></li>`;
    return head + `
    <section class="card"><div class="st-head"><h2>参加予定</h2></div>
      ${ts.upcoming.map(t => pass({...t, days: Math.round((parse(t.depart_date) - parse(today)) / 864e5)})).join("") || `<p class="muted small">参加予定のツアーはありません。ご予約はツアー窓口・お電話で承ります。</p>`}</section>
    <section class="card"><div class="st-head"><h2>これまでのツアー</h2></div>
      ${ts.past.length ? `<ul class="stmt">${ts.past.map(past).join("")}</ul>` : `<p class="muted small">まだありません。</p>`}</section>`;
  },

  info(me){
    const R = me.rules;
    return `<div class="page-title"><h1>ご案内</h1></div>
    ${offlineNote()}${flashHtml()}
    <div class="grid two-even">
      <section class="card"><div class="st-head"><h2>有効期限ごとのマイル</h2></div>${
        me.expiring.length ? `<table class="plain">${me.expiring.map(x => `<tr><th>${jp(x.date)}まで</th><td>${num(x.points)}マイル</td></tr>`).join("")}</table>` : `<p class="muted small">有効なマイルはありません。</p>`}
        <p class="small muted">付与日から${R.expiry_years}年後の月末まで有効です。期限の近いものから使われます。</p></section>
      <section class="card"><div class="st-head"><h2>マイルのため方</h2></div><ul class="how">
        <li>ツアー代金${R.yen_per_point}円ごとに1マイル × ステイタスの倍率（ツアー終了後に付与）</li>
        <li>お誕生月のツアー参加で +${R.birthday}マイル</li>
        <li>ご紹介した方の初参加で +${R.referral}マイル</li>
        <li>キャンペーン対象ツアーはマイル増量</li></ul>
        <p class="small"><a href="${esc(CFG.rulesUrl)}">マイレージ制度のくわしいご案内</a></p>
        <p class="small muted">「マイル」は当社のバスツアー会員制度のマイルです。航空会社のマイルとは交換できません。</p></section>
      ${installCard()}
      <section class="card"><div class="st-head"><h2>暗証番号の変更</h2></div><form class="stack" data-form="pin">
        <label class="field"><span>現在の暗証番号</span><input class="input" name="current" type="password" inputmode="numeric" autocomplete="current-password" required></label>
        <label class="field"><span>新しい暗証番号</span><input class="input" name="next" type="password" inputmode="numeric" autocomplete="new-password" required><small>4〜8桁の数字。変えると、ほかのスマートフォンなどでのログインは解除されます</small></label>
        <div><button class="btn">変更する</button></div></form></section>
      <section class="card"><div class="st-head"><h2>会員情報</h2></div><dl class="kv"><dt>会員番号</dt><dd class="mono">${me.member.member_no}</dd><dt>入会日</dt><dd>${jp(me.member.joined_on)}</dd></dl>
        <p class="small muted">ご登録内容の変更・退会はツアー窓口で承ります。</p>
        <div><button type="button" class="btn ghost" data-act="logout">ログアウト</button></div></section>
    </div>`;
  },

  login(){
    return `<div class="login">
      <section class="hero"><div class="lg-head"><span class="brand">バスツアー会員</span>${CFG.badge}</div>
        <h1>マイレージ会員ログイン</h1><p class="hint">会員証、保有マイル、ステイタス、参加予定のツアーを確認できます。</p></section>
      <main class="pull">
        ${flashHtml()}
        <section class="card">
          <form class="stack" data-form="login">
            <label class="field"><span>会員番号</span><input class="input mono" name="member_no" autocomplete="username" autocapitalize="characters" placeholder="例：BT00000017" required><small>会員証に記載されています</small></label>
            <label class="field"><span>暗証番号</span><input class="input" name="pin" type="password" inputmode="numeric" autocomplete="current-password" required></label>
            <button class="btn block">ログイン</button>
          </form>
          <p class="small muted">暗証番号を忘れた方は、ツアー窓口で再設定いたします。</p></section>
        ${CFG.loginHelp}
        ${installCard()}
        <p class="small"><a href="${esc(CFG.rulesUrl)}">マイレージ制度のご案内</a></p>
      </main>
    </div>`;
  },
};

// ホーム画面に追加する方法（すでにアプリとして開いているとき・デモのときは出さない）
function installCard(){
  const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  if (standalone || !CFG.serviceWorker) return "";
  const ios = /iPhone|iPad|iPod/.test(navigator.userAgent);
  const steps = ui.installEvent ? `<div><button type="button" class="btn" data-act="install">ホーム画面に追加する</button></div>`
    : ios ? `<ol><li>Safari で開き、画面下の共有ボタン（四角から矢印が出たマーク）を押す</li><li>「ホーム画面に追加」を押す</li><li>右上の「追加」を押す</li></ol>`
    : `<ol><li>Chrome の右上の「︙」を押す</li><li>「ホーム画面に追加」または「アプリをインストール」を押す</li></ol>`;
  return `<section class="card install"><div class="st-head"><h2>アプリとして使う</h2></div><p class="small muted">ホーム画面に追加すると、次からはアイコンを押すだけで会員証を開けます。</p>${steps}</section>`;
}

// 受付で見せる会員証（全画面）
function openCard(){
  if (!ui.me) return;
  let dlg = document.getElementById("cardview");
  if (!dlg){ dlg = document.createElement("dialog"); dlg.id = "cardview"; document.body.appendChild(dlg); }
  dlg.innerHTML = `<div class="cv">
    <p class="cv-title">会員証</p>
    ${memberCard(ui.me, true)}
    <p class="cv-miles">保有 <b>${num(ui.me.balance)}</b> マイル</p>
    <p class="cv-note">ツアー当日、受付でこの画面をお見せください</p>
    <form method="dialog"><button class="btn block">閉じる</button></form></div>`;
  if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
}

function render(){
  if (ui.loading) return;
  const me = ui.me;
  if (!me){ root.innerHTML = views.login(); document.title = "ログイン｜バスツアー会員"; ui.flash = null; return; }
  const navBtns = compact => TABS.map(([k,l]) => `<button type="button" class="navbtn" data-tab="${k}" ${ui.tab === k ? 'aria-current="page"' : ""}>${ICONS[k]}<span>${compact ? TAB_SHORT[k] : l}</span></button>`).join("");
  root.innerHTML = `<div class="app signed tab-${ui.tab}">
    <aside class="side" aria-label="メニュー">
      <span class="brand">バスツアー会員</span>
      <nav>${navBtns(false)}</nav>
      <div class="who"><span>ログイン中</span><b>${esc(me.member.name)} 様</b><span class="mono">${me.member.member_no}</span></div>
      <div class="links">${CFG.links.map(([l, u]) => `<a href="${esc(u)}">${esc(l)}</a>`).join("")}<a href="${esc(CFG.rulesUrl)}">制度のご案内</a><button type="button" data-act="logout">ログアウト</button></div>
    </aside>
    <div class="content">
      <header class="appbar"><span class="brand">バスツアー会員</span>${CFG.badge}<button type="button" class="cardbtn" data-card>${ICONS.card}<span>会員証</span></button></header>
      <main id="main">${views[ui.tab](me)}</main>
    </div>
  </div>
  <nav class="tabbar" aria-label="メニュー"><div class="tabs">${navBtns(true)}</div></nav>`;
  document.title = `${TABS.find(t => t[0] === ui.tab)[1]}｜バスツアー会員`;
  ui.flash = null;
}

// --- 操作 ------------------------------------------------------------------
async function goTab(tab){
  ui.tab = TABS.some(t => t[0] === tab) ? tab : "home";
  render(); window.scrollTo(0, 0);
  if (ui.tab === "history" || ui.tab === "tours"){ await loadTab(); render(); }
}

document.addEventListener("click", async e => {
  if (e.target.closest("[data-card]")){ openCard(); return; }
  const tab = e.target.closest("[data-tab]");
  if (tab){ if (location.hash !== "#" + tab.dataset.tab) location.hash = tab.dataset.tab; else goTab(tab.dataset.tab); return; }
  const fill = e.target.closest("[data-fill]");
  if (fill){ const f = document.querySelector("form[data-form=login]"); f.member_no.value = fill.dataset.fill; f.pin.value = fill.dataset.pin || ""; f.pin.focus(); return; }
  const req = e.target.closest("[data-request]");
  if (req){
    req.disabled = true;
    try { await api("POST", `/api/invites/${req.dataset.request}/request`); ui.flash = ["ok", "参加のご希望を承りました。スタッフからご連絡いたします"]; await loadMe(); }
    catch (err){ ui.flash = ["err", err instanceof LoginRequired ? "もう一度ログインしてください" : err.message]; }
    render(); return;
  }
  const act = e.target.closest("[data-act]");
  if (!act) return;
  if (act.dataset.act === "logout"){
    try { await api("POST", "/api/logout"); } catch (err) {}
    remember(null); Object.assign(ui, {me: null, history: null, tours: null, offlineAt: null, flash: ["ok", "ログアウトしました"]});
    history.replaceState(null, "", location.pathname); ui.tab = "home"; render();
  } else if (act.dataset.act === "install" && ui.installEvent){
    ui.installEvent.prompt(); ui.installEvent = null; render();
  }
});
document.addEventListener("keydown", e => { if ((e.key === "Enter" || e.key === " ") && e.target.matches && e.target.matches(".mcard[data-card]")){ e.preventDefault(); openCard(); } });

document.addEventListener("submit", async e => {
  const f = e.target.closest("form[data-form]");
  if (!f) return;
  e.preventDefault();
  const v = Object.fromEntries(new FormData(f));
  const btn = f.querySelector("button"); if (btn) btn.disabled = true;
  try {
    if (f.dataset.form === "login"){
      await api("POST", "/api/login", {member_no: v.member_no, pin: v.pin});
      ui.tab = "home"; await loadMe();
    } else if (f.dataset.form === "pin"){
      await api("POST", "/api/pin", {current: v.current, next: v.next});
      ui.flash = ["ok", "暗証番号を変更しました"];
    }
  } catch (err){
    if (err instanceof LoginRequired){ ui.me = null; }
    ui.flash = ["err", err instanceof TypeError ? "サーバにつながりません。電波の良いところでもう一度お試しください" : err.message];
  }
  render();
});

window.addEventListener("hashchange", () => goTab(location.hash.slice(1)));
window.addEventListener("beforeinstallprompt", e => { e.preventDefault(); ui.installEvent = e; if (ui.tab === "info" || !ui.me) render(); });
let lastWide = innerWidth >= 960;
window.addEventListener("resize", () => { const w = innerWidth >= 960; if (w !== lastWide){ lastWide = w; render(); } });
// アプリに戻ってきたら最新の内容にする
document.addEventListener("visibilitychange", async () => { if (document.visibilityState === "visible" && ui.me){ await loadMe(); render(); } });

if (CFG.serviceWorker && "serviceWorker" in navigator) navigator.serviceWorker.register("/app/sw.js", {scope: "/app/"}).catch(() => {});

// データが別の画面で変わったときに読み直す（画面デモでスタッフ画面と行き来するとき用）
window.memberApp = {async reload(){ await loadMe(); if (ui.me && (ui.tab === "history" || ui.tab === "tours")) await loadTab(); render(); }};

(async () => {
  await loadMe();
  ui.tab = TABS.some(t => t[0] === location.hash.slice(1)) ? location.hash.slice(1) : "home";
  render();
  if (ui.me && (ui.tab === "history" || ui.tab === "tours")){ await loadTab(); render(); }
})();
})();
