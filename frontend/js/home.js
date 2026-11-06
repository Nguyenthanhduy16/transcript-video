import { $, api, esc, fmtTime, ICONS, initTheme, toast, toggleTheme } from "./common.js";

initTheme();
$("#themeBtn").innerHTML = ICONS.moon;
$("#themeBtn").onclick = toggleTheme;

const STAGE = { queued: "Đang chờ", fetch: "Lấy nguồn", asr: "Nhận dạng giọng nói", segment: "Chia câu",
  diarize: "Người nói", furigana: "Furigana", translate: "Dịch & phân tích", save: "Lưu", done: "Xong" };

async function loadHealth() {
  try {
    const h = await api("/api/health");
    $("#health").textContent = `ASR: ${h.asr ? "có" : "chưa cài"} · Diarization: ${h.diarization ? "có" : "tắt"}`;
  } catch {}
}

let polling = null;
async function loadJobs() {
  const jobs = await api("/api/jobs");
  const el = $("#jobs");
  if (!jobs.length) { el.innerHTML = `<p class="muted">Chưa có job nào.</p>`; return false; }
  el.innerHTML = jobs.slice(0, 8).map((j) => {
    const badge = j.status === "done" ? "ok" : j.status === "error" ? "err" : "run";
    const label = { done: "Hoàn tất", error: "Lỗi", running: "Đang chạy", queued: "Đang chờ" }[j.status];
    return `<div class="job">
      <div><b>${esc(j.label)}</b> <span class="badge ${badge}">${label}</span>
        <div class="muted" style="font-size:13px">${esc(STAGE[j.stage] || j.stage)} · ${esc(j.message || "")}</div>
        ${j.error ? `<div class="err-text">${esc(j.error)}</div>` : ""}
        ${(j.warnings || []).map((w) => `<div class="warn">⚠ ${esc(w)}</div>`).join("")}</div>
      <div>${j.status === "done" && j.videoId ? `<a class="btn small primary" href="/watch?v=${encodeURIComponent(j.videoId)}">Xem</a>` : `<span class="muted">${Math.round(j.progress)}%</span>`}</div>
      <div class="progress"><div style="width:${j.progress}%"></div></div></div>`;
  }).join("");
  return jobs.some((j) => j.status === "running" || j.status === "queued");
}

async function loadLibrary() {
  const vids = await api("/api/videos");
  const el = $("#library");
  if (!vids.length) { el.innerHTML = `<p class="muted">Chưa có video nào. Hãy tạo transcript đầu tiên ở trên.</p>`; return; }
  vids.sort((a, b) => (a.series || "").localeCompare(b.series || "") || (a.episode ?? 0) - (b.episode ?? 0));
  el.innerHTML = vids.map((v) => {
    const thumb = v.player?.type === "youtube" ? `background-image:url('https://i.ytimg.com/vi/${encodeURIComponent(v.player.youtubeId)}/mqdefault.jpg')` : "";
    return `<div class="lib-item">
      <a class="lib-thumb" style="${thumb}" href="/watch?v=${encodeURIComponent(v.videoId)}">${thumb ? "" : "▶ " + esc(v.player?.type === "html5" ? "Video" : "")}</a>
      <div class="lib-body">
        <a class="lib-title" href="/watch?v=${encodeURIComponent(v.videoId)}">${esc(v.title)}</a>
        <div class="muted" style="font-size:12px">${v.series ? esc(v.series) + (v.episode != null ? ` · Tập ${v.episode}` : "") + " · " : ""}${v.cueCount} câu · ${fmtTime(v.duration)}</div>
        <div class="lib-actions"><a class="btn small primary" href="/watch?v=${encodeURIComponent(v.videoId)}">Xem</a>
          <a class="btn small" href="/edit?v=${encodeURIComponent(v.videoId)}">Sửa</a></div>
      </div></div>`;
  }).join("");
}

async function refresh() {
  const busy = await loadJobs().catch(() => false);
  if (!busy) { clearInterval(polling); polling = null; loadLibrary(); }
}
function startPolling() { if (!polling) polling = setInterval(refresh, 1500); refresh(); }

$("#urlForm").onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const body = Object.fromEntries(f);
  body.episode = body.episode ? Number(body.episode) : null;
  body.force_asr = f.has("force_asr");
  body.allow_auto_subs = f.has("allow_auto_subs");
  try {
    await api("/api/jobs", { method: "POST", body });
    toast("Đã thêm vào hàng đợi");
    e.target.reset();
    startPolling();
  } catch (err) { toast("Lỗi: " + err.message, 4000); }
};

$("#uploadForm").onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  if (!f.get("subtitle")?.size) f.delete("subtitle");
  if (!f.get("episode")) f.delete("episode");
  const btn = e.target.querySelector("button[type=submit]");
  btn.disabled = true; btn.textContent = "Đang tải lên…";
  try {
    await api("/api/jobs/upload", { method: "POST", body: f });
    toast("Đã tải lên, đang xử lý");
    e.target.reset();
    startPolling();
  } catch (err) { toast("Lỗi: " + err.message, 4000); }
  btn.disabled = false; btn.textContent = "Tải lên & xử lý";
};

loadHealth();
loadLibrary();
startPolling();
