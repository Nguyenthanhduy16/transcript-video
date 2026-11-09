const TR = globalThis.CNWEB_TR;
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let last = null;

async function go() {
  const text = $("#src").value.trim();
  if (!text) return;
  $("#out").textContent = "Đang dịch…";
  try {
    const r = await TR.translate(text, { engine: $("#engine").value, target: "vi",
      onProgress: (x) => { $("#out").textContent = `Đang tải gói ngôn ngữ của Chrome… ${Math.round(x * 100)}%`; } });
    last = r;
    $("#lang").textContent = `${TR.LANG_NAMES[r.detectedLang] || r.detectedLang} → Tiếng Việt · ${TR.ENGINE_NAMES[r.engine] || ""}`;
    if (r.kind === "word") {
      $("#out").innerHTML = `<b>${esc(r.lemma || text)}</b>${r.ipa ? `<span class="ipa">${esc(r.ipa)}</span>` : ""} ${r.pos ? `<span class="muted small">${esc(r.pos)}</span>` : ""}
        <div><b>${esc(r.translation)}</b></div>${r.meanings?.length ? `<ul>${r.meanings.map((m) => `<li>${esc(m)}</li>`).join("")}</ul>` : ""}
        ${r.example ? `<div class="ex">${esc(r.example)}${r.exampleVi ? "<br>" + esc(r.exampleVi) : ""}</div>` : ""}`;
    } else {
      $("#out").textContent = r.kind === "same" ? "Đoạn này đã là tiếng Việt." : r.translation;
    }
  } catch (e) {
    $("#out").innerHTML = `<div class="err">${esc(e.message)}</div>`;
  }
}

$("#go").onclick = go;
$("#src").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) go(); });
$("#copy").onclick = async () => { if (last) { try { await navigator.clipboard.writeText(last.translation); $("#copy").textContent = "Đã sao chép"; } catch {} } };
$("#speak").onclick = () => {
  const u = new SpeechSynthesisUtterance($("#src").value);
  u.lang = { en: "en-US", ja: "ja-JP" }[last?.detectedLang] || "en-US";
  speechSynthesis.cancel(); speechSynthesis.speak(u);
};
$("#engine").onchange = async () => {
  const { settings = {} } = await chrome.storage.sync.get("settings");
  await chrome.storage.sync.set({ settings: { ...settings, selEngine: $("#engine").value } });
  go();
};
(async () => {
  const { settings = {} } = await chrome.storage.sync.get("settings");
  $("#engine").value = settings.selEngine || "auto";
  const t = new URLSearchParams(location.search).get("text");
  if (t) { $("#src").value = t; go(); } else $("#src").focus();
})();
