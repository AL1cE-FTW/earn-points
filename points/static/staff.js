// スタッフ画面の小さな補助。画面に直接スクリプトを書かない（CSP で禁止している）ため、ここにまとめる。
"use strict";
// data-confirm のあるフォームは、送信前に確認する
document.addEventListener("submit", e => {
  const msg = e.target.getAttribute("data-confirm");
  if (msg && !window.confirm(msg)) e.preventDefault();
});
// 印刷ボタン
document.addEventListener("click", e => {
  if (e.target.closest("[data-print]")) window.print();
});
