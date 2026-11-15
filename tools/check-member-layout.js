// 会員画面をスマホの幅（320〜414px）で全タブ開き、1行のはずの短い文字が折り返していないか、
// 画面が横にはみ出していないかを調べる。会員画面を直したら実行する。
//
//   python3 -m http.server 8090 -d site        （別のターミナルで）
//   node tools/check-member-layout.js [スクショの保存先] [会員画面のURL]
//
// Playwright（npm の playwright）が必要。本番のサーバには不要。
const { chromium } = require(process.env.PW || "playwright");
const base = process.argv[3] || "http://127.0.0.1:8090/michi/member/";
(async()=>{ const b = await chromium.launch(); const out = process.argv[2] || "."; const problems = []; const errs = [];
  for (const w of [320, 360, 375, 390, 414]) for (const who of ["山田", "佐藤", "田中"]) {
    const ctx = await b.newContext({viewport:{width:w,height:740}, isMobile:true, deviceScaleFactor:2}); const m = await ctx.newPage();
    m.on("pageerror", e => errs.push(e.message));
    await m.goto(base); await m.waitForSelector(".samples button");
    const check = async (where) => {
      const found = await m.evaluate(() => [...document.querySelectorAll("body *")].filter(e => {
        if (e.closest(".help p, .install ol, .r-what, .p-name, .invite h2, .toast, .login .small, .samples, .offline, .notice, .card > p, .empty")) return false;
        const t = e.textContent.trim(); if (!t || t.length > 14 || e.children.length > 0 && [...e.children].some(c => c.textContent.trim())) return false;
        const cs = getComputedStyle(e); if (cs.display === "none" || cs.visibility === "hidden" || e.getClientRects().length === 0) return false;
        // 文字そのものが何行に分かれて表示されているかを数える
        const tops = new Set();
        for (const n of e.childNodes) if (n.nodeType === 3 && n.textContent.trim()){
          const r = document.createRange(); r.selectNodeContents(n);
          for (const x of r.getClientRects()) if (x.width > 0) tops.add(Math.round(x.top / 4));
        }
        return tops.size > 1;
      }).map(e => `${e.tagName.toLowerCase()}.${(e.className && e.className.baseVal === undefined ? e.className : "")}「${e.textContent.trim()}」`));
      const sw = await m.evaluate(() => document.documentElement.scrollWidth);
      if (sw > w) problems.push(`${w}px ${who} ${where}: 横にはみ出し ${sw}px`);
      for (const f of new Set(found)) problems.push(`${w}px ${who} ${where}: ${f}`);
    };
    await check("ログイン");
    await m.click(`.samples button:has-text('${who}')`); await m.click("form[data-form=login] button"); await m.waitForSelector(".pts");
    await check("ホーム");
    if (w === 360 && who === "佐藤") await m.screenshot({path:`${out}/home-360.png`, fullPage:true});
    for (const tab of ["history", "tours", "info"]) { await m.click(`.tabbar [data-tab=${tab}]`); await m.waitForTimeout(250); await check(tab);
      if (w === 360 && who === "佐藤") await m.screenshot({path:`${out}/${tab}-360.png`, fullPage:true}); }
    await m.click(".tabbar [data-tab=home]"); await m.waitForSelector(".idcard"); await m.click(".idcard"); await m.waitForSelector("#cardview .barcode"); await check("会員証");
    if (w === 320) await m.screenshot({path:`${out}/card-320-${who}.png`});
    await ctx.close();
  }
  console.log(problems.length ? problems.join("\n") : "折り返し・はみ出しなし"); console.log("errors:", JSON.stringify(errs)); await b.close();
  process.exit(problems.length || errs.length ? 1 : 0); })();
