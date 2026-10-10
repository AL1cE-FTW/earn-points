// PC で見ているときに「PC表示／スマホ表示」を切り替える。
// スマホ表示では、同じページを幅390pxの枠（iframe）に入れて中央に表示する。
// 枠の中は本物のスマホ幅になるので、スマホ用のレイアウトがそのまま確認できる。
(function () {
  "use strict";
  if (window.self !== window.top) { document.documentElement.classList.add("in-device"); return; }

  // data-view="phone" のページ（会員画面）は毎回スマホ表示で開く。切り替えは保存しない
  const fixed = document.currentScript && document.currentScript.dataset.view;
  const KEY = "bt-view-mode";
  const W = 390, H = 844;
  const wide = matchMedia("(min-width: 960px)");
  const get = () => { try { return localStorage.getItem(KEY); } catch (e) { return null; } };
  const set = v => { try { localStorage.setItem(KEY, v); } catch (e) {} };
  let mode = fixed || (get() === "phone" ? "phone" : "pc");

  const bar = document.createElement("div");
  bar.className = "viewswitch";
  bar.setAttribute("role", "group");
  bar.setAttribute("aria-label", "表示の切り替え");
  bar.innerHTML =
    '<button type="button" data-view="pc"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4.5" width="18" height="12" rx="1.5"/><path d="M8.5 20h7M12 16.5V20"/></svg>PC表示</button>' +
    '<button type="button" data-view="phone"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M11 18.5h2"/></svg>スマホ表示</button>';

  const stage = document.createElement("div");
  stage.className = "device-stage";
  stage.hidden = true;
  stage.innerHTML =
    '<div class="device"><iframe title="スマホ表示のプレビュー" loading="lazy"></iframe></div>' +
    '<p class="device-note">スマホ表示（幅' + W + 'px）・この枠の中もそのまま操作できます</p>';
  const device = stage.querySelector(".device");
  const frame = stage.querySelector("iframe");

  function fit() {
    const s = Math.min(1, (window.innerHeight - 150) / (H + 28), (window.innerWidth - 80) / (W + 28));
    device.style.setProperty("--scale", Math.max(0.5, s).toFixed(3));
  }
  function apply() {
    const phone = wide.matches && mode === "phone";
    bar.hidden = !wide.matches;
    stage.hidden = !phone;
    document.documentElement.classList.toggle("phone-preview", phone);
    if (phone && !frame.getAttribute("src")) frame.setAttribute("src", location.pathname + location.search);
    bar.querySelectorAll("[data-view]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.view === (phone ? "phone" : "pc"))));
    fit();
  }
  bar.addEventListener("click", e => {
    const b = e.target.closest("[data-view]");
    if (!b) return;
    mode = b.dataset.view; if (!fixed) set(mode); apply();
  });
  window.addEventListener("resize", fit);
  wide.addEventListener("change", apply);
  document.addEventListener("keydown", e => { if (e.key === "Escape" && mode === "phone") { mode = "pc"; if (!fixed) set(mode); apply(); } });

  function mount() { document.body.append(stage, bar); apply(); }
  document.body ? mount() : document.addEventListener("DOMContentLoaded", mount);
})();
