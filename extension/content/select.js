// Dịch khi bôi đen: chạy trên mọi trang (all_frames). Bôi đen chữ → khung dịch tiếng Việt cạnh đoạn chọn.
(() => {
  if (window.__cnwebSelect) return;
  window.__cnwebSelect = true;
  const TR = globalThis.CNWEB_TR;
  const DEFAULTS = { selTranslate: true, selMode: "instant", selEngine: "auto", selTarget: "vi", selDisabledSites: [] };
  let S = { ...DEFAULTS };
  const site = location.hostname;
  const enabled = () => S.selTranslate && !(S.selDisabledSites || []).includes(site);

  chrome.storage.sync.get("settings", ({ settings }) => { S = { ...DEFAULTS, ...(settings || {}) }; });
  chrome.storage.onChanged.addListener((ch) => { if (ch.settings) S = { ...DEFAULTS, ...(ch.settings.newValue || {}) }; });

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ------------------------------------------------------------------ giao diện (Shadow DOM, tạo khi cần)
  let host = null, root = null;
  function ensureHost() {
    if (host && host.isConnected) return;
    host = document.createElement("div");
    host.id = "cnweb-select-host";
    host.style.cssText = "position:absolute;left:0;top:0;width:0;height:0;z-index:2147483647;";
    root = host.attachShadow({ mode: "open" });
    root.innerHTML = `<style>
      :host { all: initial; }
      * { box-sizing: border-box; }
      .card { --bg:#fff; --bg2:#f3f3f6; --fg:#1d1d24; --muted:#74747f; --border:#e2e2e8; --accent:#e53945;
              position: absolute; width: min(380px, calc(100vw - 24px)); background: var(--bg); color: var(--fg);
              border: 1px solid var(--border); border-radius: 14px; box-shadow: 0 10px 34px rgba(20,20,40,.22);
              font: 14px/1.5 system-ui, "Segoe UI", Roboto, "Noto Sans JP", sans-serif; overflow: hidden; }
      @media (prefers-color-scheme: dark) { .card { --bg:#1c1c22; --bg2:#26262e; --fg:#ececf1; --muted:#9c9caa; --border:#34343e; } }
      .bar { display: flex; align-items: center; gap: 4px; padding: 6px 8px 6px 12px; background: var(--bg2); font-size: 12px; color: var(--muted); }
      .bar .lang { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .ib { border: 0; background: transparent; color: var(--muted); width: 28px; height: 28px; border-radius: 8px; cursor: pointer; font-size: 14px; }
      .ib:hover, .ib:focus-visible { background: var(--border); color: var(--fg); outline: none; }
      .body { padding: 10px 14px 12px; max-height: 50vh; overflow-y: auto; }
      .tr { font-size: 15px; white-space: pre-wrap; word-break: break-word; }
      .word { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; margin-bottom: 4px; }
      .word b { font-size: 18px; }
      .ipa { color: var(--accent); }
      .pos { font-size: 12px; color: var(--muted); }
      ul { margin: 6px 0 0; padding-left: 18px; color: var(--fg); }
      li { margin: 2px 0; }
      .ex { margin-top: 8px; font-size: 13px; color: var(--muted); border-left: 3px solid var(--border); padding-left: 8px; }
      .muted { color: var(--muted); }
      .err { color: var(--accent); font-size: 13px; }
      .foot { font-size: 11px; color: var(--muted); margin-top: 8px; display: flex; gap: 8px; align-items: center; }
      .foot button { border: 1px solid var(--border); background: var(--bg); color: var(--fg); border-radius: 8px; padding: 2px 8px; font-size: 12px; cursor: pointer; }
      .spin { display: inline-block; width: 12px; height: 12px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: s .8s linear infinite; vertical-align: -1px; margin-right: 6px; }
      @keyframes s { to { transform: rotate(360deg); } }
      @media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
      .fab { position: absolute; border: 0; border-radius: 9px; background: #e53945; color: #fff; font: 700 12px system-ui, sans-serif;
             padding: 5px 9px; cursor: pointer; box-shadow: 0 3px 10px rgba(0,0,0,.25); }
      .toast { position: absolute; background: #2b2224; color: #fff; padding: 5px 10px; border-radius: 8px; font: 12px system-ui, sans-serif; }
    </style><div id="wrap"></div>`;
    (document.body || document.documentElement).appendChild(host);
  }
  const wrap = () => root.getElementById("wrap");

  function close() { if (root) wrap().innerHTML = ""; current = null; }

  // ------------------------------------------------------------------ lấy đoạn bôi đen
  function selectionInfo() {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
    const text = sel.toString().replace(/\s+\n/g, "\n").trim();
    if (!text || !/\p{L}/u.test(text)) return null;
    const a = document.activeElement;
    if (a && (a.isContentEditable || /^(input|textarea)$/i.test(a.tagName))) return null;   // đang gõ chữ
    const range = sel.getRangeAt(0);
    const rects = [...range.getClientRects()].filter((r) => r.width || r.height);
    const r = rects.length ? rects[rects.length - 1] : range.getBoundingClientRect();
    const first = rects[0] || r;
    return { text, rect: { left: Math.min(first.left, r.left), right: r.right, top: first.top, bottom: r.bottom } };
  }

  function place(el, rect, w) {
    const sx = window.scrollX, sy = window.scrollY;
    const cardW = Math.min(w, window.innerWidth - 24);
    let left = Math.max(12, Math.min(rect.left, window.innerWidth - cardW - 12));
    let top = rect.bottom + 8;
    el.style.left = left + sx + "px";
    el.style.top = top + sy + "px";
    // không đủ chỗ phía dưới → đặt lên trên đoạn chọn
    requestAnimationFrame(() => {
      const h = el.offsetHeight;
      if (rect.bottom + 8 + h > window.innerHeight && rect.top - 8 - h > 0) el.style.top = rect.top - 8 - h + sy + "px";
    });
  }

  // ------------------------------------------------------------------ hiển thị
  let current = null;     // { text, rect, result }
  let seq = 0;

  function showButton(info) {
    ensureHost();
    wrap().innerHTML = `<button class="fab" id="go" title="Dịch sang tiếng Việt">Dịch</button>`;
    const b = root.getElementById("go");
    b.style.left = Math.min(info.rect.right, window.innerWidth - 60) + window.scrollX + "px";
    b.style.top = info.rect.bottom + 6 + window.scrollY + "px";
    b.onclick = (e) => { e.stopPropagation(); run(info); };
    current = { ...info, button: true };
  }

  async function run(info) {
    ensureHost();
    const id = ++seq;
    current = { ...info };
    wrap().innerHTML = `<div class="card" id="card"><div class="bar"><span class="lang">Đang dịch…</span>
      <button class="ib" data-a="close" title="Đóng (Esc)">✕</button></div>
      <div class="body"><span class="spin"></span><span class="muted" id="prog">Đang dịch…</span></div></div>`;
    place(root.getElementById("card"), info.rect, 380);
    try {
      const res = await TR.translate(info.text, { engine: S.selEngine, target: S.selTarget,
        onProgress: (x) => { const p = root.getElementById("prog"); if (p) p.textContent = `Đang tải gói ngôn ngữ của Chrome… ${Math.round(x * 100)}%`; } });
      if (id !== seq) return;
      current.result = res;
      render(info, res);
    } catch (e) {
      if (id !== seq) return;
      render(info, null, e.message);
    }
  }

  function render(info, res, error) {
    const L = TR.LANG_NAMES;
    const card = root.getElementById("card");
    if (!card) return;
    const bar = res ? `${esc(L[res.detectedLang] || res.detectedLang || "?")} → ${esc(L[S.selTarget] || S.selTarget)} · ${esc(TR.ENGINE_NAMES[res.engine] || "")}` : "Không dịch được";
    let body;
    if (error) {
      body = `<div class="err">${esc(error)}</div>
        <div class="foot">Đổi bộ dịch trong popup của extension (mục “Dịch khi bôi đen”).</div>`;
    } else if (res.kind === "same") {
      body = `<div class="muted">Đoạn này đã là ${esc(L[S.selTarget] || S.selTarget)}.</div>`;
    } else if (res.kind === "word") {
      body = `<div class="word"><b>${esc(res.lemma || info.text)}</b>${res.ipa ? `<span class="ipa">${esc(res.ipa)}</span>` : ""}${res.pos ? `<span class="pos">${esc(res.pos)}</span>` : ""}</div>
        <div class="tr"><b>${esc(res.translation)}</b></div>
        ${res.meanings?.length ? `<ul>${res.meanings.map((m) => `<li>${esc(m)}</li>`).join("")}</ul>` : ""}
        ${res.example ? `<div class="ex">${esc(res.example)}${res.exampleVi ? `<br>${esc(res.exampleVi)}` : ""}</div>` : ""}`;
    } else {
      body = `<div class="tr">${esc(res.translation)}</div>`;
    }
    const short = info.text.length <= 40 && info.text.split(/\s+/).length <= 3;
    card.innerHTML = `<div class="bar"><span class="lang">${bar}</span>
        ${res ? `<button class="ib" data-a="speak" title="Nghe phát âm câu gốc">🔊</button>
        <button class="ib" data-a="copy" title="Sao chép bản dịch">⧉</button>
        ${short ? `<button class="ib" data-a="save" title="Lưu vào sổ từ">☆</button>` : ""}` : ""}
        <button class="ib" data-a="window" title="Mở trong cửa sổ dịch">⤢</button>
        <button class="ib" data-a="close" title="Đóng (Esc)">✕</button></div><div class="body">${body}</div>`;
    place(card, info.rect, 380);
  }

  function toast(msg) {
    const c = root.getElementById("card");
    if (!c) return;
    const t = document.createElement("div");
    t.className = "toast";
    t.textContent = msg;
    t.style.left = c.style.left;
    t.style.top = parseFloat(c.style.top) - 30 + "px";
    wrap().appendChild(t);
    setTimeout(() => t.remove(), 1500);
  }

  async function act(a) {
    const res = current?.result;
    if (a === "close") return close();
    if (a === "window") { chrome.runtime.sendMessage({ type: "openTranslator", text: current?.text || "" }); return close(); }
    if (a === "copy" && res) {
      try { await navigator.clipboard.writeText(res.translation); toast("Đã sao chép bản dịch"); }
      catch { toast("Trình duyệt chặn sao chép"); }
    }
    if (a === "speak" && current) {
      try {
        speechSynthesis.cancel();
        const u = new SpeechSynthesisUtterance(current.text);
        u.lang = { en: "en-US", ja: "ja-JP", zh: "zh-CN", ko: "ko-KR", fr: "fr-FR", de: "de-DE" }[res?.detectedLang] || "en-US";
        speechSynthesis.speak(u);
      } catch {}
    }
    if (a === "save" && res) {
      const { words = [] } = await chrome.storage.local.get("words");
      const lemma = res.lemma || current.text;
      if (!words.some((w) => w.lemma === lemma)) {
        words.push({ lemma, reading: res.ipa || "", meaning: res.translation, jlpt: null, example: "", exampleVi: "",
                     page: location.href, lang: res.detectedLang, addedAt: new Date().toISOString() });
        await chrome.storage.local.set({ words });
      }
      toast(`Đã lưu “${lemma}” vào sổ từ`);
    }
  }

  // ------------------------------------------------------------------ sự kiện
  document.addEventListener("mouseup", (e) => {
    if (!enabled() || e.button !== 0) return;
    if (host && e.composedPath().includes(host)) return;         // bấm trong khung dịch
    setTimeout(() => {                                           // chờ trình duyệt cập nhật vùng chọn
      const info = selectionInfo();
      if (!info) return;
      if (current && current.text === info.text) return;
      if (info.text.length > 5000) { ensureHost(); current = info; wrap().innerHTML = ""; return; }
      if (S.selMode === "button") showButton(info); else run(info);
    }, 10);
  }, true);

  document.addEventListener("mousedown", (e) => {
    if (!current || (host && e.composedPath().includes(host))) return;
    close();
  }, true);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && current) close(); }, true);
  window.addEventListener("resize", () => current && close());

  document.addEventListener("click", (e) => {
    if (!host || !e.composedPath().includes(host)) return;
    const b = e.composedPath().find((n) => n.dataset && n.dataset.a);
    if (b) act(b.dataset.a);
  }, true);

  // menu chuột phải "Dịch … sang tiếng Việt"
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg?.type !== "translateSelection") return false;
    const info = selectionInfo() || { text: msg.text, rect: { left: 40, right: 40, top: 40, bottom: 60 } };
    run({ ...info, text: msg.text || info.text });
    sendResponse({ ok: true });
    return false;
  });
})();
