// バスツアー会員ポイント：制度の計算ロジック（ブラウザ版）。
// スタッフ画面（index.html）と会員スマホ画面（member/index.html）で共用する。
// 計算ルールは Python 版 points/ と同じ。データはこのブラウザの localStorage だけに保存する。
"use strict";
// ===== 制度ルール（Python版 points/rules.py と同じ値） =====
const RULES = {
  YEN_PER_POINT: 100, WELCOME_BONUS: 300, BIRTHDAY_BONUS: 200, REFERRAL_BONUS: 500,
  RANKS: [["regular","レギュラー",0,1.0],["silver","シルバー",3,1.5],["gold","ゴールド",6,2.0]],
  RANK_WINDOW_DAYS: 365, REDEEM_UNIT: 100, EXPIRY_YEARS: 2,
};
const KIND = {earn:"ツアー参加",bonus:"特典",redeem:"利用",restore:"返還",expire:"失効",adjust:"調整",forfeit:"退会失効"};
const BOOKING = {booked:"参加予定",completed:"参加済",no_show:"不参加",cancelled:"取消"};
const TOUR = {scheduled:"催行予定",completed:"催行完了",cancelled:"中止"};
const STORE_KEY = "bt-points-demo-v1";

class PointError extends Error {}

// ===== 日付 =====
const pad = n => String(n).padStart(2, "0");
const isoOf = d => `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())}`;
const parse = s => { const [y,m,d] = s.split("-").map(Number); return new Date(Date.UTC(y, m-1, d)); };
const addDays = (s, n) => { const d = parse(s); d.setUTCDate(d.getUTCDate()+n); return isoOf(d); };
const localToday = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`; };
function expiryDate(granted){
  const [y,m] = granted.split("-").map(Number);
  return isoOf(new Date(Date.UTC(y + RULES.EXPIRY_YEARS, m, 0)));  // 2年後の月末
}
const yen = n => n.toLocaleString("ja-JP");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

// ===== 会員番号（Luhn チェックディジット） =====
function checkDigit(digits){
  let total = 0;
  [...digits].reverse().forEach((ch, i) => { let n = +ch; if (i % 2 === 0){ n *= 2; if (n > 9) n -= 9; } total += n; });
  return String((10 - total % 10) % 10);
}
const makeMemberNo = seq => { const body = String(seq).padStart(7,"0"); return "BT" + body + checkDigit(body); };
function normalizeMemberNo(text){
  const s = String(text || "").trim().toUpperCase().replace(/[-\s]/g, "");
  if (!/^BT\d{8}$/.test(s)) throw new PointError("会員番号の形式が正しくありません（例: BT00000018）");
  if (checkDigit(s.slice(2,9)) !== s[9]) throw new PointError("会員番号が正しくありません。入力内容をご確認ください");
  return s;
}

// ===== データ =====
let db;
const emptyDb = () => ({seq:{member:0,tour:0,booking:0,txn:0,lot:0}, members:[], tours:[], bookings:[], txns:[], lots:[], usages:[]});
const nextId = k => ++db.seq[k];
function save(){ try { localStorage.setItem(STORE_KEY, JSON.stringify({db, today})); } catch (e) {} }
function load(){
  try { const raw = localStorage.getItem(STORE_KEY); if (raw){ const v = JSON.parse(raw); return v; } } catch (e) {}
  return null;
}
// 変更系の処理は失敗したら丸ごと元に戻す（DBのトランザクション相当）
function tx(fn){
  const backup = JSON.stringify(db);
  try { const r = fn(); save(); return r; } catch (e) { db = JSON.parse(backup); throw e; }
}

const memberById = id => db.members.find(m => m.id === id);
function getMember(no){
  const m = db.members.find(m => m.member_no === normalizeMemberNo(no));
  if (!m) throw new PointError("該当する会員が見つかりません");
  return m;
}
function getTour(id){
  const t = db.tours.find(t => t.id === id);
  if (!t) throw new PointError("ツアーが見つかりません");
  return t;
}

// ===== 残高・台帳 =====
const balance = (mid, d) => db.lots.filter(l => l.member_id === mid && l.expires_on >= d).reduce((a,l) => a + l.remaining, 0);
function expiringSchedule(mid, d){
  const map = new Map();
  db.lots.filter(l => l.member_id === mid && l.expires_on >= d && l.remaining > 0)
    .forEach(l => map.set(l.expires_on, (map.get(l.expires_on) || 0) + l.remaining));
  return [...map].sort((a,b) => a[0] < b[0] ? -1 : 1);
}
function addTxn(mid, kind, points, reason, d, booking_id = null, operator = ""){
  const t = {id:nextId("txn"), member_id:mid, kind, points, reason, booking_id, created_on:d, operator};
  db.txns.push(t); return t.id;
}
function grant(mid, kind, points, reason, d, booking_id, operator){
  if (points <= 0) return null;
  const txn = addTxn(mid, kind, points, reason, d, booking_id, operator);
  db.lots.push({id:nextId("lot"), member_id:mid, txn_id:txn, amount:points, remaining:points, granted_on:d, expires_on:expiryDate(d)});
  return txn;
}
// 有効期限の近い付与分から順に消費
function consume(mid, kind, points, reason, d, booking_id, operator){
  if (points <= 0) return null;
  if (balance(mid, d) < points) throw new PointError("ポイント残高が不足しています");
  const txn = addTxn(mid, kind, -points, reason, d, booking_id, operator);
  let left = points;
  const lots = db.lots.filter(l => l.member_id === mid && l.expires_on >= d && l.remaining > 0)
    .sort((a,b) => a.expires_on === b.expires_on ? a.id - b.id : (a.expires_on < b.expires_on ? -1 : 1));
  for (const lot of lots){
    const use = Math.min(left, lot.remaining);
    lot.remaining -= use; db.usages.push({txn_id:txn, lot_id:lot.id, points:use}); left -= use;
    if (!left) break;
  }
  return txn;
}

// ===== 会員 =====
function registerMember({name, pin, kana = "", phone = "", email = "", birthdate = "", referrer_no = ""}, d, op = ""){
  name = (name || "").trim();
  if (!name) throw new PointError("氏名は必須です");
  if (!/^\d{4,8}$/.test(pin || "")) throw new PointError("暗証番号は4〜8桁の数字で設定してください");
  return tx(() => {
    let referrer_id = null;
    if (referrer_no){
      const ref = getMember(referrer_no);
      if (ref.status !== "active") throw new PointError("紹介者の会員番号は現在有効ではありません");
      referrer_id = ref.id;
    }
    const id = nextId("member");
    const m = {id, member_no:makeMemberNo(id), name, kana:kana.trim(), phone:phone.trim(), email:email.trim(),
               birthdate:birthdate || null, pin, referrer_id, status:"active", joined_on:d};
    db.members.push(m);
    grant(id, "bonus", RULES.WELCOME_BONUS, "入会特典", d, null, op);
    return m;
  });
}
function authenticate(no, pin){
  let m; try { m = getMember(no); } catch (e) { return null; }
  return m.status === "active" && m.pin === pin ? m : null;
}
function rankFor(mid, on){
  const start = addDays(on, -RULES.RANK_WINDOW_DAYS);
  const count = db.bookings.filter(b => b.member_id === mid && b.status === "completed").map(b => getTour(b.tour_id))
    .filter(t => t.depart_date >= start && t.depart_date < on).length;
  let cur = RULES.RANKS[0];
  for (const r of RULES.RANKS) if (count >= r[2]) cur = r;
  const next = RULES.RANKS.find(r => r[2] > count);
  return {code:cur[0], name:cur[1], multiplier:cur[3], tours:count, next_name:next ? next[1] : null, tours_to_next:next ? next[2]-count : 0};
}
function adjustPoints(no, points, reason, d, op){
  reason = (reason || "").trim();
  if (!reason) throw new PointError("調整理由を入力してください");
  if (!Number.isInteger(points) || points === 0) throw new PointError("調整ポイントを整数で入力してください");
  tx(() => {
    const m = getMember(no);
    if (m.status !== "active") throw new PointError("退会済み会員のポイントは調整できません");
    if (points > 0) grant(m.id, "adjust", points, reason, d, null, op);
    else consume(m.id, "adjust", -points, reason, d, null, op);
  });
}
function withdrawMember(no, d, op){
  tx(() => {
    const m = getMember(no);
    if (m.status !== "active") throw new PointError("すでに退会済みです");
    if (db.bookings.some(b => b.member_id === m.id && b.status === "booked"))
      throw new PointError("参加予定のツアーがあるため退会できません。先に予約を取り消してください");
    const bal = balance(m.id, d);
    if (bal) consume(m.id, "forfeit", bal, "退会による失効", d, null, op);
    m.status = "withdrawn";
  });
}
function expirePoints(d){
  let total = 0;
  tx(() => {
    const byMember = new Map();
    db.lots.filter(l => l.expires_on < d && l.remaining > 0).forEach(l => {
      if (!byMember.has(l.member_id)) byMember.set(l.member_id, []); byMember.get(l.member_id).push(l);
    });
    for (const [mid, lots] of byMember){
      const pts = lots.reduce((a,l) => a + l.remaining, 0);
      const txn = addTxn(mid, "expire", -pts, "有効期限切れによる失効", d, null, "system");
      lots.forEach(l => { db.usages.push({txn_id:txn, lot_id:l.id, points:l.remaining}); l.remaining = 0; });
      total += pts;
    }
  });
  return total;
}

// ===== ツアー・予約 =====
function createTour({code, name, depart_date, price, bonus_multiplier = 1, bonus_points = 0}){
  code = (code || "").trim(); name = (name || "").trim();
  if (!code || !name || !depart_date) throw new PointError("ツアーコード・ツアー名・出発日は必須です");
  if (!(price > 0)) throw new PointError("代金は1円以上で入力してください");
  if (!(bonus_multiplier >= 1) || !(bonus_points >= 0)) throw new PointError("キャンペーン倍率は1以上、加算ポイントは0以上で入力してください");
  if (db.tours.some(t => t.code === code)) throw new PointError("同じツアーコードがすでに登録されています");
  return tx(() => { const t = {id:nextId("tour"), code, name, depart_date, price, bonus_multiplier, bonus_points, status:"scheduled"}; db.tours.push(t); return t; });
}
function maxRedeemable(mid, price, d){
  const b = Math.min(balance(mid, d), price);
  return b - b % RULES.REDEEM_UNIT;
}
function bookTour(no, tourId, points, d, op){
  return tx(() => {
    const m = getMember(no);
    if (m.status !== "active") throw new PointError("退会済みの会員です");
    const t = getTour(tourId);
    if (t.status !== "scheduled") throw new PointError("このツアーは予約を受け付けていません");
    if (db.bookings.some(b => b.member_id === m.id && b.tour_id === tourId && b.status !== "cancelled"))
      throw new PointError("この会員はすでにこのツアーを予約しています");
    if (!Number.isInteger(points) || points < 0 || points % RULES.REDEEM_UNIT)
      throw new PointError(`ポイントは${RULES.REDEEM_UNIT}ポイント単位でご利用いただけます`);
    if (points > maxRedeemable(m.id, t.price, d)) throw new PointError("利用ポイントが残高またはツアー代金を超えています");
    const b = {id:nextId("booking"), member_id:m.id, tour_id:tourId, price:t.price, points_used:points, status:"booked", booked_on:d};
    db.bookings.push(b);
    if (points) consume(m.id, "redeem", points, `ツアー代金に利用（${t.name}）`, d, b.id, op);
    return b;
  });
}
// 利用ポイントを元の付与分（元の有効期限）へ戻す
function restorePoints(b, d, op){
  const redeemTxns = db.txns.filter(t => t.booking_id === b.id && t.kind === "redeem").map(t => t.id);
  const uses = db.usages.filter(u => redeemTxns.includes(u.txn_id));
  const total = uses.reduce((a,u) => a + u.points, 0);
  if (!total) return;
  addTxn(b.member_id, "restore", total, "予約取消によるポイント返還", d, b.id, op);
  uses.forEach(u => { db.lots.find(l => l.id === u.lot_id).remaining += u.points; });
}
function cancelBooking(id, d, op){
  tx(() => {
    const b = db.bookings.find(b => b.id === id);
    if (!b) throw new PointError("予約が見つかりません");
    if (b.status !== "booked") throw new PointError("参加予定の予約のみ取り消せます");
    b.status = "cancelled"; restorePoints(b, d, op);
  });
}
function cancelTour(id, d, op){
  tx(() => {
    const t = getTour(id);
    if (t.status !== "scheduled") throw new PointError("催行予定のツアーのみ中止できます");
    db.bookings.filter(b => b.tour_id === id && b.status === "booked").forEach(b => { b.status = "cancelled"; restorePoints(b, d, op); });
    t.status = "cancelled";
  });
}
function estimateEarn(m, t, paid){
  const rank = rankFor(m.id, t.depart_date);
  const base = Math.floor(paid / RULES.YEN_PER_POINT);
  const items = [["基本", Math.floor(base * rank.multiplier * t.bonus_multiplier + 1e-9)]];
  if (t.bonus_points) items.push(["キャンペーン加算", t.bonus_points]);
  if (m.birthdate && m.birthdate.slice(5,7) === t.depart_date.slice(5,7)) items.push(["誕生月特典", RULES.BIRTHDAY_BONUS]);
  return {rank, items};
}
function completeTour(id, d, op, absent = []){
  let granted = 0;
  tx(() => {
    const t = getTour(id);
    if (t.status !== "scheduled") throw new PointError("催行予定のツアーのみ完了処理できます");
    if (t.depart_date > d) throw new PointError("出発日より前に完了処理はできません");
    for (const b of db.bookings.filter(b => b.tour_id === id && b.status === "booked")){
      if (absent.includes(b.id)){ b.status = "no_show"; continue; }
      const m = memberById(b.member_id);
      const first = !db.bookings.some(x => x.member_id === m.id && x.status === "completed");
      const {rank, items} = estimateEarn(m, t, b.price - b.points_used);
      b.status = "completed";
      if (m.status !== "active") continue;
      for (const [label, pts] of items){
        let kind = "bonus", reason = `ツアー参加 ${label}`;
        if (label === "基本"){
          let detail = `${rank.name}×${rank.multiplier}`;
          if (t.bonus_multiplier !== 1) detail += `・キャンペーン×${t.bonus_multiplier}`;
          kind = "earn"; reason += `（${detail}）`;
        }
        if (grant(m.id, kind, pts, reason, d, b.id, op)) granted += pts;
      }
      if (first && m.referrer_id){
        const ref = memberById(m.referrer_id);
        if (ref.status === "active"){ grant(ref.id, "bonus", RULES.REFERRAL_BONUS, `ご紹介特典（${m.name}様 初参加）`, d, null, op); granted += RULES.REFERRAL_BONUS; }
      }
    }
    t.status = "completed";
  });
  return granted;
}

// ===== サンプルデータ =====
function seed(base){
  db = emptyDb();
  const back = n => addDays(base, -n);
  const hanako = registerMember({name:"山田 花子", kana:"ヤマダ ハナコ", phone:"090-1234-5678", pin:"1234", birthdate:`1958-${back(30).slice(5,7)}-15`}, back(230), "サンプル");
  const taro = registerMember({name:"鈴木 太郎", kana:"スズキ タロウ", phone:"080-2222-3333", pin:"5678", referrer_no:hanako.member_no}, back(130), "サンプル");
  const ichiro = registerMember({name:"佐藤 一郎", kana:"サトウ イチロウ", phone:"070-4444-5555", pin:"2468", birthdate:"1951-02-03"}, back(420), "サンプル");
  const past = [["2025-H01","初夏の富士五湖めぐり",330,9800],["2025-H02","上高地ハイキング日帰り",270,11800],["2025-H03","秋の京都 紅葉ライトアップ",210,19800],
                ["2025-H04","いちご狩りと温泉の旅",150,8900],["2025-H05","河津桜と伊豆の海鮮",90,10800],["2025-H06","しだれ桜の名所めぐり",60,9800]];
  for (const [code, name, ago, price] of past){
    const t = createTour({code, name, depart_date:back(ago), price});
    bookTour(ichiro.member_no, t.id, 0, back(ago + 14), "サンプル");
    completeTour(t.id, back(ago), "サンプル");
  }
  const t1 = createTour({code:"2026-NIKKO", name:"紅葉の日光・鬼怒川 日帰りバスツアー", depart_date:back(30), price:12800});
  bookTour(hanako.member_no, t1.id, 0, back(50), "サンプル");
  bookTour(taro.member_no, t1.id, 300, back(50), "サンプル");
  bookTour(ichiro.member_no, t1.id, 1000, back(50), "サンプル");
  completeTour(t1.id, back(30), "サンプル");
  const t2 = createTour({code:"2026-KANI", name:"冬の味覚 カニ食べ放題ツアー（ポイント2倍）", depart_date:addDays(base, 40), price:15800, bonus_multiplier:2});
  bookTour(hanako.member_no, t2.id, 500, base, "サンプル");
  bookTour(ichiro.member_no, t2.id, 0, base, "サンプル");
  createTour({code:"2026-HAKONE", name:"箱根 彫刻の森と芦ノ湖遊覧", depart_date:addDays(base, 18), price:9800, bonus_points:100});
}

// ===== 起動 =====
let today = localToday();
// 保存済みデータがあれば読み込み、なければサンプルデータを作る
function bootData(){
  const saved = load();
  if (saved && saved.db && saved.db.seq){ db = saved.db; today = saved.today || today; }
  else { seed(today); save(); }
}
