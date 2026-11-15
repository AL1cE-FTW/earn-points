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
  bus: I(`<rect x="4.5" y="3.5" width="15" height="14" rx="3"/><path d="M4.5 10.5h15M8 17.5v3M16 17.5v3M8.5 7h7"/><circle cx="8.5" cy="14" r=".9"/><circle cx="15.5" cy="14" r=".9"/>`),
  gift: I(`<rect x="3.5" y="9" width="17" height="4" rx="1"/><path d="M5 13v7.5h14V13M12 9v11.5M12 9c-1.5-4-6-4-5-1.2.6 1.4 5 1.2 5 1.2zm0 0c1.5-4 6-4 5-1.2-.6 1.4-5 1.2-5 1.2z"/>`),
  yen: I(`<circle cx="12" cy="12" r="9"/><path d="m8.5 7 3.5 5 3.5-5M12 12v5.5M9 12.5h6M9 15h6"/>`),
  back: I(`<path d="M9 7 4.5 11.5 9 16"/><path d="M4.5 11.5h10a5 5 0 0 1 0 10H12"/>`),
  hourglass: I(`<path d="M7 3.5h10M7 20.5h10M8 3.5c0 5 8 5 8 8.5s-8 3.5-8 8.5M16 3.5c0 5-8 5-8 8.5s8 3.5 8 8.5"/>`),
  pen: I(`<path d="M4 20l1-4.5L15.5 5a2.1 2.1 0 0 1 3 3L8 18.5z"/><path d="m13.5 7 3 3"/>`),
  cake: I(`<path d="M4 20.5h16V13a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2zM4 15.5c2.7 1.8 5.3-1.8 8 0s5.3 1.8 8 0M12 11V8"/><path d="M12 4.5c1 1 1 2 0 3-1-1-1-2 0-3z"/>`),
  people: I(`<circle cx="9" cy="8" r="3.2"/><circle cx="17" cy="9.5" r="2.5"/><path d="M3 20c.6-3.4 3-5.2 6-5.2s5.4 1.8 6 5.2M15.5 15c2.6-.3 4.8 1.2 5.5 4.5"/>`),
  spark: I(`<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>`),
  medal: I(`<circle cx="12" cy="14.5" r="5.5"/><path d="m8.5 3.5 2.2 5.6M15.5 3.5l-2.2 5.6"/>`),
  calendar: I(`<rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>`),
  expand: I(`<path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7"/>`),
  tap: I(`<path d="M9 11V5.5a1.5 1.5 0 0 1 3 0V11l.5-1.2a1.5 1.5 0 0 1 2.8.9v.5l.3-.5a1.5 1.5 0 0 1 2.8 1V15a6 6 0 0 1-6 6h-.5a6 6 0 0 1-4.6-2.2L5 15.5a1.5 1.5 0 0 1 2.3-1.9L9 15.5"/>`),
};
const KIND_ICON = {earn: "bus", bonus: "gift", redeem: "yen", restore: "back", expire: "hourglass", forfeit: "hourglass", adjust: "pen"};
const TABS = [["home","ホーム"],["history","ポイント履歴"],["tours","ツアー"],["info","ご案内"]];
const TAB_SHORT = {home:"ホーム", history:"履歴", tours:"ツアー", info:"ご案内"};
// 「？」を押すと説明が出る（説明文はふだん隠しておく）
const help = text => `<details class="help"><summary aria-label="説明を見る">?</summary><p>${text}</p></details>`;

// 会員カード（ステイタスで色が変わる）。big=true は受付で見せる全画面表示用
function memberCard(me, big = false){
  const m = me.member, r = me.rank;
  return `<div class="mcard st-${r.code} ${big ? "big" : ""}" ${big ? "" : `role="button" tabindex="0" data-card aria-label="会員証を大きく表示する"`}>
    <div class="mc-top"><span class="mc-brand">バスツアー会員</span><span class="mc-status">${esc(r.name)}</span></div>
    <div class="mc-no mono">${m.member_no.replace(/^(BT)(\d{4})(\d{4})$/, "$1 $2 $3")}</div>
    <div class="mc-foot"><span class="mc-name">${esc(m.name)} 様</span>${big ? `<span>入会 ${m.joined_on.slice(0,4)}年${Number(m.joined_on.slice(5,7))}月</span>` : `<span class="mc-tap">${ICONS.expand}</span>`}</div>
  </div>`;
}

// ステイタス：輪のグラフで次の段階までの進み具合を見せる
function statusRing(me){
  const r = me.rank, ranks = me.ranks;
  const idx = ranks.findIndex(x => x.code === r.code);
  const next = ranks[idx + 1];
  const frac = next ? Math.min(1, (r.tours - ranks[idx].need) / (next.need - ranks[idx].need)) : 1;
  const C = 2 * Math.PI * 42;
  return `<section class="card status" aria-labelledby="st-h">
    <div class="st-head"><h2 id="st-h">ステイタス</h2>${help(`直近1年のご参加回数で決まります。ステイタスが上がると、ツアーで付くポイントが増えます（${ranks.map(x => `${esc(x.name)} ${x.mult}倍`).join("・")}）。`)}</div>
    <div class="ring-wrap">
      <svg class="ring" viewBox="0 0 100 100" role="img" aria-label="直近1年の参加 ${r.tours}回${next ? `。${esc(next.name)}まであと${next.need - r.tours}回` : ""}">
        <circle cx="50" cy="50" r="42" class="ring-bg"/>
        <circle cx="50" cy="50" r="42" class="ring-fg st-${next ? next.code : r.code}" stroke-dasharray="${(C * frac).toFixed(1)} ${C.toFixed(1)}" transform="rotate(-90 50 50)"/>
        <text x="50" y="50" class="ring-num">${r.tours}<tspan class="ring-unit" dx="1">回</tspan></text>
        <text x="50" y="66" class="ring-sub">直近1年</text>
      </svg>
      <div class="ring-side">
        ${next ? `<p class="ring-next">${ICONS.medal}<span><b>${esc(next.name)}</b>まで</span></p><p class="ring-left">あと<b>${next.need - r.tours}</b>回</p>`
               : `<p class="ring-next">${ICONS.medal}<span><b>最上位</b></span></p>`}
        <ol class="medals">${ranks.map((x, i) => `<li class="m-${x.code} ${i <= idx ? "got" : ""} ${i === idx ? "here" : ""}"><i></i><span>${esc(x.name)}</span><small>${x.mult}倍</small></li>`).join("")}</ol>
      </div>
    </div>
  </section>`;
}

// 次のツアー：搭乗券のような見た目
function pass(t){
  const days = t.days ?? null;
  return `<article class="pass ${t.michi ? "michi" : ""}">
    <div class="p-date"><span>${t.depart_date.slice(0,4)}</span><b>${md(t.depart_date)}</b><span>（${weekday(t.depart_date)}）</span></div>
    <div class="p-body">
      <div class="p-top">${t.michi ? `<span class="badge rank-gold">道ツアー</span>` : ""}${days !== null ? `<span class="p-days">${days === 0 ? "本日出発" : `あと${days}日`}</span>` : ""}</div>
      <div class="p-name">${esc(t.name)}</div>
      <div class="p-rows">
        <span title="お支払い">${ICONS.yen}${num(t.pay ?? (t.price - t.points_used))}円</span>
        ${t.points_used ? `<span title="ポイント利用" class="minus">−${num(t.points_used)}</span>` : ""}
        <span title="獲得予定のポイント" class="plus">${ICONS.spark}+${num(t.gain)}</span>
      </div>
    </div>
  </article>`;
}

function inviteCard(inv, me){
  const st = inv.state.code;
  const action = st === "booked" ? `<p class="state">${ICONS.bus}<span>ご予約済み</span></p>`
    : st === "requested" ? `<p class="state">${ICONS.people}<span>ご希望を承りました。スタッフからご連絡します</span></p>`
    : `<div class="actions"><button type="button" class="btn" data-request="${inv.id}">参加を希望する</button></div>`;
  return `<section class="invite" aria-label="道ツアーへのご招待">
    <div class="st-head"><p class="inv-kicker">${ICONS.medal}<span>ご招待</span></p>${help(`直近1年で通常ツアーに${me.normal_tours}回ご参加いただいた方だけにご案内している、招待制の道ツアーです。窓口・お電話でもお申し込みいただけます。`)}</div>
    <h2>${esc(inv.tour_name)}</h2>
    <div class="inv-facts">
      <span>${ICONS.calendar}${md(inv.depart_date)}（${weekday(inv.depart_date)}）</span>
      <span>${ICONS.yen}${num(inv.price)}円</span>
      <span>${ICONS.spark}+${num(inv.bonus)}</span>
    </div>
    ${action}
  </section>`;
}

function inviteGoal(me){
  const g = me.goal;
  if (!g || !g.need) return "";
  const buses = Array.from({length: g.need}, (_, i) => `<i class="${i < g.have ? "on" : ""}">${ICONS.bus}</i>`).join("");
  return `<section class="card goal"><div class="st-head"><h2>道ツアーのご招待まで</h2>${help("通常ツアーに直近1年で決まった回数ご参加いただくと、招待制の道ツアーのご案内が届きます。")}</div>
    <div class="buses" role="img" aria-label="直近1年の通常ツアー参加 ${g.have}回">${buses}</div>
    <p class="goal-left">${g.left ? `あと<b>${g.left}</b>回` : "条件を満たしています"}</p></section>`;
}

// pt明細の行（種類ごとのアイコン・月ごとの見出し）
function statement(items){
  let month = "", out = "";
  for (const r of items){
    const mo = r.date.slice(0, 7);
    if (mo !== month){ month = mo; out += `<li class="month">${mo.slice(0,4)}年${Number(mo.slice(5,7))}月</li>`; }
    const up = r.points > 0;
    const title = r.tour || r.reason;
    out += `<li class="row"><span class="r-ico k-${esc(r.code || "")}">${ICONS[KIND_ICON[r.code] || "spark"]}</span>
      <span class="r-what">${esc(title)}<small>${md(r.date)}・${esc(r.kind)}</small></span>
      <span class="r-pt ${up ? "plus" : "minus"}">${up ? "+" : "−"}${num(Math.abs(r.points))}</span></li>`;
  }
  return `<ul class="stmt">${out}</ul>`;
}

function offlineNote(){
  if (!ui.offlineAt) return "";
  const d = new Date(ui.offlineAt);
  return `<div class="offline" role="status">${ICONS.hourglass}<span>${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, "0")} 時点の表示（電波なし）</span></div>`;
}

// --- 画面 ------------------------------------------------------------------
const views = {
  home(me){
    const R = me.rules, t = me.next_tour;
    const nearest = me.expiring[0];
    return `
    <section class="hero">${memberCard(me)}</section>
    <div class="pull">
      ${offlineNote()}${flashHtml()}
      <section class="card miles" aria-labelledby="mi-h">
        <h2 id="mi-h" class="mi-label">保有ポイント</h2>
        <p class="mi-num"><b class="num">${num(me.balance)}</b><span>pt</span></p>
        <div class="mi-yen">${ICONS.yen}<span>${num(me.balance)}円分</span>${help(`1pt＝1円として、ツアー代金に${R.redeem_unit}pt単位でお使いいただけます。ご予約のときに窓口でお申し付けください。`)}</div>
        ${me.soon ? `<p class="notice">${ICONS.hourglass}<span><b>${num(me.soon.points)}</b> pt が ${slash(me.soon.date)} に失効</span></p>` : ""}
        <dl class="mi-facts">
          <div><dt>${ICONS.medal}<span class="sr-only">ステイタス</span></dt><dd>${esc(me.rank.name)}</dd></div>
          <div><dt>${ICONS.bus}<span class="sr-only">直近1年の参加</span></dt><dd>${me.rank.tours}回</dd></div>
          <div><dt>${ICONS.hourglass}<span class="sr-only">直近の有効期限</span></dt><dd>${nearest ? slash(nearest.date) : "—"}</dd></div>
        </dl>
      </section>
      <nav class="tiles" aria-label="よく使う機能">
        <button type="button" data-card>${ICONS.card}<span>会員証</span></button>
        <button type="button" data-tab="history">${ICONS.history}<span>履歴</span></button>
        <button type="button" data-tab="tours">${ICONS.tours}<span>ツアー</span></button>
        <a href="${esc(CFG.rulesUrl)}">${ICONS.guide}<span>制度</span></a>
      </nav>
      ${me.invites.map(i => inviteCard(i, me)).join("")}
      <div class="grid two">
        <section class="card" aria-labelledby="nx-h"><div class="st-head"><h2 id="nx-h">次のツアー</h2></div>
          ${t ? pass(t) : `<p class="empty">${ICONS.bus}<span>予定なし</span></p>`}</section>
        ${statusRing(me)}
      </div>
      ${me.invites.length ? "" : inviteGoal(me)}
      <section class="card"><div class="st-head"><h2>最近のポイント</h2><button type="button" class="link" data-tab="history">すべて</button></div>
        ${me.recent.length ? statement(me.recent) : `<p class="empty">${ICONS.history}<span>まだありません</span></p>`}</section>
    </div>`;
  },

  history(me){
    const h = ui.history;
    const head = `<div class="page-title"><h1>ポイント履歴</h1></div>${offlineNote()}`;
    if (!h) return head + `<p class="loading">${ui.offlineAt ? "電波が届くところで開くと表示されます" : "読み込んでいます…"}</p>`;
    const total = Math.max(1, h.earned);
    return head + `
    <section class="card sum">
      <p class="sum-main"><span>保有</span><b>${num(me.balance)}</b><span>pt</span></p>
      <div class="sum-bar" role="img" aria-label="獲得 ${num(h.earned)}ptのうち、利用 ${num(h.used)}pt"><i class="used" style="width:${(h.used / total * 100).toFixed(1)}%"></i></div>
      <dl><div><dt>${ICONS.spark}獲得</dt><dd class="plus">+${num(h.earned)}</dd></div>
        <div><dt>${ICONS.yen}利用</dt><dd>${num(h.used)}</dd></div></dl></section>
    <section class="card">${h.items.length ? statement(h.items) : `<p class="empty">${ICONS.history}<span>まだありません</span></p>`}</section>`;
  },

  tours(me){
    const ts = ui.tours;
    const head = `<div class="page-title"><h1>ツアー</h1></div>${offlineNote()}${flashHtml()}${me.invites.map(i => inviteCard(i, me)).join("")}`;
    if (!ts) return head + `<p class="loading">${ui.offlineAt ? "電波が届くところで開くと表示されます" : "読み込んでいます…"}</p>`;
    const today = me.today;
    const past = t => `<li class="row"><span class="r-ico ${t.status === "completed" ? "k-earn" : "k-off"}">${ICONS.bus}</span>
      <span class="r-what">${esc(t.name)}<small>${slash(t.depart_date)}・${esc(t.status_label)}${t.michi ? "・道ツアー" : ""}</small></span>
      <span class="r-pt ${t.status === "completed" ? "plus" : "muted"}">${t.status === "completed" ? `+${num(t.earned)}` : "—"}</span></li>`;
    return head + `
    <section class="card"><div class="st-head"><h2>参加予定</h2></div>
      ${ts.upcoming.map(t => pass({...t, days: Math.round((parse(t.depart_date) - parse(today)) / 864e5)})).join("") || `<p class="empty">${ICONS.bus}<span>予定なし</span></p>`}</section>
    <section class="card"><div class="st-head"><h2>これまで</h2></div>
      ${ts.past.length ? `<ul class="stmt">${ts.past.map(past).join("")}</ul>` : `<p class="empty">${ICONS.bus}<span>まだありません</span></p>`}</section>`;
  },

  info(me){
    const R = me.rules;
    const earn = [["bus", `${R.yen_per_point}円`, "1pt"], ["medal", "ステイタス", `最大${Math.max(...me.ranks.map(x => x.mult))}倍`],
                  ["cake", "誕生月", `+${num(R.birthday)}`], ["people", "ご紹介", `+${num(R.referral)}`]];
    return `<div class="page-title"><h1>ご案内</h1></div>
    ${offlineNote()}${flashHtml()}
    <div class="grid two-even">
      <section class="card"><div class="st-head"><h2>ポイントのため方</h2>${help(`ツアー代金（ポイントで払った分を除く）${R.yen_per_point}円ごとに1ptに、ステイタスの倍率をかけて、ツアー終了後に付与します。キャンペーン対象ツアーはポイントが増えます。`)}</div>
        <ul class="earn">${earn.map(([ic, a, b]) => `<li>${ICONS[ic]}<span>${esc(a)}</span><b>${esc(b)}</b></li>`).join("")}</ul>
        <p class="small"><a href="${esc(CFG.rulesUrl)}">くわしいご案内</a></p></section>
      <section class="card"><div class="st-head"><h2>有効期限</h2>${help(`付与日から${R.expiry_years}年後の月末まで有効です。期限の近いものから使われます。`)}</div>${
        me.expiring.length ? `<ul class="exp">${me.expiring.map(x => `<li>${ICONS.hourglass}<span>${slash(x.date)}</span><b>${num(x.points)}</b></li>`).join("")}</ul>` : `<p class="empty">${ICONS.hourglass}<span>有効なポイントなし</span></p>`}</section>
      ${installCard()}
      <section class="card"><div class="st-head"><h2>暗証番号の変更</h2>${help("4〜8桁の数字。変えると、ほかのスマートフォンなどでのログインは解除されます。")}</div><form class="stack" data-form="pin">
        <label class="field"><span>現在の暗証番号</span><input class="input" name="current" type="password" inputmode="numeric" autocomplete="current-password" required></label>
        <label class="field"><span>新しい暗証番号</span><input class="input" name="next" type="password" inputmode="numeric" autocomplete="new-password" required></label>
        <div><button class="btn">変更する</button></div></form></section>
      <section class="card"><div class="st-head"><h2>会員情報</h2>${help("ご登録内容の変更・退会はツアー窓口で承ります。")}</div><dl class="kv"><dt>会員番号</dt><dd class="mono">${me.member.member_no}</dd><dt>入会日</dt><dd>${slash(me.member.joined_on)}</dd></dl>
        <div><button type="button" class="btn ghost" data-act="logout">ログアウト</button></div></section>
    </div>`;
  },

  login(){
    return `<div class="login">
      <section class="hero"><div class="lg-head"><span class="brand">バスツアー会員</span>${CFG.badge}</div>
        <div class="lg-mark">${ICONS.card}</div><h1>ログイン</h1></section>
      <main class="pull">
        ${flashHtml()}
        <section class="card">
          <form class="stack" data-form="login">
            <label class="field"><span>会員番号</span><input class="input mono" name="member_no" autocomplete="username" autocapitalize="characters" placeholder="BT00000017" required></label>
            <label class="field"><span>暗証番号</span><input class="input" name="pin" type="password" inputmode="numeric" autocomplete="current-password" required></label>
            <button class="btn block">ログイン</button>
          </form>
          <div class="st-head"><span class="small muted">会員番号は会員証に書いてあります</span>${help("暗証番号を忘れた方は、ツアー窓口で再設定いたします。")}</div></section>
        ${CFG.loginHelp}
        ${installCard()}
        <p class="small"><a href="${esc(CFG.rulesUrl)}">ポイント制度のご案内</a></p>
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
  return `<section class="card install"><div class="st-head"><h2>${ICONS.tap}ホーム画面に追加</h2>${help("ホーム画面に追加すると、次からはアイコンを押すだけで会員証を開けます。")}</div>${steps}</section>`;
}

// 受付で見せる会員証（全画面）
function openCard(){
  if (!ui.me) return;
  let dlg = document.getElementById("cardview");
  if (!dlg){ dlg = document.createElement("dialog"); dlg.id = "cardview"; document.body.appendChild(dlg); }
  dlg.innerHTML = `<div class="cv">
    <p class="cv-title">会員証</p>
    ${memberCard(ui.me, true)}
    <p class="cv-miles">保有 <b>${num(ui.me.balance)}</b> pt</p>
    <p class="cv-note">${ICONS.bus}<span>受付でお見せください</span></p>
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
