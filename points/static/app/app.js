// 会員アプリ（PWA）。データはサーバの /api/ から読み、画面はこのファイルで組み立てる。
// 見た目と画面の構成は、画面デモ（site/member）のアプリ風デザインと同じ。
"use strict";

const root = document.getElementById("root");
const CACHE_KEY = "bt-member-last-v1";   // 最後に見た会員証（電波が弱いとき用）。ログアウトで消す
const ui = {tab: "home", me: null, history: null, tours: null, flash: null, offlineAt: null, installEvent: null, loading: true};

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const yen = n => Number(n).toLocaleString("ja-JP");
const WEEK = "日月火水木金土";
const parse = s => { const [y,m,d] = s.split("-").map(Number); return new Date(Date.UTC(y, m - 1, d)); };
const jp = s => { const [y,m,d] = s.split("-").map(Number); return `${y}年${m}月${d}日`; };
const slash = s => s.replace(/-/g, "/");
const weekday = s => WEEK[parse(s).getUTCDay()];
const flashHtml = () => ui.flash ? `<div class="toast ${ui.flash[0]}" role="status">${esc(ui.flash[1])}</div>` : "";

// --- サーバとのやりとり -------------------------------------------------------
class LoginRequired extends Error {}
async function api(method, path, data){
  const res = await fetch(path, {method, credentials: "same-origin",
    headers: {"X-Requested-With": "fetch", ...(data ? {"Content-Type": "application/json"} : {})},
    body: data ? JSON.stringify(data) : undefined});
  let body = {};
  try { body = await res.json(); } catch (e) {}
  if (res.status === 401 && body.login) throw new LoginRequired();
  if (!res.ok) throw new Error(body.error || "うまくいきませんでした。時間をおいてもう一度お試しください");
  return body;
}
function remember(me){ try { me ? localStorage.setItem(CACHE_KEY, JSON.stringify({at: Date.now(), me})) : localStorage.removeItem(CACHE_KEY); } catch (e) {} }
function recall(){ try { return JSON.parse(localStorage.getItem(CACHE_KEY) || "null"); } catch (e) { return null; } }

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
const ICONS = {
  home:`<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="2.5" y="6" width="19" height="12" rx="1.5"/><path d="M6 10h6M6 14h4"/></svg>`,
  history:`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16M4 12h16M4 19h10"/></svg>`,
  tours:`<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="3.5" width="17" height="14" rx="2"/><path d="M3.5 11h17M7.5 17.5V20M16.5 17.5V20"/></svg>`,
  info:`<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.01"/></svg>`,
};
const TABS = [["home","会員証"],["history","ポイント履歴"],["tours","ツアー"],["info","ご案内"]];
const TAB_SHORT = {home:"会員証", history:"履歴", tours:"ツアー", info:"ご案内"};

const histRow = r => { const up = r.points > 0;
  return `<tr><td class="d num">${slash(r.date)}</td><td>${esc(r.reason)}<span class="k">${esc(r.kind)}</span></td>
    <td class="p ${up ? "plus" : "minus"}">${up ? "+" : "−"}${yen(Math.abs(r.points))}pt</td></tr>`; };
const histTable = rows => `<table class="hist"><thead><tr><th>日付</th><th>内容</th><th style="text-align:right">ポイント</th></tr></thead><tbody>${rows.map(histRow).join("")}</tbody></table>`;

function hero(me){
  const m = me.member, r = me.rank;
  return `<section class="hero rank-${r.code}" aria-label="会員証 ${m.member_no} ${esc(m.name)}様 ${esc(r.name)} 保有${yen(me.balance)}ポイント">
    <div class="h-top"><span>バスツアー会員証</span><span class="h-rank">${esc(r.name)}・${r.multiplier}倍</span></div>
    <div class="h-label">保有ポイント</div>
    <div class="h-pt"><b class="num">${yen(me.balance)}</b><span>pt</span></div>
    <div class="h-foot"><span class="mono">${m.member_no}</span><span>${esc(m.name)} 様</span></div></section>`;
}

function rankRoute(me){
  const idx = me.ranks.findIndex(r => r.code === me.rank.code);
  return `<div class="route" role="img" aria-label="直近1年の参加 ${me.rank.tours}回。現在 ${esc(me.rank.name)}">
    ${me.ranks.map((r, i) => `<div class="stop ${i < idx ? "done" : i === idx ? "here" : ""}"><b>${esc(r.name)}</b><span>${r.need ? `${r.need}回〜` : "入会時"}・${r.mult}倍</span></div>`).join("")}
  </div>`;
}

function inviteCard(inv, me){
  const st = inv.state.code;
  const action = st === "booked" ? `<div class="state">ご予約済みです。当日のご参加をお待ちしております。</div>`
    : st === "requested" ? `<div class="state">参加のご希望を承りました。スタッフからご連絡いたします。</div>`
    : `<div class="actions"><button type="button" class="btn" data-request="${inv.id}">参加を希望する</button><span class="small muted">窓口・お電話でも承ります</span></div>`;
  return `<section class="invite" aria-label="道ツアーへのご招待">
    <h2>道ツアーへのご招待</h2>
    <p class="small">直近1年で通常ツアーに${me.normal_tours}回ご参加いただいた${esc(me.member.name)}様へ、道ツアーのご案内です。</p>
    <div class="tname">${esc(inv.tour_name)}</div>
    <dl><dt>出発日</dt><dd>${jp(inv.depart_date)}（${weekday(inv.depart_date)}）</dd><dt>代金</dt><dd>${yen(inv.price)}円</dd><dt>参加特典</dt><dd class="plus">+${yen(inv.bonus)}pt</dd></dl>
    ${action}
  </section>`;
}

function inviteBlock(me){
  if (me.invites.length) return me.invites.map(i => inviteCard(i, me)).join("");
  const g = me.goal;
  const dots = Array.from({length: g.need}, (_, i) => `<i class="${i < g.have ? "on" : ""}"></i>`).join("");
  return `<section class="card goal"><h2>道ツアーへのご招待まで <span class="badge rank-gold">招待制</span></h2>
    <div class="dots" aria-hidden="true">${dots}</div>
    <p class="small">${g.left ? `直近1年の通常ツアー参加 <b>${g.have}回</b>。あと<b>${g.left}回</b>のご参加で、道ツアーへの招待が届きます。` : "招待の条件を満たしています。次の道ツアーのご案内をお待ちください。"}</p></section>`;
}

function offlineNote(){
  if (!ui.offlineAt) return "";
  const d = new Date(ui.offlineAt);
  return `<div class="offline" role="status">電波が届かないため、${d.getMonth() + 1}月${d.getDate()}日 ${d.getHours()}:${String(d.getMinutes()).padStart(2, "0")} 時点の内容を表示しています</div>`;
}

// --- 画面 ------------------------------------------------------------------
const views = {
  home(me){
    const r = me.rank, R = me.rules;
    const nextRank = me.ranks.find(x => x.need > r.tours);
    const t = me.next_tour;
    const board = t ? `<section class="card next" aria-labelledby="next-h"><h2 id="next-h">次のご参加予定</h2>
        <div class="tname">${esc(t.name)}</div>
        <dl><dt>出発日</dt><dd>${jp(t.depart_date)}（${weekday(t.depart_date)}）${t.days === 0 ? "・本日出発" : `・あと${t.days}日`}</dd>
          <dt>お支払い</dt><dd>${yen(t.pay)}円</dd><dt>ポイント利用</dt><dd>${yen(t.points_used)}pt</dd><dt>付与予定</dt><dd class="plus">+${yen(t.gain)}pt</dd></dl></section>`
      : `<section class="card next"><h2>次のご参加予定</h2><p class="small muted">参加予定のツアーはありません。ご予約はツアー窓口・お電話で承ります。</p></section>`;
    const chip = t ? `<div class="chip-next" role="note">次のツアーまで<b>${t.days === 0 ? "本日出発" : `あと${t.days}日`}</b></div>` : "";
    return `
    <div class="page-title"><h1>こんにちは、${esc(me.member.name)} 様</h1></div>
    ${offlineNote()}${flashHtml()}
    ${inviteBlock(me)}
    <div class="grid two">
      <div>${hero(me)}<p class="hero-note">ツアー当日、受付でこの画面をお見せください</p>${chip}</div>
      <section class="card" aria-labelledby="bal-h">
        <h2 id="bal-h">ポイントの使い方と期限</h2>
        <p class="small muted">${yen(me.balance)}円分としてツアー代金に使えます（${R.redeem_unit}pt単位）</p>
        ${me.soon ? `<div class="notice"><b>${yen(me.soon.points)}pt</b> の有効期限が近づいています（${jp(me.soon.date)}まで）</div>` : ""}
        ${me.expiring.length ? `<div class="small muted">有効期限ごとの内訳</div><table class="plain">${me.expiring.slice(0, 3).map(x => `<tr><th>${jp(x.date)}まで</th><td>${yen(x.points)}pt</td></tr>`).join("")}</table>` : `<p class="small muted">有効なポイントはありません。</p>`}
        ${me.expiring.length > 3 ? `<button type="button" class="linkbtn" data-tab="info">有効期限をすべて見る</button>` : ""}
      </section>
    </div>
    <div class="grid two-even">
      <section class="card" aria-labelledby="rank-h">
        <h2 id="rank-h">会員ランク <span class="badge rank-${r.code}">${esc(r.name)}</span></h2>
        ${rankRoute(me)}
        <p class="small">直近1年の参加 <b>${r.tours}回</b>${nextRank ? `。あと<b>${nextRank.need - r.tours}回</b>で${esc(nextRank.name)}（${nextRank.mult}倍）になります。` : "。最上位ランクです。"}</p>
      </section>
      ${board}
    </div>
    <section class="card"><h2>最近のポイント <button type="button" class="link" data-tab="history">履歴をすべて見る</button></h2>
      ${me.recent.length ? histTable(me.recent) : `<p class="muted small">まだありません。</p>`}</section>`;
  },

  history(me){
    const h = ui.history;
    if (!h) return `<div class="page-title"><h1>ポイント履歴</h1></div>${offlineNote()}<p class="loading">${ui.offlineAt ? "電波が届くところで開くと表示されます。" : "読み込んでいます…"}</p>`;
    return `<div class="page-title"><h1>ポイント履歴</h1></div>
    <div class="grid two" style="grid-template-columns:${innerWidth >= 960 ? "1.6fr .9fr" : "1fr"}">
      <section class="card">${h.items.length ? histTable(h.items) : `<p class="muted">ポイントの履歴はまだありません。</p>`}</section>
      <section class="card"><h2>これまでの合計</h2><dl class="kv"><dt>獲得したポイント</dt><dd>+${yen(h.earned)}pt</dd><dt>ツアー代金に使ったポイント</dt><dd>${yen(h.used)}pt</dd><dt>現在の保有ポイント</dt><dd><b>${yen(me.balance)}pt</b></dd></dl></section>
    </div>`;
  },

  tours(me){
    const ts = ui.tours;
    const trip = t => `<div class="trip"><div class="top"><span class="badge st-${t.status}">${esc(t.status_label)}</span>${t.michi ? `<span class="badge rank-gold">道ツアー</span>` : ""}<span>${jp(t.depart_date)}（${weekday(t.depart_date)}）出発</span></div>
        <div class="name">${esc(t.name)}</div>
        <div class="facts"><span>代金 ${yen(t.price)}円</span>${t.points_used ? `<span>ポイント利用 ${yen(t.points_used)}pt</span>` : ""}
          ${t.status === "completed" ? `<span class="plus">獲得 +${yen(t.earned)}pt</span>` : ""}${t.status === "booked" ? `<span class="plus">参加で +${yen(t.gain)}pt の予定</span>` : ""}</div></div>`;
    const body = !ts ? `<p class="loading">${ui.offlineAt ? "電波が届くところで開くと表示されます。" : "読み込んでいます…"}</p>` : `
    <div class="grid two-even">
      <section class="card"><h2>参加予定</h2>${ts.upcoming.map(trip).join("") || `<p class="muted small">参加予定のツアーはありません。ご予約はツアー窓口・お電話で承ります。</p>`}</section>
      <section class="card"><h2>これまでのツアー</h2>${ts.past.map(trip).join("") || `<p class="muted small">まだありません。</p>`}</section>
    </div>`;
    return `<div class="page-title"><h1>ツアー</h1></div>${offlineNote()}${flashHtml()}${me.invites.map(i => inviteCard(i, me)).join("")}${body}`;
  },

  info(me){
    const R = me.rules;
    return `<div class="page-title"><h1>ご案内</h1></div>
    ${offlineNote()}${flashHtml()}
    <div class="grid two-even">
      <section class="card"><h2>有効期限ごとのポイント</h2>${
        me.expiring.length ? `<table class="plain">${me.expiring.map(x => `<tr><th>${jp(x.date)}まで</th><td>${yen(x.points)}pt</td></tr>`).join("")}</table>` : `<p class="muted small">有効なポイントはありません。</p>`}
        <p class="small muted">付与日から${R.expiry_years}年後の月末まで有効です。期限の近いものから使われます。</p></section>
      <section class="card"><h2>ポイントのため方</h2><ul class="how">
        <li>ツアー代金${R.yen_per_point}円ごとに1pt × ランク倍率（ツアー終了後に付与）</li>
        <li>お誕生月のツアー参加で +${R.birthday}pt</li>
        <li>ご紹介した方の初参加で +${R.referral}pt</li>
        <li>キャンペーン対象ツアーはポイント増量</li></ul>
        <p class="small"><a href="/rules">ポイント制度のくわしいご案内</a></p></section>
      ${installCard()}
      <section class="card"><h2>暗証番号の変更</h2><form class="stack" data-form="pin">
        <label class="field"><span>現在の暗証番号</span><input class="input" name="current" type="password" inputmode="numeric" autocomplete="current-password" required></label>
        <label class="field"><span>新しい暗証番号</span><input class="input" name="next" type="password" inputmode="numeric" autocomplete="new-password" required><small>4〜8桁の数字。変えると、ほかのスマートフォンなどでのログインは解除されます</small></label>
        <div><button class="btn">変更する</button></div></form></section>
      <section class="card"><h2>会員情報</h2><dl class="kv"><dt>会員番号</dt><dd class="mono">${me.member.member_no}</dd><dt>入会日</dt><dd>${jp(me.member.joined_on)}</dd></dl>
        <p class="small muted">ご登録内容の変更・退会はツアー窓口で承ります。</p>
        <div><button type="button" class="btn ghost" data-act="logout">ログアウト</button></div></section>
    </div>`;
  },

  login(){
    return `<div class="login">
      <header class="appbar"><span class="brand">バスツアー会員</span></header>
      <main>
        <h1>ログイン</h1>
        <p class="small">会員番号と暗証番号を入れると、会員証、保有ポイント、会員ランク、参加予定のツアーを確認できます。</p>
        ${flashHtml()}
        <section class="card">
          <form class="stack" data-form="login">
            <label class="field"><span>会員番号</span><input class="input mono" name="member_no" autocomplete="username" autocapitalize="characters" placeholder="例：BT00000017" required><small>会員証に記載されています</small></label>
            <label class="field"><span>暗証番号</span><input class="input" name="pin" type="password" inputmode="numeric" autocomplete="current-password" required></label>
            <button class="btn block">ログイン</button>
          </form>
          <p class="small muted">暗証番号を忘れた方は、ツアー窓口で再設定いたします。</p></section>
        ${installCard()}
        <p class="small"><a href="/rules">ポイント制度のご案内</a></p>
      </main>
    </div>`;
  },
};

// ホーム画面に追加する方法（すでにアプリとして開いているときは出さない）
function installCard(){
  const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  if (standalone) return "";
  const ios = /iPhone|iPad|iPod/.test(navigator.userAgent);
  const steps = ui.installEvent ? `<div><button type="button" class="btn" data-act="install">ホーム画面に追加する</button></div>`
    : ios ? `<ol><li>Safari で開き、画面下の共有ボタン（四角から矢印が出たマーク）を押す</li><li>「ホーム画面に追加」を押す</li><li>右上の「追加」を押す</li></ol>`
    : `<ol><li>Chrome の右上の「︙」を押す</li><li>「ホーム画面に追加」または「アプリをインストール」を押す</li></ol>`;
  return `<section class="card install"><h2>アプリとして使う</h2><p class="small muted">ホーム画面に追加すると、次からはアイコンを押すだけで会員証を開けます。</p>${steps}</section>`;
}

function render(){
  if (ui.loading) return;
  const me = ui.me;
  if (!me){ root.innerHTML = views.login(); document.title = "ログイン｜バスツアー会員"; ui.flash = null; return; }
  const navBtns = compact => TABS.map(([k,l]) => `<button type="button" class="navbtn" data-tab="${k}" ${ui.tab === k ? 'aria-current="page"' : ""}>${ICONS[k]}<span>${compact ? TAB_SHORT[k] : l}</span></button>`).join("");
  root.innerHTML = `<div class="app signed">
    <aside class="side" aria-label="メニュー">
      <span class="brand">バスツアー会員</span>
      <nav>${navBtns(false)}</nav>
      <div class="who"><span>ログイン中</span><b>${esc(me.member.name)} 様</b><span class="mono">${me.member.member_no}</span></div>
      <div class="links"><a href="/rules">制度のご案内</a><button type="button" data-act="logout">ログアウト</button></div>
    </aside>
    <div class="content">
      <header class="appbar"><span class="brand">バスツアー会員</span></header>
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
  const tab = e.target.closest("[data-tab]");
  if (tab){ if (location.hash !== "#" + tab.dataset.tab) location.hash = tab.dataset.tab; else goTab(tab.dataset.tab); return; }
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
    history.replaceState(null, "", "/app/"); ui.tab = "home"; render();
  } else if (act.dataset.act === "install" && ui.installEvent){
    ui.installEvent.prompt(); ui.installEvent = null; render();
  }
});

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

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/app/sw.js", {scope: "/app/"}).catch(() => {});

(async () => {
  await loadMe();
  ui.tab = TABS.some(t => t[0] === location.hash.slice(1)) ? location.hash.slice(1) : "home";
  render();
  if (ui.me && (ui.tab === "history" || ui.tab === "tours")){ await loadTab(); render(); }
})();
