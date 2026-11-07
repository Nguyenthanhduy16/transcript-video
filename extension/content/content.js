// Content script: phụ đề song ngữ + bảng transcript trên YouTube và trang có <video>.
// YouTube: tự chạy. Trang khác: bấm "Bật trên trang này" trong popup của extension.
(() => {
  if (window.__cnwebContent) return;
  window.__cnwebContent = true;
  const { esc, fmtTime, cueHTML, CSS } = window.CNWEB;
  const IS_YT = /(^|\.)youtube\.com$/.test(location.hostname);

  const DEFAULTS = { server: "http://localhost:8000", subOn: true, jaOn: true, viOn: true, furigana: true, romaji: false,
                     fontScale: 100, panelOn: true, hoverLookup: true, autoPause: "off", subBottom: 14, offset: 0 };
  let S = { ...DEFAULTS };

  // ------------------------------------------------------------------ trạng thái
  let video = null;          // <video> đang theo dõi
  let pageKey = null;        // link đại diện cho video (YouTube watch URL / link file / link trang)
  let doc = null, cues = [], speakerMap = {};
  let status = "no-video";   // no-video | checking | missing | creating | ready | error
  let statusMsg = "", job = null, ytInfo = null;
  let activeIdx = -1, showIdx = -1, pausedFor = null, hint = "";
  let tab = "dialog", lastUserScroll = 0, programmatic = false;
  let words = [];

  const api = (path, method = "GET", body) => new Promise((res) =>
    chrome.runtime.sendMessage({ type: "api", path, method, body }, (r) => res(r || { ok: false, error: chrome.runtime.lastError?.message || "Extension lỗi" })));

  // ------------------------------------------------------------------ giao diện (Shadow DOM)
  const host = document.createElement("div");
  host.id = "cnweb-transcript-host";
  host.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:2147483000;";
  const shadow = host.attachShadow({ mode: "open" });
  shadow.innerHTML = `<style>${CSS}</style>
    <div class="root">
      <div class="sub hidden" id="sub"><div class="sub-box" id="subBox"></div></div>
      <button class="fab hidden" id="fab" title="Bảng transcript (Transcript học ngoại ngữ)">字</button>
      <div class="panel hidden" id="panel">
        <div class="head" id="head"><span class="dot" id="dot"></span>
          <span class="title" id="title">Transcript<span class="sub2" id="sub2"></span></span>
          <button class="iconbtn" id="close" title="Ẩn bảng">✕</button></div>
        <div class="tabs" id="tabs"><button class="tab on" data-tab="dialog">Hội thoại</button><button class="tab" data-tab="analysis">Phân tích</button></div>
        <div class="toggles" id="toggles"></div>
        <div class="body" id="body"></div>
      </div>
      <div class="pop hidden" id="pop"></div>
    </div>`;
  const $ = (id) => shadow.getElementById(id);
  (document.documentElement || document.body).appendChild(host);

  function toast(msg) {
    const t = document.createElement("div");
    t.className = "toast";
    t.textContent = msg;
    shadow.querySelector(".root").appendChild(t);
    setTimeout(() => t.remove(), 2000);
  }

  // ------------------------------------------------------------------ cài đặt
  chrome.storage.sync.get("settings", ({ settings }) => { S = { ...DEFAULTS, ...(settings || {}) }; applySettings(); });
  chrome.storage.local.get("words", ({ words: w }) => { words = w || []; });
  chrome.storage.onChanged.addListener((ch) => {
    if (ch.settings) { S = { ...DEFAULTS, ...(ch.settings.newValue || {}) }; applySettings(); }
    if (ch.words) words = ch.words.newValue || [];
  });
  const saveSettings = () => chrome.storage.sync.set({ settings: S });
  function applySettings() {
    shadow.querySelector(".root").style.setProperty("--scale", S.fontScale / 100);
    $("subBox").classList.toggle("nofuri", !S.furigana);
    $("body").classList.toggle("nofuri", !S.furigana);
    renderToggles();
    renderSub();
    if (status === "ready") renderList();
    layout();
  }

  function renderToggles() {
    const chips = [["subOn", "Phụ đề"], ["jaOn", "Nhật"], ["viOn", "Việt"], ["furigana", "Furigana"], ["romaji", "Romaji"]];
    $("toggles").innerHTML = chips.map(([k, l]) => `<button class="chip ${S[k] ? "on" : ""}" data-k="${k}">${l}</button>`).join("") +
      `<button class="chip ${S.autoPause === "each" ? "on" : ""}" data-k="autoPause" title="Tự dừng cuối mỗi câu">Dừng mỗi câu</button>
       <button class="chip" data-k="fontDown" title="Chữ nhỏ hơn">A−</button><button class="chip" data-k="fontUp" title="Chữ lớn hơn">A+</button>`;
  }

  // ------------------------------------------------------------------ tìm video + khoá trang
  function findVideo() {
    if (IS_YT) return document.querySelector("#movie_player video.html5-main-video") || document.querySelector("video");
    let best = null, area = 0;
    for (const v of document.querySelectorAll("video")) {
      const r = v.getBoundingClientRect();
      if (r.width * r.height > area) { best = v; area = r.width * r.height; }
    }
    return area > 100 * 60 ? best : null;
  }
  function ytId() {
    const u = new URL(location.href);
    if (u.pathname === "/watch") return u.searchParams.get("v");
    const m = u.pathname.match(/^\/(shorts|live|embed)\/([\w-]{6,})/);
    return m ? m[2] : null;
  }
  function computeKey(v) {
    if (IS_YT) { const id = ytId(); return id ? `https://www.youtube.com/watch?v=${id}` : null; }
    const src = v && (v.currentSrc || v.src);
    return src && /^https?:/.test(src) ? src : location.href.split("#")[0];
  }

  let checkTimer = null;
  function scan() {
    const v = findVideo();
    const key = v ? computeKey(v) : null;
    if (v !== video) attachVideo(v);
    if (key !== pageKey) {
      pageKey = key;
      reset();
      if (key) { clearTimeout(checkTimer); checkTimer = setTimeout(check, 400); }
    }
    layout();
  }
  function attachVideo(v) {
    if (video) { video.removeEventListener("play", onPlay); video.removeEventListener("seeking", onSeek); }
    video = v;
    if (video) { video.addEventListener("play", onPlay); video.addEventListener("seeking", onSeek); }
  }
  const onPlay = () => { hint = ""; renderSub(); };
  const onSeek = () => { pausedFor = null; };

  function reset() {
    doc = null; cues = []; speakerMap = {}; job = null; ytInfo = null;
    activeIdx = showIdx = -1; pausedFor = null; hint = "";
    setStatus(pageKey ? "checking" : "no-video");
  }

  function setStatus(s, msg = "") {
    status = s; statusMsg = msg;
    $("fab").classList.toggle("hidden", !video);
    $("dot").style.background = { ready: "#2fb170", creating: "#e3a21a", error: "#e53945", missing: "#9a9aa8" }[s] || "#9a9aa8";
    $("tabs").classList.toggle("hidden", s !== "ready");
    $("toggles").classList.toggle("hidden", s !== "ready");
    $("sub2").textContent = s === "ready" ? (doc.credit || "") : "";
    $("title").firstChild.textContent = s === "ready" ? doc.title : "Transcript học ngoại ngữ";
    renderBody();
    renderSub();
  }

  // ------------------------------------------------------------------ server: kiểm tra / tạo transcript
  async function check() {
    const key = pageKey;
    if (!key) return;
    setStatus("checking");
    const r = await api(`/api/resolve?url=${encodeURIComponent(key)}`);
    if (key !== pageKey) return;
    if (!r.ok) return setStatus("error", r.error);
    if (r.data.exists) return loadDoc(r.data.videoId);
    const { jobs: saved = {} } = await chrome.storage.local.get("jobs");
    if (saved[key]) { job = { id: saved[key] }; return poll(); }
    setStatus("missing");
    if (IS_YT) fetchYtTracks();
  }

  async function loadDoc(videoId) {
    const r = await api(`/api/videos/${encodeURIComponent(videoId)}`);
    if (!r.ok) return setStatus("error", r.error);
    doc = r.data;
    cues = doc.cues || [];
    speakerMap = Object.fromEntries((doc.speakers || []).map((s) => [s.name, s]));
    setStatus("ready");
  }

  function fetchYtTracks() {
    const reqId = Math.random().toString(36).slice(2);
    const onMsg = (ev) => {
      if (ev.source !== window || ev.data?.__cnweb !== "tracks" || ev.data.reqId !== reqId) return;
      window.removeEventListener("message", onMsg);
      ytInfo = ev.data;
      if (status === "missing") renderBody();
    };
    window.addEventListener("message", onMsg);
    window.postMessage({ __cnweb: "get-tracks", reqId }, "*");
    setTimeout(() => window.removeEventListener("message", onMsg), 5000);
  }

  function jaTrack() {
    const t = (ytInfo?.tracks || []).filter((x) => /^ja/.test(x.lang));
    return t.find((x) => x.kind !== "asr") || t[0] || null;
  }

  // ---- phụ đề YouTube → WebVTT (YouTube trả json3, srv3/XML hoặc VTT tuỳ yêu cầu)
  function vttTime(ms) {
    const t = Math.max(0, Math.round(ms));
    const h = Math.floor(t / 3600000), m = Math.floor(t / 60000) % 60, s = Math.floor(t / 1000) % 60, x = t % 1000;
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}.${String(x).padStart(3, "0")}`;
  }
  function decodeEntities(s) { const ta = document.createElement("textarea"); ta.innerHTML = s; return ta.value; }
  function toVtt(body) {
    if (!body) return "";
    const txt = body.trim();
    if (txt.startsWith("WEBVTT")) return txt;
    let items = [];
    if (txt.startsWith("{")) {                       // json3
      try {
        const j = JSON.parse(txt);
        for (const e of j.events || []) {
          if (!e.segs || e.aAppend) continue;
          const text = e.segs.map((g) => g.utf8 || "").join("").replace(/\n+/g, " ").trim();
          if (text) items.push({ s: e.tStartMs || 0, e: (e.tStartMs || 0) + (e.dDurationMs || 2000), text });
        }
      } catch { return ""; }
    } else if (txt.startsWith("<")) {                // srv3 (<p t d>) hoặc srv1 (<text start dur>)
      const doc = new DOMParser().parseFromString(txt, "text/xml");
      for (const n of doc.querySelectorAll("p")) {
        const text = decodeEntities(n.textContent || "").replace(/\s+/g, " ").trim();
        if (text) items.push({ s: +n.getAttribute("t") || 0, e: (+n.getAttribute("t") || 0) + (+n.getAttribute("d") || 2000), text });
      }
      if (!items.length) for (const n of doc.querySelectorAll("text")) {
        const st = parseFloat(n.getAttribute("start") || "0") * 1000, du = parseFloat(n.getAttribute("dur") || "2") * 1000;
        const text = decodeEntities(n.textContent || "").replace(/\s+/g, " ").trim();
        if (text) items.push({ s: st, e: st + du, text });
      }
    }
    items.sort((x, y) => x.s - y.s);
    // phụ đề tự động "cuộn" chồng thời gian → cắt end tại start của dòng sau
    for (let i = 0; i < items.length - 1; i++) if (items[i].e > items[i + 1].s) items[i].e = Math.max(items[i].s + 300, items[i + 1].s);
    if (!items.length) return "";
    return "WEBVTT\n\n" + items.map((x) => `${vttTime(x.s)} --> ${vttTime(x.e)}\n${x.text}\n`).join("\n");
  }

  function captureFromPlayer(t) {
    return new Promise((resolve) => {
      const reqId = Math.random().toString(36).slice(2);
      const onMsg = (ev) => {
        if (ev.source !== window || ev.data?.__cnweb !== "subs" || ev.data.reqId !== reqId) return;
        window.removeEventListener("message", onMsg);
        resolve(ev.data.body || "");
      };
      window.addEventListener("message", onMsg);
      window.postMessage({ __cnweb: "capture-subs", reqId, lang: t.lang, kind: t.kind }, "*");
      setTimeout(() => { window.removeEventListener("message", onMsg); resolve(""); }, 15000);
    });
  }

  async function createFromYtSubs() {
    const t = jaTrack();
    if (!t) return;
    setStatus("creating", "Đang đọc phụ đề tiếng Nhật trên trang…");
    let vtt = "";
    // 1) tải trực tiếp link phụ đề (chạy được với video/tài khoản chưa bị YouTube đòi PO token)
    try {
      const u = new URL(t.baseUrl, location.origin);
      u.searchParams.set("fmt", "vtt");
      vtt = toVtt(await (await fetch(u.toString(), { credentials: "include" })).text());
    } catch (e) { /* thử cách 2 */ }
    // 2) nhờ player YouTube tự tải (có PO token) rồi bắt lại nội dung
    if (!vtt) {
      setStatus("creating", "Đang lấy phụ đề qua trình phát YouTube…");
      vtt = toVtt(await captureFromPlayer(t));
    }
    if (!vtt) {
      return setStatus("missing", "Không lấy được phụ đề từ YouTube. Thử bật phụ đề tiếng Nhật (nút CC) trên video vài giây rồi bấm lại, hoặc dùng “Nhận dạng giọng nói trên server”.");
    }
    const r = await api("/api/jobs/subtitle", "POST", {
      url: pageKey, subtitle: vtt, format: "vtt", subtitle_kind: t.kind === "asr" ? "youtube_auto" : "youtube_manual",
      title: ytInfo?.title || document.title.replace(/ - YouTube$/, ""), duration: ytInfo?.duration || video?.duration || null,
    });
    startJob(r);
  }

  async function createByAsr() {
    const n = Number(shadow.getElementById("nspk")?.value) || null;
    setStatus("creating", "Đang gửi yêu cầu…");
    const title = IS_YT ? (ytInfo?.title || document.title.replace(/ - YouTube$/, "")) : document.title;
    const r = await api("/api/jobs", "POST", { url: pageKey, title, lang: "ja", target: "vi", num_speakers: n });
    startJob(r);
  }

  async function startJob(r) {
    if (!r.ok) return setStatus("missing", r.error);
    job = r.data;
    const { jobs: saved = {} } = await chrome.storage.local.get("jobs");
    saved[pageKey] = job.id;
    chrome.storage.local.set({ jobs: saved });
    poll();
  }

  async function poll() {
    const key = pageKey;
    while (job && key === pageKey) {
      const r = await api(`/api/jobs/${job.id}`);
      if (key !== pageKey) return;
      if (!r.ok) { await forgetJob(key); return setStatus("missing", r.error); }
      job = r.data;
      const j = job;              // forgetJob() đặt job = null
      if (j.status === "done") {
        await forgetJob(key);
        if (j.warnings?.length) toast("⚠ " + j.warnings[0].slice(0, 120));
        return loadDoc(j.videoId);
      }
      if (j.status === "error") { await forgetJob(key); return setStatus("missing", j.error); }
      setStatus("creating", job.message || "Đang xử lý");
      await new Promise((ok) => setTimeout(ok, 1500));
    }
  }
  async function forgetJob(key) {
    const { jobs: saved = {} } = await chrome.storage.local.get("jobs");
    delete saved[key];
    await chrome.storage.local.set({ jobs: saved });
    job = null;
  }

  // ------------------------------------------------------------------ vẽ bảng
  function renderBody() {
    const body = $("body");
    if (status === "ready") { renderList(); return; }
    if (status === "no-video") { body.innerHTML = `<div class="empty">Không thấy video trên trang này.</div>`; return; }
    if (status === "checking") { body.innerHTML = `<div class="empty">Đang kiểm tra transcript trên server…</div>`; return; }
    if (status === "error") {
      body.innerHTML = `<div class="empty"><b>Không kết nối được server</b><div class="err">${esc(statusMsg)}</div>
        <button class="btn" data-act="retry">Thử lại</button></div>`;
      return;
    }
    if (status === "creating") {
      const pct = job?.progress ?? 3;
      body.innerHTML = `<div class="empty"><b>Đang tạo transcript</b><div class="bar"><div style="width:${pct}%"></div></div>
        <div class="muted">${esc(statusMsg)} · ${Math.round(pct)}%</div>
        <div class="muted" style="font-size:12px;margin-top:8px">Có thể tiếp tục xem video, bảng sẽ tự cập nhật.</div></div>`;
      return;
    }
    // missing
    const t = IS_YT ? jaTrack() : null;
    // phụ đề tự động (asr) của YouTube có ngôn ngữ = ngôn ngữ nói trong video
    const spoken = IS_YT ? (ytInfo?.tracks || []).find((x) => x.kind === "asr" && !/^ja/.test(x.lang)) : null;
    body.innerHTML = `<div class="empty"><b>Video này chưa có transcript</b>
      <p class="muted">Tạo một lần, lần sau mở lại sẽ có ngay.</p>
      ${spoken ? `<p class="err" style="margin-top:0">Video này có vẻ nói ${esc(spoken.name.replace(/\s*\(.*\)$/, ""))}. Tool hiện chỉ hỗ trợ video tiếng Nhật; phụ đề tiếng Nhật (nếu có) có thể chỉ là bản dịch tự động.</p>` : ""}
      ${IS_YT ? (t ? `<button class="btn primary" data-act="subs">Tạo từ phụ đề YouTube<br><span style="font-weight:500;font-size:12px">${esc(t.name)}${t.kind === "asr" ? " (tự động)" : ""}</span></button>`
                   : `<p class="muted" style="font-size:12px">${ytInfo ? "Video không có phụ đề tiếng Nhật." : "Đang đọc danh sách phụ đề…"}</p>`) : ""}
      <button class="btn ${IS_YT && t ? "" : "primary"}" data-act="asr">Nhận dạng giọng nói trên server</button>
      <div style="font-size:12px;margin-top:6px" class="muted">Số người nói (nếu biết):
        <select id="nspk"><option value="">tự đoán</option>${[1, 2, 3, 4, 5, 6].map((n) => `<option>${n}</option>`).join("")}</select></div>
      ${statusMsg ? `<div class="err">${esc(statusMsg)}</div>` : ""}
      ${!IS_YT && !/^https?:/.test(video?.currentSrc || "") ? `<p class="muted" style="font-size:12px">Video phát dạng luồng (blob), server sẽ thử tải từ link trang.</p>` : ""}</div>`;
  }

  function rowHTML(c, i) {
    const color = c.type === "speech" ? (speakerMap[c.speaker]?.color || "#9aa0b4") : "#c3c3cc";
    return `<div class="cue${i === activeIdx ? " on" : ""}" data-idx="${i}">
      <button class="play" style="background:${esc(color)}" data-seek="${i}" title="Phát từ ${fmtTime(c.start)}">▶</button>
      <div>${S.jaOn ? `<div class="ja">${cueHTML(c, i, speakerMap)}</div>` : ""}
        ${S.romaji && c.romaji ? `<div class="romaji">${esc(c.romaji)}</div>` : ""}
        ${S.viOn && c.translation ? `<div class="tr">${esc(c.translation)}</div>` : ""}</div></div>`;
  }

  function renderList() {
    const body = $("body");
    if (tab === "analysis") { renderAnalysis(); return; }
    body.innerHTML = cues.length ? cues.map(rowHTML).join("") : `<div class="empty">Transcript trống.</div>`;
    scrollToActive(true);
  }

  function renderAnalysis() {
    const c = cues[activeIdx];
    const body = $("body");
    if (!c) { body.innerHTML = `<div class="empty">Phát video hoặc bấm ▶ ở một câu để xem phân tích.</div>`; return; }
    let h = `<div class="now"><div class="meta">${fmtTime(c.start)} – ${fmtTime(c.end)} · #${c.id}/${cues.length}</div>
      <div class="ja">${cueHTML(c, activeIdx, speakerMap)}</div>${c.translation ? `<div class="muted">${esc(c.translation)}</div>` : ""}</div>`;
    if (c.type !== "speech") { body.innerHTML = h + `<div class="empty">Cue này không có từ.</div>`; return; }
    const v = c.vocab || [], k = c.kanji || [], g = c.grammar || [];
    h += `<div class="sec">Từ vựng (${v.length})</div>` + (v.map((x) => `<div class="item"><span class="big">${esc(x.lemma)}</span><span class="rd">${esc(x.reading)}</span>${x.jlpt ? `<span class="jlpt">${esc(x.jlpt)}</span>` : ""}
        <div>${x.meaning ? esc(x.meaning) : '<span class="muted">chưa có nghĩa</span>'}</div></div>`).join("") || `<div class="muted" style="padding:0 6px">—</div>`);
    h += `<div class="sec">Kanji (${k.length})</div>` + (k.map((x) => `<div class="item"><span class="big">${esc(x.char)}</span> <b>${esc(x.hanViet || "")}</b> · ${esc(x.meaning || "")}
        <div class="muted" style="font-size:12px">On: ${esc((x.on || []).join("、") || "–")} · Kun: ${esc((x.kun || []).join("、") || "–")}</div></div>`).join("") || `<div class="muted" style="padding:0 6px">—</div>`);
    h += `<div class="sec">Ngữ pháp (${g.length})</div>` + (g.map((x) => `<div class="item"><b>${esc(x.pattern)}</b>${x.jlpt ? `<span class="jlpt">${esc(x.jlpt)}</span>` : ""}
        <div>${esc(x.meaning)}</div><div class="muted" style="font-size:12px">${esc(x.explanation || "")}</div></div>`).join("") || `<div class="muted" style="padding:0 6px">—</div>`);
    if (k.length) h += `<div class="src">Kanji: KANJIDIC2 © EDRDG (CC BY-SA 4.0)</div>`;
    body.innerHTML = h;
  }

  function scrollToActive(force) {
    if (tab !== "dialog" || activeIdx < 0) return;
    const body = $("body");
    const row = body.querySelector(`.cue[data-idx="${activeIdx}"]`);
    if (!row || (!force && Date.now() - lastUserScroll < 3000)) return;
    programmatic = true;
    body.scrollTo({ top: row.offsetTop - body.clientHeight / 2 + row.offsetHeight / 2, behavior: force ? "auto" : "smooth" });
    setTimeout(() => (programmatic = false), 500);
  }
  $("body").addEventListener("scroll", () => { if (!programmatic) lastUserScroll = Date.now(); });

  // ------------------------------------------------------------------ phụ đề trên video
  function renderSub() {
    const box = $("subBox");
    const on = status === "ready" && S.subOn && video;
    let html = "";
    if (on && showIdx >= 0) {
      const c = cues[showIdx];
      if (S.jaOn) html += `<div class="ja">${cueHTML(c, showIdx, speakerMap)}</div>`;
      if (S.romaji && c.romaji) html += `<div class="romaji">${esc(c.romaji)}</div>`;
      if (S.viOn && c.translation) html += `<div class="vi">${esc(c.translation)}</div>`;
    }
    if (on && hint) html += `<div class="hint">${esc(hint)}</div>`;
    box.innerHTML = html;
    $("sub").classList.toggle("hidden", !html);
  }

  function layout() {
    if (!video || !video.isConnected) { $("sub").classList.add("hidden"); $("fab").classList.add("hidden"); return; }
    const r = video.getBoundingClientRect();
    const sub = $("sub");
    sub.style.left = r.left + "px";
    sub.style.width = r.width + "px";
    sub.style.bottom = Math.max(0, window.innerHeight - r.bottom + r.height * (S.subBottom / 100)) + "px";
    const fab = $("fab");
    fab.classList.toggle("off", !S.panelOn);
    fab.style.left = Math.max(4, r.right - 46) + "px";
    fab.style.top = Math.max(4, r.top + 10) + "px";
    fab.classList.toggle("hidden", r.width < 120);
    $("panel").classList.toggle("hidden", !S.panelOn);
  }

  // ------------------------------------------------------------------ đồng bộ theo thời gian video
  function findIdx(t) {
    let lo = 0, hi = cues.length - 1, ans = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (cues[m].start <= t) { ans = m; lo = m + 1; } else hi = m - 1; }
    return ans;
  }
  function tick() {
    if (status !== "ready" || !video || !cues.length) return;
    const t = video.currentTime + (S.offset || 0);
    const idx = findIdx(t);
    const until = idx >= 0 ? Math.max(cues[idx].end + 0.25, cues[idx].start + 1) : 0;
    const inside = idx >= 0 && t < until ? idx : -1;
    if (idx !== activeIdx) {
      activeIdx = idx;
      const body = $("body");
      body.querySelector(".cue.on")?.classList.remove("on");
      body.querySelector(`.cue[data-idx="${idx}"]`)?.classList.add("on");
      if (tab === "analysis") renderAnalysis(); else scrollToActive(false);
    }
    if (inside !== showIdx) { showIdx = inside; renderSub(); }
    const c = cues[idx];
    if (S.autoPause === "each" && c && c.type === "speech" && !video.paused && t >= c.end - 0.08 && t < c.end + 0.5 && pausedFor !== c.id) {
      pausedFor = c.id;
      video.pause();
      hint = "Đã dừng cuối câu – nhấn Space hoặc ] để tiếp";
      renderSub();
    }
  }
  setInterval(tick, 80);
  setInterval(scan, 1000);
  window.addEventListener("resize", layout);
  document.addEventListener("scroll", layout, true);
  (function raf() { layout(); setTimeout(() => requestAnimationFrame(raf), 250); })();
  document.addEventListener("fullscreenchange", () => {
    const fs = document.fullscreenElement;
    (fs && fs !== host ? fs : document.documentElement).appendChild(host);
    setTimeout(layout, 100);
  });
  if (IS_YT) document.addEventListener("yt-navigate-finish", () => setTimeout(scan, 300));

  function seekTo(i) {
    if (!video || !cues[i]) return;
    pausedFor = null; hint = "";
    video.currentTime = Math.max(0, cues[i].start - (S.offset || 0) + 0.01);
    video.play().catch(() => {});
  }

  // ------------------------------------------------------------------ tra từ
  let popTimer = null, hideTimer = null;
  function showPop(el) {
    const c = cues[Number(el.dataset.c)];
    const t = c?.tokens?.[Number(el.dataset.i)];
    if (!t) return;
    shadow.querySelectorAll(".w.hl").forEach((x) => x.classList.remove("hl"));
    el.classList.add("hl");
    let v = (c.vocab || []).find((x) => x.lemma === t.lemma && x.meaning);
    if (!v) for (const o of cues) { v = (o.vocab || []).find((x) => x.lemma === t.lemma && x.meaning); if (v) break; }
    const saved = words.some((w) => w.lemma === t.lemma);
    const pop = $("pop");
    pop.innerHTML = `<div class="s">${esc(t.surface)}</div><div class="r">${esc(t.reading)} <span class="muted" style="font-weight:400">${esc(t.romaji || "")}</span></div>
      ${t.lemma !== t.surface ? `<div class="row">Dạng từ điển: <b style="color:var(--fg)">${esc(t.lemma)}</b> ${esc(t.lemmaReading || "")}</div>` : ""}
      <div class="m">${v ? esc(v.meaning) : '<span class="muted">Chưa có nghĩa cho từ này</span>'}</div>
      <div class="row"><span>${esc(t.pos)}</span>${v?.jlpt ? `<span class="jlpt">${esc(v.jlpt)}</span>` : ""}
        <button class="btn ${saved ? "" : "primary"}" data-save="1">${saved ? "✓ Đã lưu" : "Lưu vào sổ từ"}</button></div>`;
    pop.classList.remove("hidden");
    pop._data = { c, t, v };
    const r = el.getBoundingClientRect();
    const w = 260;
    pop.style.left = Math.max(8, Math.min(r.left + r.width / 2 - w / 2, innerWidth - w - 8)) + "px";
    const h = pop.offsetHeight;
    pop.style.top = (r.top - h - 8 > 8 ? r.top - h - 8 : r.bottom + 8) + "px";
  }
  function hidePop() { $("pop").classList.add("hidden"); shadow.querySelectorAll(".w.hl").forEach((x) => x.classList.remove("hl")); }

  shadow.addEventListener("mouseover", (e) => {
    const w = e.target.closest?.(".w.word");
    if (w && S.hoverLookup) { clearTimeout(popTimer); clearTimeout(hideTimer); popTimer = setTimeout(() => showPop(w), 180); }
    if (e.target.closest?.("#pop")) clearTimeout(hideTimer);
  });
  shadow.addEventListener("mouseout", (e) => {
    if (e.target.closest?.(".w.word") || e.target.closest?.("#pop")) { clearTimeout(popTimer); hideTimer = setTimeout(hidePop, 300); }
  });

  // ------------------------------------------------------------------ sự kiện
  shadow.addEventListener("click", async (e) => {
    const el = e.target;
    const w = el.closest(".w.word");
    if (w) { e.stopPropagation(); if (video && !video.paused) video.pause(); showPop(w); return; }
    if (el.closest("[data-save]")) {
      const { c, t, v } = $("pop")._data || {};
      if (t && !words.some((x) => x.lemma === t.lemma)) {
        words.push({ lemma: t.lemma, reading: t.lemmaReading || t.reading, meaning: v?.meaning || "", jlpt: v?.jlpt || null,
                     example: c.text, exampleVi: c.translation || "", page: pageKey, addedAt: new Date().toISOString() });
        await chrome.storage.local.set({ words });
        toast(`Đã lưu “${t.lemma}” vào sổ từ`);
        hidePop();
      }
      return;
    }
    if (!el.closest("#pop")) hidePop();
    const seek = el.closest("[data-seek]");
    if (seek) { seekTo(Number(seek.dataset.seek)); return; }
    const tb = el.closest("[data-tab]");
    if (tb) {
      tab = tb.dataset.tab;
      shadow.querySelectorAll(".tab").forEach((x) => x.classList.toggle("on", x === tb));
      renderList();
      return;
    }
    const chip = el.closest("[data-k]");
    if (chip) {
      const k = chip.dataset.k;
      if (k === "autoPause") S.autoPause = S.autoPause === "each" ? "off" : "each";
      else if (k === "fontUp") S.fontScale = Math.min(200, S.fontScale + 10);
      else if (k === "fontDown") S.fontScale = Math.max(60, S.fontScale - 10);
      else S[k] = !S[k];
      saveSettings();
      return;
    }
    const act = el.closest("[data-act]")?.dataset.act;
    if (act === "subs") createFromYtSubs();
    else if (act === "asr") createByAsr();
    else if (act === "retry") check();
    if (el.closest("#close")) { S.panelOn = false; saveSettings(); }
    if (el.closest("#fab")) { S.panelOn = !S.panelOn; saveSettings(); }
  });

  // kéo bảng transcript bằng thanh tiêu đề
  (() => {
    let drag = null;
    $("head").addEventListener("mousedown", (e) => {
      if (e.target.closest("button")) return;
      const r = $("panel").getBoundingClientRect();
      drag = { dx: e.clientX - r.left, dy: e.clientY - r.top };
      e.preventDefault();
    });
    window.addEventListener("mousemove", (e) => {
      if (!drag) return;
      const p = $("panel");
      p.style.left = Math.max(0, Math.min(innerWidth - 120, e.clientX - drag.dx)) + "px";
      p.style.top = Math.max(0, Math.min(innerHeight - 60, e.clientY - drag.dy)) + "px";
      p.style.right = "auto";
    });
    window.addEventListener("mouseup", () => (drag = null));
  })();

  // phím tắt: [ câu trước · ] câu sau · \ nghe lại câu (không trùng phím của YouTube)
  window.addEventListener("keydown", (e) => {
    if (status !== "ready" || e.ctrlKey || e.metaKey || e.altKey) return;
    const tag = (document.activeElement?.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || document.activeElement?.isContentEditable) return;
    if (e.key === "[") { seekTo(Math.max(0, activeIdx - 1)); e.stopPropagation(); }
    else if (e.key === "]") { seekTo(Math.min(cues.length - 1, activeIdx + 1)); e.stopPropagation(); }
    else if (e.key === "\\") { seekTo(Math.max(0, activeIdx)); e.stopPropagation(); }
  }, true);

  // ------------------------------------------------------------------ popup hỏi trạng thái
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg?.type === "status") {
      sendResponse({ status, statusMsg, pageKey, title: doc?.title || null, cueCount: cues.length,
                     videoId: doc?.videoId || null, progress: job?.progress ?? null, hasVideo: !!video });
    } else if (msg?.type === "recheck") { check(); sendResponse({ ok: true }); }
    return false;
  });

  scan();
})();
