// 画面デモの会員画面：サービス版の会員アプリ（member-app.js）を、このブラウザ内のデモデータで動かす。
// サーバの /api/ と同じ形のデータを、points.js（と提案版では michi.js）の計算から作って返す。
// member-app.js より前に読み込む。data-session にログイン状態の保存先、data-links にメニュー下のリンクを書く。
"use strict";
(function () {
  const me = document.currentScript;
  const SESSION_KEY = me.dataset.session || "bt-points-member-v1";
  const hasMichi = typeof myInvites === "function";
  const storeKey = typeof MICHI_KEY !== "undefined" ? MICHI_KEY : STORE_KEY;

  const session = {
    get(){ try { return localStorage.getItem(SESSION_KEY); } catch (e) { return null; } },
    set(no){ try { no ? localStorage.setItem(SESSION_KEY, no) : localStorage.removeItem(SESSION_KEY); } catch (e) {} },
  };
  const current = () => {
    const no = session.get();
    if (!no) return null;
    try { const m = getMember(no); return m.status === "active" ? m : null; } catch (e) { return null; }
  };
  const gainOf = (m, t, paid) => estimateEarn(m, t, paid).items.reduce((a, [, p]) => a + p, 0);
  const txnOut = r => {
    const b = r.booking_id && db.bookings.find(x => x.id === r.booking_id);
    const tn = b ? getTour(b.tour_id).name : "";
    const reason = (r.kind === "earn" || r.kind === "bonus") && tn && !r.reason.includes(tn) ? `${r.reason}／${tn}` : r.reason;
    return {date: r.created_on, kind: KIND[r.kind], reason, points: r.points};
  };
  const isMichiTour = t => hasMichi && isMichi(t);
  const days = d => Math.round((parse(d) - parse(today)) / 864e5);

  function summary(m){
    const rank = rankFor(m.id, today);
    const sched = expiringSchedule(m.id, today).map(([d, p]) => ({date: d, points: p}));
    const soon = sched.filter(x => x.date <= addDays(today, 90));
    const up = db.bookings.filter(b => b.member_id === m.id && b.status === "booked").map(b => ({b, t: getTour(b.tour_id)}))
      .filter(x => x.t.depart_date >= today).sort((x, y) => x.t.depart_date < y.t.depart_date ? -1 : 1)[0];
    const recent = db.txns.filter(t => t.member_id === m.id).sort((a, b) => b.id - a.id).slice(0, 4).map(txnOut);
    return {
      today,
      member: {member_no: m.member_no, name: m.name, joined_on: m.joined_on},
      balance: balance(m.id, today),
      rank,
      ranks: RULES.RANKS.map(([code, name, need, mult]) => ({code, name, need, mult})),
      expiring: sched,
      soon: soon.length ? {points: soon.reduce((a, x) => a + x.points, 0), date: soon[0].date} : null,
      next_tour: up ? {name: up.t.name, depart_date: up.t.depart_date, pay: up.b.price - up.b.points_used, points_used: up.b.points_used,
                       gain: gainOf(m, up.t, up.b.price - up.b.points_used), days: days(up.t.depart_date), michi: isMichiTour(up.t)} : null,
      recent,
      invites: hasMichi ? myInvites(m.id, today).map(({inv, t}) => ({id: inv.id, tour_name: t.name, depart_date: t.depart_date,
                                                                    price: t.price, bonus: t.bonus_points, state: inviteState(inv)})) : [],
      normal_tours: hasMichi ? normalToursIn(m.id, today) : 0,
      goal: hasMichi ? inviteGoal(m.id, today) : null,
      rules: {yen_per_point: RULES.YEN_PER_POINT, redeem_unit: RULES.REDEEM_UNIT, birthday: RULES.BIRTHDAY_BONUS,
              referral: RULES.REFERRAL_BONUS, expiry_years: RULES.EXPIRY_YEARS},
    };
  }

  async function api(method, path, data, LoginRequired){
    bootData();
    if (method === "POST" && path === "/api/login"){
      const m = authenticate(data.member_no, data.pin);
      if (!m) throw new Error("会員番号または暗証番号が正しくありません");
      session.set(m.member_no); return {ok: true};
    }
    if (method === "POST" && path === "/api/logout"){ session.set(null); return {ok: true}; }
    const m = current();
    if (!m) throw new LoginRequired();
    if (path === "/api/me") return summary(m);
    if (path === "/api/history"){
      const rows = db.txns.filter(t => t.member_id === m.id).sort((a, b) => b.id - a.id);
      return {items: rows.map(txnOut), earned: rows.filter(r => r.points > 0).reduce((a, r) => a + r.points, 0),
              used: rows.filter(r => r.kind === "redeem").reduce((a, r) => a - r.points, 0)};
    }
    if (path === "/api/tours"){
      const out = {upcoming: [], past: []};
      for (const b of db.bookings.filter(x => x.member_id === m.id)){
        const t = getTour(b.tour_id);
        const item = {name: t.name, depart_date: t.depart_date, price: b.price, points_used: b.points_used, status: b.status,
                      status_label: BOOKING[b.status], michi: isMichiTour(t)};
        if (b.status === "booked"){ item.gain = gainOf(m, t, b.price - b.points_used); out.upcoming.push(item); }
        else { item.earned = db.txns.filter(x => x.booking_id === b.id && (x.kind === "earn" || x.kind === "bonus")).reduce((a, x) => a + x.points, 0); out.past.push(item); }
      }
      out.upcoming.sort((x, y) => x.depart_date < y.depart_date ? -1 : 1);
      out.past.sort((x, y) => x.depart_date < y.depart_date ? 1 : -1);
      return out;
    }
    if (path === "/api/pin"){
      if (m.pin !== data.current) throw new Error("現在の暗証番号が正しくありません");
      if (!/^\d{4,8}$/.test(data.next || "")) throw new Error("暗証番号は4〜8桁の数字で設定してください");
      m.pin = data.next; save(); return {ok: true};
    }
    const req = path.match(/^\/api\/invites\/(\d+)\/request$/);
    if (req && hasMichi){
      const inv = (db.invites || []).find(i => i.id === Number(req[1]) && i.member_id === m.id);
      if (!inv) throw new Error("招待が見つかりません");
      requestJoin(inv.id, today); return {ok: true};
    }
    throw new Error("見つかりません");
  }

  bootData();
  const samples = db.members.filter(m => m.status === "active").slice(0, 4);
  window.MEMBER_APP = {
    api,
    rulesUrl: me.dataset.rules || "../",
    serviceWorker: false,
    cacheKey: SESSION_KEY + "-last",
    badge: `<span class="demo" title="デモの日付">デモ ${today.replace(/-/g, "/")}</span>`,
    loginHelp: `<section class="card"><div class="st-head"><h2>デモ用のサンプル会員</h2></div>
      <p class="small muted">押すと会員番号と暗証番号が入ります。${hasMichi ? "佐藤様・田中様には道ツアーの招待が届いています。" : ""}</p>
      <div class="samples">${samples.map(m => { const r = rankFor(m.id, today);
        return `<button type="button" data-fill="${m.member_no}" data-pin="${esc(m.pin)}">${esc(m.name)}<small>${r.name}・${yen(balance(m.id, today))}マイル</small></button>`; }).join("")}</div></section>
      <p class="small muted">スタッフ画面（デモ）で予約やマイル付与をすると、同じブラウザならこの画面に反映されます。</p>`,
    links: JSON.parse(me.dataset.links || "[]"),
  };
  // スタッフ画面（別タブ）での変更をすぐ反映する
  window.addEventListener("storage", e => { if (e.key === storeKey && window.memberApp) window.memberApp.reload(); });
})();
