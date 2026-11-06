// Trang xem: đồng bộ video ↔ transcript, phân tích, tra từ, chế độ học.
import { $, $$, api, cueTextHTML, esc, fmtTime, ICONS, initTheme, speakerPrefixHTML, store, toast, toggleTheme } from "./common.js";
import { createPlayer } from "./player.js";
import { applySettings, loadSettings, openSettings, saveSettings } from "./settings.js";

initTheme();
const params = new URLSearchParams(location.search);
const videoId = params.get("v");
const S = loadSettings();
applySettings(S);

$$("[data-ico]").forEach((el) => (el.outerHTML = ICONS[el.dataset.ico]));
$("#themeBtn").innerHTML = ICONS.moon;
$("#themeBtn").onclick = toggleTheme;

let doc, cues = [], speakerMap = {}, player;
let activeIdx = -1;        // cue tô sáng trong danh sách (cue cuối cùng đã bắt đầu)
let showIdx = -1;          // cue đang hiện trên phụ đề (đang trong khoảng thời gian)
let analysisIdx = -1;
let offset = 0;            // chỉnh lệch thời gian (giây), lưu theo video
let pausedFor = null;      // id cue đã tự dừng (tránh dừng lặp)
let shadowTimer = null, hint = "";
let lastUserScroll = 0;
let syncState = { level: "wait", text: "Đang tải trình phát…" };
let anaSub = "vocab";

const fav = store.get("vt.fav", {});
const words = store.get("vt.words", []);
const seenLemmas = new Set();

// ---------------------------------------------------------------- tải dữ liệu
async function init() {
  if (!videoId) { $("#subBox").innerHTML = `<p class="muted">Thiếu tham số ?v=</p>`; return; }
  try {
    doc = await api(`/api/videos/${encodeURIComponent(videoId)}`);
  } catch (e) {
    $("#subBox").innerHTML = `<p class="err-text">${esc(e.message)}</p>`;
    return;
  }
  document.title = `${doc.title} – Xem & học`;
  $("#editLink").href = `/edit?v=${encodeURIComponent(videoId)}`;
  cues = doc.cues;
  speakerMap = Object.fromEntries((doc.speakers || []).map((s) => [s.name, s]));
  offset = store.get(`vt.offset.${videoId}`, 0);

  renderDialog();
  renderAnalysis();
  loadEpisodes();
  applyViewSettings();

  player = createPlayer($("#player"), doc.player);
  player.on("ready", () => {
    player.setRate(S.rate);
    const t = Number(params.get("t"));
    if (t) player.seek(t);
    updateSync();
  });
  player.on("error", (msg) => { syncState = { level: "err", text: msg }; renderSyncDot(); });
  player.on("state", (s) => { if (s === "playing") { clearShadow(); } });
  setInterval(tick, 80);
}

// ---------------------------------------------------------------- đồng bộ
function findIdx(t) {
  // tìm nhị phân cue cuối cùng có start <= t
  let lo = 0, hi = cues.length - 1, ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (cues[mid].start <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return ans;
}

let lastT = 0;
function tick() {
  if (!player?.ready) return;
  const t = player.getTime() + offset;
  const jumped = Math.abs(t - lastT) > 1.5;
  if (jumped) pausedFor = null;
  lastT = t;
  const idx = findIdx(t);
  const inside = idx >= 0 && t < cues[idx].end + 0.25 ? idx : -1;
  if (idx !== activeIdx) setActive(idx);
  if (inside !== showIdx) { showIdx = inside; renderSubtitle(); }

  // tự dừng cuối câu
  const c = cues[idx];
  if (c && !player.isPaused() && t >= c.end - 0.08 && t < c.end + 0.5 && pausedFor !== c.id && shouldPause(c)) {
    pausedFor = c.id;
    player.pause();
    if (S.viewMode === "shadow") startShadow(c);
    else if (S.viewMode === "read") { hint = "Nhấn Space hoặc → để đọc tiếp"; renderSubtitle(); }
    else { hint = "Đã tự dừng cuối câu – nhấn Space để tiếp tục"; renderSubtitle(); }
  }
  if (c?.type === "speech") c.vocab?.forEach((v) => t > c.end && seenLemmas.add(v.lemma));
  updateSync();
}

function shouldPause(c) {
  if (c.type !== "speech") return false;
  if (S.viewMode === "read" || S.viewMode === "shadow") return true;
  if (S.autoPause === "each") return true;
  if (S.autoPause === "new") {
    const saved = new Set(words.map((w) => w.lemma));
    return (c.vocab || []).some((v) => !saved.has(v.lemma) && !seenLemmas.has(v.lemma) && v.meaning);
  }
  return false;
}

function startShadow(c) {
  const wait = Math.max(1.5, (c.end - c.start) * 1.3 / (S.rate || 1) + 0.5);
  const until = Date.now() + wait * 1000;
  clearShadow();
  const step = () => {
    const left = (until - Date.now()) / 1000;
    if (left <= 0) { clearShadow(); player.play(); return; }
    hint = `🎙 Nhại lại câu này… ${left.toFixed(1)}s (Space: tiếp ngay, R: nghe lại)`;
    renderSubtitle();
    shadowTimer = setTimeout(step, 100);
  };
  step();
}
function clearShadow() {
  if (shadowTimer) clearTimeout(shadowTimer);
  shadowTimer = null;
  if (hint) { hint = ""; renderSubtitle(); }
}

function updateSync() {
  if (!player) return;
  if (player.error) { syncState = { level: "err", text: player.error }; }
  else if (!player.ready) { syncState = { level: "wait", text: "Video chưa sẵn sàng – chưa khớp được với bảng phụ đề" }; }
  else {
    const d = player.getDuration();
    const last = cues.length ? cues[cues.length - 1].end : 0;
    if (doc.duration && d && Math.abs(d - doc.duration) > 2) {
      syncState = { level: "warn", text: `Thời lượng video (${fmtTime(d)}) khác transcript (${fmtTime(doc.duration)}) – phụ đề có thể lệch` };
    } else if (d && last > d + 2) {
      syncState = { level: "warn", text: "Transcript dài hơn video – có thể sai tập" };
    } else {
      syncState = { level: "ok", text: "Đang khớp với video" };
    }
  }
  renderSyncDot();
}
function renderSyncDot() {
  const color = { ok: "#2fb170", warn: "#e3a21a", err: "#e53945", wait: "#9a9aa8" }[syncState.level];
  $("#syncDot").style.background = color;
}

// ---------------------------------------------------------------- hội thoại
function rowHTML(c, i) {
  const sp = speakerMap[c.speaker];
  const color = c.type === "speech" ? sp?.color || "#9aa0b4" : "#c3c3cc";
  const isFav = (fav[videoId] || []).includes(c.id);
  const ja = speakerPrefixHTML(c, speakerMap) + cueTextHTML(c, speakerMap);
  return `<div class="cue" data-idx="${i}" id="cue-${c.id}">
    <button class="play" style="background:${color}" data-play="${i}" title="Phát từ ${fmtTime(c.start)}">${ICONS.play}</button>
    <div>
      <div class="ja" data-cue="${i}">${ja}</div>
      ${c.romaji ? `<div class="romaji">${esc(c.romaji)}</div>` : ""}
      ${c.translation ? `<div class="tr">${esc(c.translation)}</div>` : ""}
    </div>
    <button class="heart ${isFav ? "on" : ""}" data-fav="${c.id}" title="Lưu câu yêu thích">${ICONS.heart}</button>
  </div>`;
}

function renderDialog() {
  const body = $("#tab-dialog");
  const credit = `<div class="cue credit" style="background:var(--active-bg);color:#fff">
      <button class="play" style="background:var(--accent)" data-play="-1">${ICONS.play}</button>
      <div><div class="ja">${esc(doc.title)}</div><div class="tr" style="color:#d6c9cb">${esc(doc.credit || "")}</div></div><span></span></div>`;
  body.innerHTML = credit + cues.map(rowHTML).join("") +
    (cues.length ? "" : `<div class="empty">Transcript trống</div>`);
  body.addEventListener("scroll", () => { if (!programmaticScroll) lastUserScroll = Date.now(); });
}
let programmaticScroll = false;

function setActive(idx) {
  const body = $("#tab-dialog");
  $(".cue.active:not(.credit)", body)?.classList.remove("active");
  activeIdx = idx;
  if (idx >= 0) {
    analysisIdx = idx;
    const row = $(`.cue[data-idx="${idx}"]`, body);
    row?.classList.add("active");
    if (row && Date.now() - lastUserScroll > 3000 && !body.classList.contains("hidden")) {
      programmaticScroll = true;
      body.scrollTo({ top: row.offsetTop - body.clientHeight / 2 + row.offsetHeight / 2, behavior: "smooth" });
      setTimeout(() => (programmaticScroll = false), 600);
    }
  }
  renderAnalysis();
}

function seekToCue(i) {
  clearShadow();
  if (i < 0) { player.seek(0); player.play(); return; }
  const c = cues[i];
  pausedFor = null;
  player.seek(c.start - offset + 0.01);
  player.play();
}

// ---------------------------------------------------------------- phụ đề
function renderSubtitle() {
  const box = $("#subBox"), ov = $("#overlaySub");
  let html;
  if (showIdx >= 0) {
    const c = cues[showIdx];
    html = `<div class="sub-line" data-cue="${showIdx}">
      <div class="ja">${speakerPrefixHTML(c, speakerMap)}${cueTextHTML(c, speakerMap)}</div>
      ${c.romaji ? `<div class="romaji">${esc(c.romaji)}</div>` : ""}
      ${c.translation ? `<div class="vi">${esc(c.translation)}</div>` : ""}</div>`;
  } else if (activeIdx < 0) {
    html = `<div class="sub-line sub-credit"><div class="ja">${esc(doc.title)}</div><div class="vi">${esc(doc.credit || "")}</div></div>`;
  } else {
    html = `<div class="sub-line"><div class="vi muted">&nbsp;</div></div>`;
  }
  const hintHTML = hint ? `<div class="shadow-hint">${esc(hint)}</div>` : "";
  box.innerHTML = html + hintHTML;
  ov.innerHTML = showIdx >= 0 ? html : "";
  ov.classList.toggle("hidden", S.subMode !== "overlay" || showIdx < 0);
  box.classList.toggle("hidden", S.subMode !== "box" && !hint);
}

// ---------------------------------------------------------------- phân tích
function renderAnalysis() {
  const body = $("#tab-analysis");
  if (body.classList.contains("hidden") && analysisIdx >= 0 && body.dataset.rendered === String(analysisIdx)) return;
  body.dataset.rendered = String(analysisIdx);
  const c = cues[analysisIdx];
  if (!c) { body.innerHTML = `<div class="empty">Phát video hoặc bấm một câu để xem phân tích.</div>`; return; }
  const v = c.vocab || [], k = c.kanji || [], g = c.grammar || [];
  const head = `<div class="now"><div class="meta">CÂU THOẠI ĐANG PHÁT · ${fmtTime(c.start)} – ${fmtTime(c.end)} · #${c.id}/${cues.length}</div>
    <div class="ja" data-cue="${analysisIdx}">${speakerPrefixHTML(c, speakerMap)}${cueTextHTML(c, speakerMap)}</div>
    ${c.translation ? `<div class="tr muted">${esc(c.translation)}</div>` : ""}</div>`;
  if (c.type !== "speech") {
    body.innerHTML = head + `<div class="empty">Cue này không có từ (${c.type === "music" ? "nhạc" : "tiếng động"}).</div>`;
    return;
  }
  const tabs = [["vocab", "Từ vựng", v.length], ["kanji", "Kanji", k.length], ["grammar", "Ngữ pháp", g.length]];
  let list = "";
  if (anaSub === "vocab") {
    list = v.length ? v.map((x) => `<div class="ana-item"><div class="head">
        <span class="big">${esc(x.lemma)}</span><span class="reading" style="color:var(--accent)">${esc(x.reading)}</span>
        ${x.jlpt ? `<span class="jlpt">${esc(x.jlpt)}</span>` : ""}
        <button class="btn small save-word" data-save='${esc(JSON.stringify({ lemma: x.lemma, reading: x.reading, meaning: x.meaning, jlpt: x.jlpt, cue: c.id }))}'>${isSaved(x.lemma) ? "✓ Đã lưu" : "+ Sổ từ"}</button></div>
        <div>${esc(x.meaning) || '<span class="muted">Chưa có nghĩa (cần chạy dịch/phân tích)</span>'}</div>
        <div class="muted" style="font-size:12px">${esc(x.pos || "")}</div></div>`).join("")
      : `<div class="empty">Không có từ vựng.</div>`;
  } else if (anaSub === "kanji") {
    list = k.length ? k.map((x) => `<div class="ana-item"><div class="head"><span class="big kanji-big">${esc(x.char)}</span>
        <div><div style="font-weight:800">${esc(x.hanViet || "")}</div><div>${esc(x.meaning || "")}</div></div></div>
        <div style="font-size:13px;margin-top:6px"><b>On:</b> ${esc((x.on || []).join("、") || "–")} &nbsp; <b>Kun:</b> ${esc((x.kun || []).join("、") || "–")}</div></div>`).join("")
      : `<div class="empty">Câu này không có kanji.</div>`;
  } else {
    list = g.length ? g.map((x) => `<div class="ana-item"><div class="head"><span class="big" style="font-size:17px">${esc(x.pattern)}</span>
        ${x.jlpt ? `<span class="jlpt">${esc(x.jlpt)}</span>` : ""}</div>
        <div style="font-weight:600">${esc(x.meaning)}</div><div class="muted" style="font-size:13px">${esc(x.explanation)}</div></div>`).join("")
      : `<div class="empty">Chưa có mẫu ngữ pháp cho câu này.</div>`;
  }
  body.innerHTML = head + `<div class="subtabs">${tabs.map(([key, l, n]) =>
    `<button class="subtab ${anaSub === key ? "active" : ""}" data-sub-tab="${key}">${l}<span class="count">${n}</span></button>`).join("")}</div>` + list;
}

// ---------------------------------------------------------------- tập
async function loadEpisodes() {
  const body = $("#tab-episodes");
  if (!doc.series) {
    $("#epTab").textContent = "Tập (1)";
    body.innerHTML = `<div class="empty">Video chưa thuộc series nào.<br>Đặt tên series trong trang Sửa transcript.</div>`;
    return;
  }
  try {
    const eps = await api(`/api/series/${encodeURIComponent(doc.series)}/episodes`);
    $("#epTab").textContent = `Tập (${eps.length})`;
    body.innerHTML = `<div class="muted" style="font-size:13px;margin:0 6px 8px">${esc(doc.series)}</div>` + eps.map((e) =>
      `<a class="ep ${e.videoId === videoId ? "current" : ""}" href="/watch?v=${encodeURIComponent(e.videoId)}">
        <span class="ep-num">${e.episode ?? "–"}</span><span><div>${esc(e.title)}</div>
        <div class="muted" style="font-size:12px">${e.cueCount} câu · ${fmtTime(e.duration)}</div></span></a>`).join("");
  } catch (e) { body.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}

// ---------------------------------------------------------------- tra từ
let pop, popTimer, hideTimer;
function tokenAt(el) {
  const holder = el.closest("[data-cue]");
  const c = cues[Number(holder?.dataset.cue)];
  return c ? { c, t: c.tokens[Number(el.dataset.i)] } : null;
}
function lookupMeaning(c, t) {
  const v = (c.vocab || []).find((x) => x.lemma === t.lemma);
  if (v?.meaning) return v;
  for (const o of cues) {               // từ cùng lemma ở câu khác
    const w = (o.vocab || []).find((x) => x.lemma === t.lemma && x.meaning);
    if (w) return w;
  }
  return v || null;
}
function isSaved(lemma) { return words.some((w) => w.lemma === lemma); }

function showPopup(el) {
  const r = tokenAt(el);
  if (!r?.t) return;
  const { c, t } = r;
  hidePopup(true);
  const v = lookupMeaning(c, t);
  $$(".w.hl").forEach((x) => x.classList.remove("hl"));
  el.classList.add("hl");
  pop = document.createElement("div");
  pop.className = "popover word-pop";
  const lemmaLine = t.lemma !== t.surface ? `<div class="row">Dạng từ điển: <b style="color:var(--text)">${esc(t.lemma)}</b> ${esc(t.lemmaReading || "")}</div>` : "";
  const saved = isSaved(t.lemma);
  pop.innerHTML = `<div class="surface">${esc(t.surface)}</div>
    <div class="reading">${esc(t.reading)} <span class="muted" style="font-weight:400">${esc(t.romaji || "")}</span></div>
    ${lemmaLine}
    <div class="meaning">${v?.meaning ? esc(v.meaning) : '<span class="muted">Chưa có nghĩa cho từ này</span>'}</div>
    <div class="row"><span class="badge">${esc(t.pos)}</span>${v?.jlpt ? `<span class="jlpt">${esc(v.jlpt)}</span>` : ""}
      <span style="flex:1"></span>
      <button class="btn small ${saved ? "" : "primary"}" data-saveword>${saved ? "✓ Đã lưu" : "Lưu vào sổ từ"}</button></div>`;
  document.body.appendChild(pop);
  const rect = el.getBoundingClientRect();
  const w = pop.offsetWidth;
  let left = rect.left + scrollX + rect.width / 2 - w / 2;
  left = Math.max(8, Math.min(left, scrollX + innerWidth - w - 8));
  let top = rect.bottom + scrollY + 6;
  if (rect.bottom + pop.offsetHeight + 12 > innerHeight) top = rect.top + scrollY - pop.offsetHeight - 6;
  pop.style.left = left + "px";
  pop.style.top = top + "px";
  pop.addEventListener("mouseenter", () => clearTimeout(hideTimer));
  pop.addEventListener("mouseleave", () => scheduleHide());
  $("[data-saveword]", pop).onclick = () => {
    if (!isSaved(t.lemma)) {
      saveWord({ lemma: t.lemma, reading: t.lemmaReading || t.reading, meaning: v?.meaning || "", jlpt: v?.jlpt || null, cue: c.id });
      showPopup(el);
    }
  };
}
function hidePopup(now) { clearTimeout(hideTimer); pop?.remove(); pop = null; if (now !== true) $$(".w.hl").forEach((x) => x.classList.remove("hl")); }
function scheduleHide() { clearTimeout(hideTimer); hideTimer = setTimeout(hidePopup, 250); }

function saveWord(w) {
  const c = cues.find((x) => x.id === w.cue);
  words.push({ ...w, example: c?.text || "", exampleVi: c?.translation || "", videoId, addedAt: new Date().toISOString() });
  store.set("vt.words", words);
  toast(`Đã lưu “${w.lemma}” vào sổ từ`);
  renderAnalysis();
}

document.addEventListener("mouseover", (e) => {
  const w = e.target.closest(".w.word");
  if (w && S.hoverLookup) {
    clearTimeout(popTimer); clearTimeout(hideTimer);
    popTimer = setTimeout(() => showPopup(w), 180);
  }
});
document.addEventListener("mouseout", (e) => {
  if (e.target.closest(".w.word")) { clearTimeout(popTimer); if (pop) scheduleHide(); }
});

// ---------------------------------------------------------------- sự kiện click
document.addEventListener("click", (e) => {
  const word = e.target.closest(".w.word");
  if (word) {                      // chạm/bấm vào từ: luôn mở popup (kể cả trên mobile)
    e.stopPropagation();
    if (!player.isPaused()) player.pause();
    showPopup(word);
    return;
  }
  if (pop && !e.target.closest(".word-pop")) hidePopup();

  const play = e.target.closest("[data-play]");
  if (play) { seekToCue(Number(play.dataset.play)); return; }
  const favBtn = e.target.closest("[data-fav]");
  if (favBtn) {
    const id = Number(favBtn.dataset.fav);
    const list = (fav[videoId] ||= []);
    const i = list.indexOf(id);
    i >= 0 ? list.splice(i, 1) : list.push(id);
    store.set("vt.fav", fav);
    favBtn.classList.toggle("on", i < 0);
    return;
  }
  const save = e.target.closest("[data-save]");
  if (save) { const w = JSON.parse(save.dataset.save); if (!isSaved(w.lemma)) saveWord(w); return; }
  const sub = e.target.closest("[data-sub-tab]");
  if (sub) { anaSub = sub.dataset.subTab; $("#tab-analysis").dataset.rendered = ""; renderAnalysis(); return; }
  const tab = e.target.closest("[data-tab]");
  if (tab) {
    $$(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    $$(".side .tab-body").forEach((b) => b.classList.toggle("hidden", b.id !== `tab-${tab.dataset.tab}`));
    if (tab.dataset.tab === "analysis") { $("#tab-analysis").dataset.rendered = ""; renderAnalysis(); }
    if (tab.dataset.tab === "dialog") { lastUserScroll = 0; setActive(activeIdx); }
    return;
  }
  // dropdown
  const ddBtn = e.target.closest("[data-dd]");
  $$(".dd-menu").forEach((m) => { if (!ddBtn || m !== ddBtn.nextElementSibling) m.classList.add("hidden"); });
  if (ddBtn) { ddBtn.nextElementSibling.classList.toggle("hidden"); return; }
  const mode = e.target.closest("[data-mode]");
  if (mode) { setSetting("viewMode", mode.dataset.mode); mode.closest(".dd-menu").classList.add("hidden"); return; }
  const subm = e.target.closest("[data-sub]");
  if (subm) { setSetting("subMode", subm.dataset.sub); subm.closest(".dd-menu").classList.add("hidden"); return; }
});

function setSetting(k, v) { S[k] = v; saveSettings(S); applySettings(S); applyViewSettings(); }

function applyViewSettings() {
  $$("[data-mode]").forEach((b) => b.classList.toggle("sel", b.dataset.mode === S.viewMode));
  $$("[data-sub]").forEach((b) => b.classList.toggle("sel", b.dataset.sub === S.subMode));
  $("#ddMode [data-dd]").title = "Chế độ: " + { watch: "Xem", read: "Đọc", shadow: "Nói theo" }[S.viewMode];
  $("#panelBtn").classList.toggle("on", S.panel);
  $("#watch").classList.toggle("panel-off", !S.panel);
  $("#speedLabel").textContent = S.rate + "x";
  player?.ready && player.setRate(S.rate);
  if (doc) renderSubtitle();
}

$("#panelBtn").onclick = () => setSetting("panel", !S.panel);
$("#settingsBtn").onclick = () => openSettings(S, () => applyViewSettings());
$("#fullBtn").onclick = () => {
  if (document.fullscreenElement) document.exitFullscreen();
  else $("#mainCol").requestFullscreen?.().catch(() => toast("Trình duyệt không cho phép toàn màn hình"));
};
$("#speedLabel").onclick = () => {
  const R = [0.5, 0.75, 1, 1.25, 1.5, 2];
  setSetting("rate", R[(R.indexOf(S.rate) + 1) % R.length]);
};

$("#infoBtn").onclick = (e) => {
  e.stopPropagation();
  if ($(".sync-pop")) { $(".sync-pop").remove(); return; }
  const p = document.createElement("div");
  p.className = "popover sync-pop";
  const color = { ok: "#2fb170", warn: "#e3a21a", err: "#e53945", wait: "#9a9aa8" }[syncState.level];
  const src = { upload: "Phụ đề tải lên", asr: "Nhận dạng giọng nói (ASR)", youtube_manual: "Phụ đề YouTube (làm tay)", youtube_auto: "Phụ đề tự động YouTube" }[doc.source?.subtitle] || doc.source?.subtitle || "?";
  const draw = () => {
    p.innerHTML = `<div class="sync-state"><i style="background:${color}"></i>${esc(syncState.text)}</div>
    <div class="muted">Thời gian: ${fmtTime(player?.getTime?.() ?? 0)} · Câu: ${activeIdx >= 0 ? "#" + cues[activeIdx].id : "–"}/${cues.length}</div>
    <div class="muted">Nguồn transcript: ${esc(src)} · Phiên bản ${esc(doc.version)}</div>
    <div style="margin:10px 0 4px;font-weight:600">Chỉnh lệch phụ đề: ${offset >= 0 ? "+" : ""}${offset.toFixed(1)}s</div>
    <div class="seg">${[-0.5, -0.1, 0.1, 0.5].map((d) => `<button data-off="${d}">${d > 0 ? "+" : ""}${d}s</button>`).join("")}<button data-off="0">Đặt lại</button></div>
    <p class="muted" style="font-size:12px;margin:8px 0 0">Phụ đề hiện sớm → bấm số âm; hiện trễ → bấm số dương.</p>
    ${(doc.warnings || []).length ? `<div class="warn" style="margin-top:8px">⚠ ${doc.warnings.map(esc).join("<br>⚠ ")}</div>` : ""}
    <div style="margin-top:8px;font-size:12px" class="muted"><span style="color:#2fb170">●</span> khớp &nbsp;<span style="color:#e3a21a">●</span> có thể lệch &nbsp;<span style="color:#e53945">●</span> lỗi video &nbsp;<span style="color:#9a9aa8">●</span> đang tải</div>`;
  };
  draw();
  p.addEventListener("click", (ev) => {
    ev.stopPropagation();
    const b = ev.target.closest("[data-off]");
    if (!b) return;
    const d = Number(b.dataset.off);
    offset = d === 0 ? 0 : Math.round((offset + d) * 10) / 10;
    store.set(`vt.offset.${videoId}`, offset);
    draw();
  });
  document.body.appendChild(p);
  const r = $("#infoBtn").getBoundingClientRect();
  p.style.top = r.bottom + scrollY + 6 + "px";
  p.style.left = Math.max(8, r.right + scrollX - p.offsetWidth) + "px";
  setTimeout(() => document.addEventListener("click", function close(ev) {
    if (!ev.target.closest(".sync-pop")) { p.remove(); document.removeEventListener("click", close); }
  }), 0);
};

$("#helpBtn").onclick = () => modal(`<h3>Trợ giúp</h3>
  <div class="set-group"><h4>Phím tắt</h4>
  <div class="set-row"><span><kbd>Space</kbd> Phát / dừng (tiếp tục sau khi tự dừng)</span></div>
  <div class="set-row"><span><kbd>←</kbd> / <kbd>→</kbd> Câu trước / câu sau</span></div>
  <div class="set-row"><span><kbd>R</kbd> Nghe lại câu hiện tại</span></div>
  <div class="set-row"><span><kbd>[</kbd> / <kbd>]</kbd> Giảm / tăng tốc độ</span></div>
  <div class="set-row"><span><kbd>T</kbd> Ẩn/hiện bản dịch · <kbd>F</kbd> Furigana · <kbd>P</kbd> Bảng transcript</span></div></div>
  <div class="set-group"><h4>Chế độ</h4>
  <p><b>Xem</b>: phát liên tục. <b>Đọc</b>: dừng sau mỗi câu để đọc kỹ. <b>Nói theo</b>: dừng sau mỗi câu, chờ bạn nhại lại rồi tự phát tiếp.</p>
  <p>Rê chuột (hoặc chạm) vào từ để xem nghĩa và lưu vào sổ từ. Bấm nút ▶ ở mỗi câu để tua tới câu đó.</p></div>`);

$("#wordsBtn").onclick = () => {
  const rows = words.map((w, i) => `<div class="ana-item"><div class="head"><span class="big">${esc(w.lemma)}</span>
      <span style="color:var(--accent)">${esc(w.reading)}</span>${w.jlpt ? `<span class="jlpt">${esc(w.jlpt)}</span>` : ""}
      <button class="btn small save-word" data-del="${i}">Xoá</button></div><div>${esc(w.meaning)}</div>
      <div class="muted" style="font-size:12px">${esc(w.example)}</div></div>`).join("");
  const m = modal(`<div style="display:flex;align-items:center"><h3>Sổ từ (${words.length})</h3><span style="flex:1"></span>
      <button class="btn small" data-csv ${words.length ? "" : "disabled"}>Xuất CSV (Anki)</button></div>
      <div style="margin-top:12px">${rows || '<div class="empty">Chưa có từ nào. Rê chuột vào một từ và bấm “Lưu vào sổ từ”.</div>'}</div>`);
  m.addEventListener("click", (e) => {
    const d = e.target.closest("[data-del]");
    if (d) { words.splice(Number(d.dataset.del), 1); store.set("vt.words", words); m.closest(".modal-back").remove(); $("#wordsBtn").click(); renderAnalysis(); }
    if (e.target.closest("[data-csv]")) {
      const csv = words.map((w) => [w.lemma, w.reading, w.meaning, w.example, w.exampleVi].map((x) => `"${String(x ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv" }));
      a.download = "so-tu.csv";
      a.click();
    }
  });
};

function modal(html) {
  const back = document.createElement("div");
  back.className = "modal-back";
  back.innerHTML = `<div class="modal">${html}<div style="text-align:right;margin-top:12px"><button class="btn primary" data-x>Đóng</button></div></div>`;
  back.addEventListener("click", (e) => { if (e.target === back || e.target.closest("[data-x]")) back.remove(); });
  document.body.appendChild(back);
  return $(".modal", back);
}

// ---------------------------------------------------------------- bàn phím
addEventListener("keydown", (e) => {
  if (e.target.matches("input, textarea, select") || e.ctrlKey || e.metaKey || !player) return;
  const k = e.key;
  if (k === " ") {
    e.preventDefault();
    if (shadowTimer) { clearShadow(); player.play(); return; }
    if (player.isPaused()) { hint = ""; renderSubtitle(); player.play(); } else player.pause();
  } else if (k === "ArrowRight") {
    e.preventDefault(); seekToCue(Math.min(cues.length - 1, activeIdx + 1));
  } else if (k === "ArrowLeft") {
    e.preventDefault();
    const t = player.getTime() + offset;
    const i = activeIdx >= 0 && t - cues[activeIdx].start > 1 ? activeIdx : activeIdx - 1;
    seekToCue(Math.max(0, i));
  } else if (k === "r" || k === "R") { if (activeIdx >= 0) seekToCue(activeIdx); }
  else if (k === "[" || k === "]") {
    const R = [0.5, 0.75, 1, 1.25, 1.5, 2];
    const i = R.indexOf(S.rate) + (k === "]" ? 1 : -1);
    if (i >= 0 && i < R.length) { setSetting("rate", R[i]); toast(`Tốc độ ${S.rate}x`, 900); }
  } else if (k === "t" || k === "T") setSetting("viOn", !S.viOn);
  else if (k === "f" || k === "F") setSetting("furigana", !S.furigana);
  else if (k === "p" || k === "P") setSetting("panel", !S.panel);
  else if (k === "Escape") hidePopup();
});

init();
