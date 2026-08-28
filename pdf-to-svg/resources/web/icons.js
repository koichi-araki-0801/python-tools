// =============================================================================
// icons.js — インライン SVG アイコン断片の一元管理 (app.js / rail.js が共有)
// =============================================================================

import { svg } from "./dom.js";

var fileIcon = '<path d="M6 3.5A1.5 1.5 0 0 1 7.5 2h6L19 7.5v13A1.5 1.5 0 0 1 17.5 22h-10A1.5 1.5 0 0 1 6 20.5V3.5Z"/><path d="M13 2v6h6"/>';
var xIcon = '<path d="m6 6 12 12M18 6 6 18"/>';
var chevD = '<path d="m10 6 6 6-6 6"/>';
var checkD = "m4.5 12.5 5 5 10-11";
var ckMark = svg('<path d="' + checkD + '"/>', 11, 2.4);
var checkDot = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="' + checkD + '"/></svg>';
var skipDot = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 8l4 4-4 4M15 8v8"/></svg>';

export { fileIcon, xIcon, chevD, checkD, ckMark, checkDot, skipDot };
