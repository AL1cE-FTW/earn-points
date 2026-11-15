// 会員アプリ（PWA）。スマホの画面を基準に作り、PC でも同じ1列を中央に出す。
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
  links: [],                 // ご案内の下に出すリンク [[文字, URL], ...]
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
  chev: I(`<path d="m9 6 6 6-6 6"/>`),
  tap: I(`<path d="M9 11V5.5a1.5 1.5 0 0 1 3 0V11l.5-1.2a1.5 1.5 0 0 1 2.8.9v.5l.3-.5a1.5 1.5 0 0 1 2.8 1V15a6 6 0 0 1-6 6h-.5a6 6 0 0 1-4.6-2.2L5 15.5a1.5 1.5 0 0 1 2.3-1.9L9 15.5"/>`),
};
const KIND_ICON = {earn: "bus", bonus: "gift", redeem: "yen", restore: "back", expire: "hourglass", forfeit: "hourglass", adjust: "pen"};
const TABS = [["home","ホーム"],["history","ポイント履歴"],["tours","ツアー"],["info","ご案内"]];
const TAB_SHORT = {home:"ホーム", history:"履歴", tours:"ツアー", info:"ご案内"};
// 「？」を押すと説明が出る（説明文はふだん隠しておく）
const help = text => `<details class="help"><summary aria-label="説明を見る">?</summary><p>${text}</p></details>`;

// 会員番号のバーコード（CODE39。窓口のバーコードリーダーで読める）
const CODE39 = {"0":"101000111011101","1":"111010001010111","2":"101110001010111","3":"111011100010101","4":"101000111010111","5":"111010001110101","6":"101110001110101","7":"101000101110111","8":"111010001011101","9":"101110001011101","A":"111010100010111","B":"101110100010111","C":"111011101000101","D":"101011100010111","E":"111010111000101","F":"101110111000101","G":"101010001110111","H":"111010100011101","I":"101110100011101","J":"101011100011101","K":"111010101000111","L":"101110101000111","M":"111011101010001","N":"101011101000111","O":"111010111010001","P":"101110111010001","Q":"101010111000111","R":"111010101110001","S":"101110101110001","T":"101011101110001","U":"111000101010111","V":"100011101010111","W":"111000111010101","X":"100010111010111","Y":"111000101110101","Z":"100011101110101","-":"100010101110111","*":"100010111011101"};
function code39Modules(text){
  return ["*", ...String(text).toUpperCase(), "*"].map(c => CODE39[c] || "").join("0");
}
function barcodeSvg(text){
  const mods = code39Modules(text), q = 12, w = mods.length + q * 2;
  let x = q, rects = "";
  for (let i = 0; i < mods.length; i++){
    if (mods[i] !== "1") continue;
    let n = 1; while (mods[i + n] === "1") n++;
    rects += `<rect x="${q + i}" y="0" width="${n}" height="40"/>`; i += n - 1;
  }
  return `<svg class="barcode" viewBox="0 0 ${w} 40" preserveAspectRatio="none" role="img" aria-label="会員番号 ${esc(text)} のバーコード" shape-rendering="crispEdges"><rect width="${w}" height="40" fill="#fff"/><g fill="#000">${rects}</g></svg>`;
}
const spacedNo = no => no.replace(/^(BT)(\d{4})(\d{4})$/, "$1 $2 $3");

// 会員証：トップにいつも出しておくバーコード。押すと大きく表示する
function idCard(me){
  const m = me.member, r = me.rank;
  return `<section class="card idcard" data-card role="button" tabindex="0" aria-label="会員証のバーコードを大きく表示する">
    <div class="id-head"><span class="id-title">${ICONS.card}会員証</span><span class="stage-chip st-${r.code}">${esc(r.name)}</span><span class="id-zoom">${ICONS.expand}</span></div>
    <div class="bc">${barcodeSvg(m.member_no)}</div>
    <div class="id-foot"><span class="mono">${spacedNo(m.member_no)}</span><span>${esc(m.name)} 様</span></div>
  </section>`;
}

// ステイタス：次の段階までの進み具合をバーで見せる
function stageCard(me){
  const r = me.rank, ranks = me.ranks;
  const idx = ranks.findIndex(x => x.code === r.code);
  const next = ranks[idx + 1];
  const pct = next ? Math.round(Math.min(1, r.tours / next.need) * 100) : 100;
  return `<section class="card stage" aria-labelledby="st-h">
    <div class="st-head"><h2 id="st-h">ステイタス</h2>${help(`直近1年のご参加回数で決まります。ステイタスが上がると、ツアーで付くポイントが増えます（${ranks.map(x => `${esc(x.name)} ${x.mult}倍`).join("・")}）。`)}</div>
    <div class="stage-now"><span class="stage-chip big st-${r.code}">${esc(r.name)}</span><span class="stage-mult">ポイント <b>${r.multiplier}</b>倍</span></div>
    <div class="bar" role="img" aria-label="直近1年の参加 ${r.tours}回${next ? `。${esc(next.name)}まであと${next.need - r.tours}回` : ""}"><i style="width:${pct}%"></i></div>
    <div class="bar-legend"><span>${ICONS.bus}${r.tours}回</span><span>${next ? `${esc(next.name)}まで あと<b>${next.need - r.tours}</b>回` : "最上位"}</span></div>
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
    ${offlineNote()}${flashHtml()}
    ${idCard(me)}
    <section class="card pts" aria-labelledby="pt-h">
      <div class="st-head"><h2 id="pt-h">保有ポイント</h2><button type="button" class="more" data-tab="history">履歴${ICONS.chev}</button></div>
      <p class="pts-num"><b class="num">${num(me.balance)}</b><span>pt</span></p>
      <ul class="pts-sub">
        <li>${ICONS.yen}<span>${num(me.balance)}円分 使える</span>${help(`1pt＝1円として、ツアー代金に${R.redeem_unit}pt単位でお使いいただけます。ご予約のときに窓口でお申し付けください。`)}</li>
        ${nearest ? `<li class="${me.soon ? "warn" : ""}">${ICONS.hourglass}<span>${slash(nearest.date)}まで ${num(nearest.points)}pt</span></li>` : ""}
      </ul>
    </section>
    ${stageCard(me)}
    ${me.invites.map(i => inviteCard(i, me)).join("") || inviteGoal(me)}
    <section class="card" aria-labelledby="nx-h"><div class="st-head"><h2 id="nx-h">次のツアー</h2><button type="button" class="more" data-tab="tours">一覧${ICONS.chev}</button></div>
      ${t ? pass(t) : `<p class="empty">${ICONS.bus}<span>予定なし</span></p>`}</section>
    <nav class="tiles" aria-label="メニュー">
      <button type="button" data-card>${ICONS.card}<span>会員証</span></button>
      <button type="button" data-tab="history">${ICONS.history}<span>履歴</span></button>
      <button type="button" data-tab="tours">${ICONS.tours}<span>ツアー</span></button>
      <a href="${esc(CFG.rulesUrl)}">${ICONS.guide}<span>制度</span></a>
    </nav>
    <section class="card"><div class="st-head"><h2>最近のポイント</h2><button type="button" class="more" data-tab="history">すべて${ICONS.chev}</button></div>
      ${me.recent.length ? statement(me.recent) : `<p class="empty">${ICONS.history}<span>まだありません</span></p>`}</section>`;
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
    <div class="grid">
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
        <div><button type="button" class="btn ghost" data-act="logout">ログアウト</button></div>
        ${CFG.links.length ? `<p class="small">${CFG.links.map(([l, u]) => `<a href="${esc(u)}">${esc(l)}</a>`).join("　")}</p>` : ""}</section>
    </div>`;
  },

  login(){
    return `<div class="login">
      <header class="appbar"><div class="bar-in"><span class="brand">バスツアー会員</span>${CFG.badge}</div></header>
      <main>
        <div class="st-head"><span class="lg-mark">${ICONS.card}</span><h1>ログイン</h1></div>
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

// 受付で見せる会員証（全画面）。読み取りやすいよう白地に大きなバーコード
function openCard(){
  if (!ui.me) return;
  const m = ui.me.member, r = ui.me.rank;
  let dlg = document.getElementById("cardview");
  if (!dlg){ dlg = document.createElement("dialog"); dlg.id = "cardview"; document.body.appendChild(dlg); }
  dlg.innerHTML = `<div class="cv">
    <div class="cv-card">
      <div class="id-head"><span class="id-title">${ICONS.card}会員証</span><span class="stage-chip st-${r.code}">${esc(r.name)}</span></div>
      <div class="bc big">${barcodeSvg(m.member_no)}</div>
      <p class="cv-no mono">${spacedNo(m.member_no)}</p>
      <p class="cv-name">${esc(m.name)} 様</p>
      <p class="cv-pt">保有 <b>${num(ui.me.balance)}</b> pt</p>
    </div>
    <p class="cv-note">${ICONS.bus}<span>受付でお見せください</span></p>
    <form method="dialog"><button class="btn block">閉じる</button></form></div>`;
  if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
}

function render(){
  if (ui.loading) return;
  const me = ui.me;
  if (!me){ root.innerHTML = views.login(); document.title = "ログイン｜バスツアー会員"; ui.flash = null; return; }
  root.innerHTML = `<div class="app signed tab-${ui.tab}">
    <header class="appbar"><div class="bar-in"><span class="brand">バスツアー会員</span>${CFG.badge}${ui.tab === "home" ? "" : `<button type="button" class="cardbtn" data-card aria-label="会員証を表示">${ICONS.card}<span>会員証</span></button>`}</div></header>
    <main id="main">${views[ui.tab](me)}</main>
  </div>
  <nav class="tabbar" aria-label="メニュー"><div class="tabs">${TABS.map(([k]) => `<button type="button" class="navbtn" data-tab="${k}" ${ui.tab === k ? 'aria-current="page"' : ""}>${ICONS[k]}<span>${TAB_SHORT[k]}</span></button>`).join("")}</div></nav>`;
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
document.addEventListener("keydown", e => { if ((e.key === "Enter" || e.key === " ") && e.target.matches && e.target.matches(".idcard[data-card]")){ e.preventDefault(); openCard(); } });

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
