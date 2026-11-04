/* Shared replay pages UI: back-to-top. */
(function () {
  "use strict";
  function mount() {
    if (document.querySelector(".replay-backtop")) return;
    var b = document.createElement("button");
    b.type = "button";
    b.className = "replay-backtop";
    b.setAttribute("aria-label", "回到顶部");
    b.textContent = "↑";
    b.addEventListener("click", function () {
      var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      window.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" });
    });
    document.body.appendChild(b);
    function onScroll() { b.classList.toggle("show", window.scrollY > 700); }
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
