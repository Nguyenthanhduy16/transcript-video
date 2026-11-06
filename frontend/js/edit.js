// Trang chỉnh sửa transcript: sửa mốc thời gian, người nói, loại cue, câu gốc, bản dịch.
import { $, $$, api, esc, fmtTime, initTheme, toast } from "./common.js";
import { createPlayer } from "./player.js";

initTheme();
const videoId = new URLSearchParams(location.search).get("v");
let doc, player, dirty = false, activeRow = -1;

async function init() {
  doc = await api(`/api/videos/${encodeURIComponent(videoId)}`);
  document.title = `Sửa – ${doc.title}`;
  $("#watchLink").href = `/watch?v=${encodeURIComponent(videoId)}`;
  $("#fTitle").value = doc.title || "";
  $("#fSeries").value = doc.series || "";
  $("#fEpisode").value = doc.episode ?? "";
  $("#fGlossary").value = doc.glossary || "";
  $("#exports").innerHTML = [["srt", "both", "SRT song ngữ"], ["srt", doc.lang, "SRT gốc"], ["srt", doc.target, "SRT dịch"], ["vtt", "both", "VTT"], ["json", "", "JSON"]]
    .map(([f, l, t]) => `<a class="btn small" href="/api/videos/${encodeURIComponent(videoId)}/export.${f}${l ? "?lang=" + l : ""}" download>${t}</a>`).join("");
  renderSpeakers();
  renderRows();
  renderMeta();
  if (!player) {
    player = createPlayer($("#player"), doc.player);
    setInterval(highlight, 200);
  }
}

function renderMeta() {
  $("#cueCount").textContent = `${doc.cues.length} câu · phiên bản ${doc.version}`;
  $("#needCount").textContent = (doc.needsAnalysis || []).length;
  $("#warnings").innerHTML = (doc.warnings || []).map((w) => `<div class="warn">⚠ ${esc(w)}</div>`).join("");
}

function renderSpeakers() {
  $("#speakers").innerHTML = (doc.speakers || []).map((s, i) => `<div class="spk-row" data-sp="${i}">
      <input value="${esc(s.name)}" disabled title="Tên gốc trong transcript">
      <input data-k="display" value="${esc(s.display)}" placeholder="Tên hiển thị">
      <input data-k="color" type="color" value="${esc(s.color)}"></div>`).join("") ||
    `<p class="muted" style="font-size:13px">Chưa có người nói. Điền cột “Người nói” ở bảng bên phải.</p>`;
}

function speakerOptions() {
  return `<datalist id="spkList">${(doc.speakers || []).map((s) => `<option value="${esc(s.name)}">`).join("")}</datalist>`;
}

function renderRows() {
  const need = new Set(doc.needsAnalysis || []);
  $("#rows").innerHTML = doc.cues.map((c, i) => `<tr data-row="${i}" class="${need.has(c.id) ? "need" : ""}">
    <td><button class="btn small" data-seek="${i}" title="Tua tới câu này">${c.id ?? "mới"}</button></td>
    <td><input class="t" data-k="start" type="number" step="0.01" value="${c.start}"><div class="muted" style="font-size:11px">${fmtTime(c.start)}</div></td>
    <td><input class="t" data-k="end" type="number" step="0.01" value="${c.end}"></td>
    <td><input data-k="speaker" list="spkList" value="${esc(c.speaker || "")}" style="min-width:80px"></td>
    <td><select data-k="type">${["speech", "music", "sfx"].map((t) => `<option ${t === c.type ? "selected" : ""}>${t}</option>`).join("")}</select></td>
    <td><textarea data-k="text" rows="2" lang="ja">${esc(c.text)}</textarea></td>
    <td><textarea data-k="translation" rows="2">${esc(c.translation || "")}</textarea></td>
    <td><button class="btn small" data-del="${i}" title="Xoá câu">✕</button></td></tr>`).join("") + speakerOptions();
}

function highlight() {
  if (!player?.ready) return;
  const t = player.getTime();
  const i = doc.cues.findIndex((c) => t >= c.start && t < c.end);
  if (i !== activeRow) {
    $(`tr[data-row="${activeRow}"]`)?.classList.remove("active");
    $(`tr[data-row="${i}"]`)?.classList.add("active");
    activeRow = i;
  }
}

function markDirty() { dirty = true; $("#saveBtn").textContent = "Lưu thay đổi •"; }

$("#rows").addEventListener("input", (e) => {
  const tr = e.target.closest("tr[data-row]");
  const k = e.target.dataset.k;
  if (!tr || !k) return;
  const c = doc.cues[Number(tr.dataset.row)];
  c[k] = e.target.type === "number" ? Number(e.target.value) : e.target.value;
  tr.classList.add("dirty");
  markDirty();
});
$("#rows").addEventListener("click", (e) => {
  const s = e.target.closest("[data-seek]");
  if (s) { const c = doc.cues[Number(s.dataset.seek)]; player.seek(c.start); player.play(); }
  const d = e.target.closest("[data-del]");
  if (d && confirm("Xoá câu này?")) { doc.cues.splice(Number(d.dataset.del), 1); renderRows(); markDirty(); }
});
$("#rows").addEventListener("keydown", (e) => {
  if (e.altKey && (e.key === "s" || e.key === "e") && player?.ready) {
    const tr = e.target.closest("tr[data-row]");
    if (!tr) return;
    e.preventDefault();
    const k = e.key === "s" ? "start" : "end";
    const v = Math.round(player.getTime() * 100) / 100;
    doc.cues[Number(tr.dataset.row)][k] = v;
    $(`[data-k="${k}"]`, tr).value = v;
    tr.classList.add("dirty"); markDirty();
  }
});
$("#speakers").addEventListener("input", (e) => {
  const row = e.target.closest("[data-sp]");
  if (!row) return;
  doc.speakers[Number(row.dataset.sp)][e.target.dataset.k] = e.target.value;
  markDirty();
});
["fTitle", "fSeries", "fEpisode", "fGlossary"].forEach((id) => $("#" + id).addEventListener("input", markDirty));

$("#addBtn").onclick = () => {
  const t = player?.ready ? Math.round(player.getTime() * 100) / 100 : (doc.cues.at(-1)?.end ?? 0);
  doc.cues.push({ id: null, start: t, end: t + 2, speaker: "", type: "speech", text: "", translation: "" });
  doc.cues.sort((a, b) => a.start - b.start);
  renderRows(); markDirty();
};

async function save() {
  const body = {
    title: $("#fTitle").value, series: $("#fSeries").value,
    episode: $("#fEpisode").value === "" ? null : Number($("#fEpisode").value),
    glossary: $("#fGlossary").value, speakers: doc.speakers,
    cues: doc.cues.filter((c) => c.text.trim()).map((c) => ({ id: c.id, start: c.start, end: c.end, speaker: c.speaker || null, type: c.type, text: c.text, translation: c.translation || "" })),
  };
  try {
    doc = await api(`/api/videos/${encodeURIComponent(videoId)}`, { method: "PUT", body });
    dirty = false;
    $("#saveBtn").textContent = "Lưu thay đổi";
    renderSpeakers(); renderRows(); renderMeta();
    toast(`Đã lưu – phiên bản ${doc.version}`);
    return true;
  } catch (e) { toast("Lỗi: " + e.message, 4000); return false; }
}
$("#saveBtn").onclick = save;

async function retranslate(all) {
  if (dirty && !(await save())) return;
  try {
    const job = await api(`/api/videos/${encodeURIComponent(videoId)}/retranslate`, { method: "POST", body: { all } });
    const poll = setInterval(async () => {
      const j = await api(`/api/jobs/${job.id}`);
      $("#jobStatus").textContent = `${j.message} – ${Math.round(j.progress)}%`;
      if (j.status === "done" || j.status === "error") {
        clearInterval(poll);
        $("#jobStatus").innerHTML = j.status === "done" ? "✓ Đã dịch xong" : `<span class="err-text">${esc(j.error)}</span>`;
        if (j.status === "done") init();
      }
    }, 1200);
  } catch (e) { toast(e.message, 4000); }
}
$("#reChanged").onclick = () => retranslate(false);
$("#reAll").onclick = () => retranslate(true);
addEventListener("beforeunload", (e) => { if (dirty) e.preventDefault(); });

init().catch((e) => { document.querySelector("main").innerHTML = `<p class="err-text container">${esc(e.message)}</p>`; });
