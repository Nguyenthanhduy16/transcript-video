// Bảng Cài đặt: lưu localStorage, áp dụng qua CSS variables / class trên <body>.
import { $, esc, store } from "./common.js";

export const DEFAULTS = {
  viOn: true, viSize: 100, viColor: "",
  jaOn: true, jaSize: 100, jaColor: "", furigana: true, romaji: false,
  subMode: "box",          // overlay | box | off
  bgOpacity: 55, outline: 0, shadow: false, weight: 600, font: "Noto Sans JP",
  rate: 1,
  autoPause: "off",        // off | each | new
  hoverLookup: true,
  viewMode: "watch",       // watch | read | shadow
  panel: true,
};
const KEY = "vt.settings.v1";

export function loadSettings() {
  return { ...DEFAULTS, ...store.get(KEY, {}) };
}
export function saveSettings(s) { store.set(KEY, s); }

export function applySettings(s) {
  const r = document.documentElement.style;
  r.setProperty("--sub-ja-scale", s.jaSize / 100);
  r.setProperty("--sub-vi-scale", s.viSize / 100);
  s.jaColor ? r.setProperty("--sub-ja-color", s.jaColor) : r.removeProperty("--sub-ja-color");
  s.jaColor ? r.setProperty("--sub-ja-color-overlay", s.jaColor) : r.removeProperty("--sub-ja-color-overlay");
  s.viColor ? r.setProperty("--sub-vi-color", s.viColor) : r.removeProperty("--sub-vi-color");
  r.setProperty("--sub-bg-opacity", s.bgOpacity / 100);
  r.setProperty("--sub-outline", `${s.outline}px`);
  r.setProperty("--sub-shadow", s.shadow ? "0 2px 4px rgba(0,0,0,.6)" : "none");
  r.setProperty("--sub-weight", s.weight);
  r.setProperty("--sub-font", `"${s.font}", system-ui, sans-serif`);
  const b = document.body.classList;
  b.toggle("hide-furi", !s.furigana);
  b.toggle("hide-romaji", !s.romaji);
  b.toggle("hide-vi", !s.viOn);
  b.toggle("hide-ja", !s.jaOn);
}

const RATES = [0.5, 0.75, 1, 1.25, 1.5, 2];
const FONTS = ["Noto Sans JP", "Noto Serif JP", "M PLUS Rounded 1c", "Zen Maru Gothic", "Kosugi Maru"];

function sw(key, s) {
  return `<label class="switch"><input type="checkbox" data-k="${key}" ${s[key] ? "checked" : ""}><span></span></label>`;
}
function seg(key, opts, s) {
  return `<div class="seg" data-seg="${key}">${opts.map(([v, l]) =>
    `<button type="button" data-v="${v}" class="${String(s[key]) === String(v) ? "sel" : ""}">${l}</button>`).join("")}</div>`;
}
function range(key, min, max, step, s, unit = "") {
  return `<span><input type="range" data-k="${key}" min="${min}" max="${max}" step="${step}" value="${s[key]}">
    <span class="muted" data-out="${key}">${s[key]}${unit}</span></span>`;
}

export function openSettings(s, onChange) {
  const back = document.createElement("div");
  back.className = "modal-back";
  back.innerHTML = `<div class="modal" role="dialog" aria-label="Cài đặt">
    <div style="display:flex;align-items:center"><h3>Cài đặt</h3><span style="flex:1"></span>
      <button class="btn small" data-reset>Mặc định</button>&nbsp;<button class="btn small primary" data-close>Xong</button></div>
    <p class="muted" style="margin:0 0 8px;font-size:13px">Tự lưu trên trình duyệt này.</p>
    <div class="set-group"><h4>Tiếng Việt</h4>
      <div class="set-row">Hiện bản dịch ${sw("viOn", s)}</div>
      <div class="set-row">Cỡ chữ ${range("viSize", 60, 200, 5, s, "%")}</div>
      <div class="set-row">Màu chữ <input type="color" data-k="viColor" value="${s.viColor || "#8a8a96"}"></div>
    </div>
    <div class="set-group"><h4>Tiếng Nhật</h4>
      <div class="set-row">Hiện câu gốc ${sw("jaOn", s)}</div>
      <div class="set-row">Cỡ chữ ${range("jaSize", 60, 200, 5, s, "%")}</div>
      <div class="set-row">Màu chữ <input type="color" data-k="jaColor" value="${s.jaColor || "#1d1d24"}"></div>
      <div class="set-row">Furigana ${sw("furigana", s)}</div>
      <div class="set-row">Romaji ${sw("romaji", s)}</div>
    </div>
    <div class="set-group"><h4>Phụ đề hiển thị</h4>
      <div class="set-row">Vị trí ${seg("subMode", [["overlay", "Nổi"], ["box", "Khung"], ["off", "Tắt"]], s)}</div>
    </div>
    <div class="set-group"><h4>Kiểu chữ phụ đề</h4>
      <div class="set-row">Độ mờ nền (khi nổi) ${range("bgOpacity", 0, 100, 5, s, "%")}</div>
      <div class="set-row">Viền chữ ${range("outline", 0, 4, 0.5, s, "px")}</div>
      <div class="set-row">Bóng chữ ${sw("shadow", s)}</div>
      <div class="set-row">Độ dày nét ${seg("weight", [[400, "Thường"], [500, "Vừa"], [600, "Đậm"], [800, "Rất đậm"]], s)}</div>
      <div class="set-row">Phông chữ <select data-k="font">${FONTS.map((f) => `<option ${f === s.font ? "selected" : ""}>${esc(f)}</option>`).join("")}</select></div>
    </div>
    <div class="set-group"><h4>Phát video</h4>
      <div class="set-row">Tốc độ ${seg("rate", RATES.map((r) => [r, r + "x"]), s)}</div>
      <div class="set-row">Tự dừng cuối câu ${seg("autoPause", [["off", "Tắt"], ["each", "Mỗi câu"], ["new", "Khi có từ mới"]], s)}</div>
    </div>
    <div class="set-group"><h4>Tra từ</h4>
      <div class="set-row">Di chuột vào từ để hiện nghĩa ${sw("hoverLookup", s)}</div>
    </div>
  </div>`;
  document.body.appendChild(back);
  const modal = $(".modal", back);

  const update = (k, v) => { s[k] = v; saveSettings(s); applySettings(s); onChange?.(k, v); };
  modal.addEventListener("input", (e) => {
    const k = e.target.dataset.k;
    if (!k) return;
    let v = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    if (e.target.type === "range") v = Number(v);
    const out = $(`[data-out="${k}"]`, modal);
    if (out) out.textContent = v + out.textContent.replace(/^[\d.]+/, "");
    update(k, v);
  });
  modal.addEventListener("click", (e) => {
    const b = e.target.closest("[data-seg] button");
    if (b) {
      const k = b.parentElement.dataset.seg;
      let v = b.dataset.v;
      if (k === "rate" || k === "weight") v = Number(v);
      b.parentElement.querySelectorAll("button").forEach((x) => x.classList.toggle("sel", x === b));
      update(k, v);
    }
    if (e.target.closest("[data-reset]")) {
      Object.assign(s, DEFAULTS, { panel: s.panel, viewMode: s.viewMode });
      saveSettings(s); applySettings(s); onChange?.("*", null);
      back.remove(); openSettings(s, onChange);
    }
    if (e.target.closest("[data-close]")) back.remove();
  });
  back.addEventListener("click", (e) => { if (e.target === back) back.remove(); });
  const onKey = (e) => { if (e.key === "Escape") { back.remove(); removeEventListener("keydown", onKey); } };
  addEventListener("keydown", onKey);
}
