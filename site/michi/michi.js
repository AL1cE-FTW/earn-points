// 提案版：招待制「道ツアー」の追加ロジック。../points.js の後に読み込む。
// 仕様は docs/提案.md の「段階1」（LINE なし）。数値はまだ決まっていないため「仮」の値。
// データは現行版のデモと混ざらないよう、別の保存先（MICHI_KEY）に置く。
"use strict";

const MICHI_KEY = "bt-points-michi-v1";
const MICHI = {
  DEFAULT_MIN_TOURS: 3,   // 仮：直近1年で通常ツアーに何回参加したら招待するか
  DEFAULT_BONUS: 1000,    // 仮：道ツアー参加の特典ポイント
  WINDOW_DAYS: 365,
};
const TOUR_KIND = {normal:"通常ツアー", michi:"道ツアー"};
const CONTACT = {app:"会員アプリ", phone:"電話", mail:"郵送"};

// 保存先を現行版と分ける（points.js の save / load を置き換える）
function save(){ try { localStorage.setItem(MICHI_KEY, JSON.stringify({db, today})); } catch (e) {} }
function load(){ try { const raw = localStorage.getItem(MICHI_KEY); if (raw) return JSON.parse(raw); } catch (e) {} return null; }

const isMichi = t => t.kind === "michi";

// 道ツアーの特典は「キャンペーン加算」ではなく「道ツアー特典」と表示する（points.js の estimateEarn を置き換える）
function estimateEarn(m, t, paid){
  const rank = rankFor(m.id, t.depart_date);
  const base = Math.floor(paid / RULES.YEN_PER_POINT);
  const items = [["基本", Math.floor(base * rank.multiplier * t.bonus_multiplier + 1e-9)]];
  if (t.bonus_points) items.push([isMichi(t) ? "道ツアー特典" : "キャンペーン加算", t.bonus_points]);
  if (m.birthdate && m.birthdate.slice(5,7) === t.depart_date.slice(5,7)) items.push(["誕生月特典", RULES.BIRTHDAY_BONUS]);
  return {rank, items};
}

// 直近1年に参加完了した「通常ツアー」の回数（招待条件の判定に使う）
function normalToursIn(mid, on){
  const start = addDays(on, -MICHI.WINDOW_DAYS);
  return db.bookings.filter(b => b.member_id === mid && b.status === "completed").map(b => getTour(b.tour_id))
    .filter(t => !isMichi(t) && t.depart_date >= start && t.depart_date <= on).length;
}

function createTourEx({kind = "normal", invite_min_tours, ...rest}){
  if (kind === "michi"){
    const n = invite_min_tours ?? MICHI.DEFAULT_MIN_TOURS;
    if (!Number.isInteger(n) || n < 1) throw new PointError("招待条件の参加回数は1以上の整数で入力してください");
    if (rest.bonus_points === undefined) rest.bonus_points = MICHI.DEFAULT_BONUS;
    const t = createTour(rest);
    return tx(() => { const x = getTour(t.id); x.kind = "michi"; x.invite_min_tours = n; return x; });
  }
  return createTour(rest);
}

const invitesOf = tourId => (db.invites || []).filter(i => i.tour_id === tourId);
const inviteFor = (tourId, mid) => (db.invites || []).find(i => i.tour_id === tourId && i.member_id === mid);
const activeBooking = (tourId, mid) => db.bookings.find(b => b.tour_id === tourId && b.member_id === mid && b.status !== "cancelled");

// 招待条件を満たす会員（有効会員のみ）
function eligibleFor(tour, d){
  return db.members.filter(m => m.status === "active")
    .map(m => ({m, count: normalToursIn(m.id, d)}))
    .filter(x => x.count >= tour.invite_min_tours)
    .sort((a,b) => b.count - a.count);
}

// 招待の状態（記録から毎回求める）
function inviteState(inv){
  if (!inv) return {code:"none", label:"未招待"};
  const b = activeBooking(inv.tour_id, inv.member_id);
  if (b) return {code:"booked", label: b.status === "completed" ? "参加済" : "予約済"};
  if (inv.requested_on) return {code:"requested", label:"参加希望"};
  const ch = inv.contacts.map(c => CONTACT[c.channel]).join("・");
  return {code:"invited", label:`案内済（${ch}）`};
}

// 条件を満たし、まだ招待していない会員に招待を出す（会員アプリに表示される）
function sendInvites(tourId, d, op){
  return tx(() => {
    const t = getTour(tourId);
    if (!isMichi(t) || t.status !== "scheduled") throw new PointError("催行予定の道ツアーのみ招待できます");
    db.invites = db.invites || [];
    let n = 0;
    for (const {m} of eligibleFor(t, d)){
      if (inviteFor(t.id, m.id)) continue;
      db.invites.push({id: nextId("invite"), tour_id: t.id, member_id: m.id, invited_on: d, operator: op,
                       contacts: [{channel:"app", on:d}], requested_on: null});
      n++;
    }
    return n;
  });
}

// 電話・郵送で案内したことを記録する
function markContacted(inviteId, channel, d){
  tx(() => {
    const inv = (db.invites || []).find(i => i.id === inviteId);
    if (!inv) throw new PointError("招待が見つかりません");
    if (!inv.contacts.some(c => c.channel === channel)) inv.contacts.push({channel, on:d});
  });
}

// 会員アプリから「参加を希望する」
function requestJoin(inviteId, d){
  tx(() => {
    const inv = (db.invites || []).find(i => i.id === inviteId);
    if (!inv) throw new PointError("招待が見つかりません");
    inv.requested_on = inv.requested_on || d;
  });
}

// 予約：道ツアーは招待された会員だけが予約できる
function bookTourEx(no, tourId, points, d, op){
  const t = getTour(tourId);
  if (isMichi(t)){
    const m = getMember(no);
    if (!inviteFor(t.id, m.id)) throw new PointError("道ツアーは招待された会員だけが予約できます。先に「招待を送る」で招待してください");
  }
  return bookTour(no, tourId, points, d, op);
}

// 会員に届いている招待（催行予定のツアーのみ、出発日が近い順）
function myInvites(mid, d){
  return (db.invites || []).filter(i => i.member_id === mid).map(i => ({inv:i, t:getTour(i.tour_id)}))
    .filter(x => x.t.status === "scheduled" && x.t.depart_date >= d)
    .sort((a,b) => a.t.depart_date < b.t.depart_date ? -1 : 1);
}

// まだ招待の対象でない会員に「あと何回で招待」を示すための目安
function inviteGoal(mid, d){
  const ts = db.tours.filter(t => isMichi(t) && t.status === "scheduled");
  const need = ts.length ? Math.min(...ts.map(t => t.invite_min_tours)) : MICHI.DEFAULT_MIN_TOURS;
  const have = normalToursIn(mid, d);
  return {need, have, left: Math.max(0, need - have)};
}

// サンプルデータ（現行版と同じ内容に、常連の会員と道ツアーを追加）。points.js の seed を置き換える
function seed(base){
  db = emptyDb();
  db.seq.invite = 0; db.invites = [];
  const back = n => addDays(base, -n);
  const S = "サンプル";
  const hanako = registerMember({name:"山田 花子", kana:"ヤマダ ハナコ", phone:"090-1234-5678", pin:"1234", birthdate:`1958-${back(30).slice(5,7)}-15`}, back(230), S);
  const taro = registerMember({name:"鈴木 太郎", kana:"スズキ タロウ", phone:"080-2222-3333", pin:"5678", referrer_no:hanako.member_no}, back(130), S);
  const ichiro = registerMember({name:"佐藤 一郎", kana:"サトウ イチロウ", phone:"070-4444-5555", pin:"2468", birthdate:"1951-02-03"}, back(420), S);
  const kazuko = registerMember({name:"田中 和子", kana:"タナカ カズコ", phone:"090-7777-8888", pin:"1357", birthdate:"1955-06-21"}, back(200), S);
  const past = [["2025-H01","初夏の富士五湖めぐり",330,9800],["2025-H02","上高地ハイキング日帰り",270,11800],["2025-H03","秋の京都 紅葉ライトアップ",210,19800],
                ["2025-H04","いちご狩りと温泉の旅",150,8900],["2025-H05","河津桜と伊豆の海鮮",90,10800],["2025-H06","しだれ桜の名所めぐり",60,9800]];
  for (const [code, name, ago, price] of past){
    const t = createTour({code, name, depart_date:back(ago), price});
    bookTour(ichiro.member_no, t.id, 0, back(ago + 14), S);
    if (ago <= 150) bookTour(kazuko.member_no, t.id, 0, back(ago + 14), S);
    completeTour(t.id, back(ago), S);
  }
  const t1 = createTour({code:"2026-NIKKO", name:"紅葉の日光・鬼怒川 日帰りバスツアー", depart_date:back(30), price:12800});
  bookTour(hanako.member_no, t1.id, 0, back(50), S);
  bookTour(taro.member_no, t1.id, 300, back(50), S);
  bookTour(ichiro.member_no, t1.id, 1000, back(50), S);
  completeTour(t1.id, back(30), S);
  const t2 = createTour({code:"2026-KANI", name:"冬の味覚 カニ食べ放題ツアー（ポイント2倍）", depart_date:addDays(base, 40), price:15800, bonus_multiplier:2});
  bookTour(hanako.member_no, t2.id, 500, base, S);
  bookTour(ichiro.member_no, t2.id, 0, base, S);
  createTour({code:"2026-HAKONE", name:"箱根 彫刻の森と芦ノ湖遊覧", depart_date:addDays(base, 18), price:9800, bonus_points:100});
  // 道ツアー：1件目は招待済み（佐藤様は予約済、田中様は参加希望）、2件目はまだ招待していない
  const m1 = createTourEx({kind:"michi", code:"MICHI-OIRASE", name:"奥入瀬渓流と十和田湖 2日間", depart_date:addDays(base, 55), price:89800});
  sendInvites(m1.id, back(6), S);
  markContacted(inviteFor(m1.id, kazuko.id).id, "phone", back(4));
  bookTourEx(ichiro.member_no, m1.id, 0, back(3), S);
  requestJoin(inviteFor(m1.id, kazuko.id).id, back(2));
  createTourEx({kind:"michi", code:"MICHI-SHIRAKAWA", name:"冬の白川郷ライトアップと飛騨の宿 2日間", depart_date:addDays(base, 96), price:76000});
}
