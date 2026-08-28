// =============================================================================
// icons.js — アイコン (`<i data-ic>` の inline SVG 化) とトースト通知
// =============================================================================

import { dom } from "./dom.js";

// ── 1. アイコン (`<i data-ic="...">` を inline SVG 化) + トースト ──
const ICONS = {
  undo:'<path d="M9 7 4 12l5 5"/><path d="M4 12h11a5 5 0 0 1 0 10h-1"/>',
  redo:'<path d="m15 7 5 5-5 5"/><path d="M20 12H9a5 5 0 0 0 0 10h1"/>',
  file:'<path d="M6 3.5A1.5 1.5 0 0 1 7.5 2h6L19 7.5v13A1.5 1.5 0 0 1 17.5 22h-10A1.5 1.5 0 0 1 6 20.5V3.5Z"/><path d="M13 2v6h6"/>',
  folder:'<path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h4l2 2.2H19.5A1.5 1.5 0 0 1 21 9.7V18a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18V7.5Z"/>',
  check:'<path d="m4.5 12.5 5 5 10-11"/>',
  cursor:'<path d="M5.5 3.5 19 12l-6.2 1.4L9.5 20 5.5 3.5Z"/>',
  leader:'<circle cx="6" cy="18" r="2.4"/><path d="M7.6 16.4 18 6"/><circle cx="19" cy="5" r="1.6"/>',
  bend:'<path d="M4 19h7l4-9 5 0"/><circle cx="11" cy="19" r="2"/>',
  droplet:'<path d="M12 3s6 7 6 11a6 6 0 0 1-12 0c0-4 6-11 6-11z"/>',
  rows:'<rect x="4" y="5" width="16" height="5" rx="1.5"/><rect x="4" y="14" width="16" height="5" rx="1.5"/>',
  width:'<path d="M3 12h18M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3"/><path d="M8 5h8M8 19h8"/>',
  reset:'<path d="M4 5v5h5"/><path d="M5 13a8 8 0 1 0 2-6L4 10"/>',
  zoomin:'<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5M11 8v6M8 11h6"/>',
  zoomout:'<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5M8 11h6"/>',
  chevR:'<path d="m10 6 6 6-6 6"/>',
  chevL:'<path d="m14 6-6 6 6 6"/>',
  upload:'<path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M5 20h14"/>',
  download:'<path d="M12 4v12"/><path d="m7 11 5 5 5-5"/><path d="M5 20h14"/>',
};
function drawIcons(scope) {
  (scope || document).querySelectorAll("i[data-ic]").forEach((el) => {
    if (el.dataset.drawn) return;
    const k = el.getAttribute("data-ic");
    if (!ICONS[k]) return;
    const stroke = el.hasAttribute("data-accent") ? "var(--accent)" : "currentColor";
    el.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="${stroke}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${ICONS[k]}</svg>`;
    el.style.display = "inline-flex";
    el.style.alignItems = "center";
    el.dataset.drawn = "1";
  });
}

let _toastTimer = 0;
function showToast(msg) {
  const t = dom.toast;
  if (!t) return;
  t.textContent = msg;
  t.classList.add("on");
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => t.classList.remove("on"), 2200);
}

export { drawIcons, showToast };
