const DEFAULTS = { server: "http://localhost:8000", subOn: true, jaOn: true, viOn: true, furigana: true, romaji: false,
                   fontScale: 100, panelOn: true, hoverLookup: true, autoPause: "off", subBottom: 14, offset: 0,
                   selTranslate: true, selMode: "instant", selEngine: "auto", selTarget: "vi", selDisabledSites: [] };
const $ = (s) => document.querySelector(s);
let S = { ...DEFAULTS };

async function load() {
  const { settings } = await chrome.storage.sync.get("settings");
  S = { ...DEFAULTS, ...(settings || {}) };
  document.querySelectorAll("[data-k]").forEach((el) => {
    const k = el.dataset.k;
    if (el.type === "checkbox") el.checked = !!S[k]; else el.value = S[k];
  });
  $("#autoPause").checked = S.autoPause === "each";
  $("#server").value = S.server;
  $("#openWeb").href = S.server;
  outputs();
  siteButton();
  health();
  tabStatus();
  words();
}
function outputs() { $("#fontOut").textContent = S.fontScale + "%"; $("#botOut").textContent = S.subBottom + "%"; }
const save = () => chrome.storage.sync.set({ settings: S });

document.querySelectorAll("[data-k]").forEach((el) => el.addEventListener("input", () => {
  const k = el.dataset.k;
  S[k] = el.type === "checkbox" ? el.checked : el.tagName === "SELECT" ? el.value : Number(el.value);
  outputs();
  save();
}));
$("#autoPause").addEventListener("change", (e) => { S.autoPause = e.target.checked ? "each" : "off"; save(); });

$("#saveServer").addEventListener("click", async () => {
  let url = $("#server").value.trim().replace(/\/+$/, "");
  try { url = new URL(url).origin; } catch { $("#health").innerHTML = '<span class="bad">Địa chỉ không hợp lệ</span>'; return; }
  const local = /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(url);
  if (!local) {
    // server khác localhost: xin quyền truy cập host đó (Chrome hiện hộp thoại)
    const granted = await chrome.permissions.request({ origins: [url + "/*"] });
    if (!granted) { $("#health").innerHTML = '<span class="bad">Chưa cấp quyền truy cập server này</span>'; return; }
  }
  S.server = url;
  await save();
  $("#openWeb").href = url;
  health();
});

async function health() {
  const r = await chrome.runtime.sendMessage({ type: "api", path: "/api/health" });
  const el = $("#health");
  if (!r?.ok) { el.innerHTML = `<span class="bad">✗ ${escapeHtml(r?.error || "Không kết nối được")}</span>`; return; }
  const h = r.data;
  el.innerHTML = `<span class="ok">✓ Đã kết nối</span> · ASR: ${h.asr ? escapeHtml(h.asrEngine) : "chưa có"} · người nói: ${escapeHtml(h.diarization)} · hàng đợi: ${escapeHtml(h.queue)}`;
  if (!h.ffmpeg) el.innerHTML += `<div class="bad">⚠ Máy chạy server chưa cài ffmpeg: nút “Nhận dạng giọng nói” sẽ không chạy. Windows: <code>winget install Gyan.FFmpeg</code> · macOS: <code>brew install ffmpeg</code> · Ubuntu: <code>sudo apt install ffmpeg</code>, rồi mở terminal mới và chạy lại server.</div>`;
}

async function tabStatus() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const text = $("#tabText"), btn = $("#enableBtn");
  if (!tab || !/^https?:/.test(tab.url || "")) { text.textContent = "Mở một trang có video để dùng extension."; return; }
  let st = null;
  try { st = await chrome.tabs.sendMessage(tab.id, { type: "status" }); } catch { /* chưa bật trên trang này */ }
  if (!st) {
    text.textContent = "Extension chưa chạy trên trang này.";
    btn.classList.remove("hidden");
    btn.onclick = async () => {
      try {
        await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content/render.js", "content/content.js"] });
        text.textContent = "Đã bật. Bảng transcript xuất hiện cạnh video.";
        btn.classList.add("hidden");
        setTimeout(tabStatus, 1500);
      } catch (e) { text.innerHTML = `<span class="bad">Không bật được: ${escapeHtml(e.message)}</span>`; }
    };
    return;
  }
  btn.classList.add("hidden");
  const msg = {
    "no-video": "Không thấy video trên trang.",
    checking: "Đang kiểm tra transcript…",
    missing: "Video chưa có transcript. Bấm nút 字 trên video để tạo.",
    creating: `Đang tạo transcript… ${st.progress != null ? Math.round(st.progress) + "%" : ""}`,
    ready: `✓ ${st.title || "Transcript"} · ${st.cueCount} câu`,
    error: "Không kết nối được server.",
  }[st.status] || st.status;
  text.innerHTML = escapeHtml(msg) + (st.statusMsg && st.status !== "creating" ? `<div class="small bad">${escapeHtml(st.statusMsg)}</div>` : "");
}

async function words() {
  const { words: list = [] } = await chrome.storage.local.get("words");
  $("#wordCount").textContent = `(${list.length})`;
  $("#words").innerHTML = list.slice().reverse().slice(0, 30).map((w) =>
    `<li><b>${escapeHtml(w.lemma)}</b><span class="rd">${escapeHtml(w.reading)}</span> – ${escapeHtml(w.meaning || "")}</li>`).join("") ||
    '<li class="muted">Chưa có từ nào. Rê chuột vào một từ trong phụ đề và bấm "Lưu vào sổ từ".</li>';
  $("#exportBtn").disabled = !list.length;
  $("#exportBtn").onclick = () => {
    const csv = list.map((w) => [w.lemma, w.reading, w.meaning, w.example, w.exampleVi].map((x) => `"${String(x ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv" }));
    a.download = "so-tu.csv";
    a.click();
  };
  $("#clearBtn").onclick = async () => {
    if (!list.length) return;
    if ($("#clearBtn").dataset.confirm !== "1") { $("#clearBtn").dataset.confirm = "1"; $("#clearBtn").textContent = "Bấm lần nữa để xoá"; return; }
    await chrome.storage.local.set({ words: [] });
    $("#clearBtn").dataset.confirm = ""; $("#clearBtn").textContent = "Xoá hết";
    words();
  };
}

async function siteButton() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const btn = $("#siteBtn");
  let host = "";
  try { host = new URL(tab.url).hostname; } catch {}
  if (!host) { btn.disabled = true; return; }
  const off = (S.selDisabledSites || []).includes(host);
  btn.textContent = off ? `Bật lại trên ${host}` : `Tắt trên ${host}`;
  btn.onclick = async () => {
    const list = new Set(S.selDisabledSites || []);
    off ? list.delete(host) : list.add(host);
    S.selDisabledSites = [...list];
    await save();
    siteButton();
  };
}
$("#openTr").addEventListener("click", () => chrome.runtime.sendMessage({ type: "openTranslator", text: "" }));

function escapeHtml(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
load();
