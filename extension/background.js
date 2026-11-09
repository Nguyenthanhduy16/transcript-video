// Service worker: gọi API của server transcript thay cho content script
// (origin của extension + host_permissions → không vướng CORS của trang đang xem).
const DEFAULT_SERVER = "http://localhost:8000";

async function serverUrl() {
  const { settings = {} } = await chrome.storage.sync.get("settings");
  return (settings.server || DEFAULT_SERVER).replace(/\/+$/, "");
}

async function callApi({ path, method = "GET", body }) {
  const server = await serverUrl();
  try {
    const r = await fetch(server + path, {
      method,
      headers: body ? { "content-type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = null;
    try { data = await r.json(); } catch {}
    if (!r.ok) {
      const detail = data && data.detail;
      return { ok: false, status: r.status, error: typeof detail === "string" ? detail : (detail ? JSON.stringify(detail) : r.statusText) };
    }
    return { ok: true, status: r.status, data };
  } catch (e) {
    return { ok: false, status: 0, error: `Không kết nối được server ${server}. Kiểm tra server đã chạy và địa chỉ trong phần Cài đặt của extension.` };
  }
}

// ---------------------------------------------------------------- dịch khi bôi đen
const CJK = /[\u3040-\u30ff\u3400-\u9fff]/;
const isShort = (t) => !t.includes("\n") && (CJK.test(t) ? t.length <= 12 && !/[。！？、]/.test(t)
                                                          : t.length <= 40 && t.trim().split(/\s+/).length <= 3);

// bảng kanji KANJIDIC2 (EDRDG, CC BY-SA 4.0) nhúng trong extension: âm Hán Việt, On/Kun, nghĩa tiếng Anh, số nét
let kanjiDic = null;
async function loadKanji() {
  if (kanjiDic) return kanjiDic;
  const r = await fetch(chrome.runtime.getURL("data/kanjidic.json.gz"));
  const stream = r.body.pipeThrough(new DecompressionStream("gzip"));
  kanjiDic = JSON.parse(await new Response(stream).text());
  return kanjiDic;
}
async function kanjiLookup(chars) {
  const d = await loadKanji();
  return chars.filter((c) => d[c]).map((c) => ({ char: c, on: d[c].on || [], kun: d[c].kun || [],
    hanViet: (d[c].vi || []).slice(0, 2).map((v) => v.toUpperCase()).join("/"), meaning: (d[c].en || []).slice(0, 3).join(", "),
    meaningLang: "en", strokes: d[c].strokes || null }));
}

async function googleTranslate(text, source, target) {
  // endpoint công khai của Google Dịch (không chính thức, không cần key)
  const params = new URLSearchParams({ client: "gtx", sl: source || "auto", tl: target, dj: "1" });
  ["t", "bd", "rm"].forEach((d) => params.append("dt", d));
  const url = "https://translate.googleapis.com/translate_a/single?" + params;
  const r = text.length > 1500
    ? await fetch(url, { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded;charset=UTF-8" }, body: "q=" + encodeURIComponent(text) })
    : await fetch(url + "&q=" + encodeURIComponent(text));
  if (!r.ok) throw new Error(`Google Dịch trả lỗi HTTP ${r.status}`);
  const j = await r.json();
  const translation = (j.sentences || []).map((x) => x.trans || "").join("");
  if (!translation) throw new Error("Google Dịch không trả kết quả");
  const translit = (j.sentences || []).map((x) => x.src_translit || "").join("").trim();
  const out = { translation, detectedLang: j.src || source, engine: "google", kind: "text" };
  if (translit) out.translit = translit;            // tiếng Nhật: romaji của câu gốc
  if (isShort(text) && j.dict && j.dict.length) {
    out.kind = "word";
    out.meanings = j.dict.slice(0, 4).map((d) => `${d.pos ? d.pos + ": " : ""}${(d.terms || []).slice(0, 5).join(", ")}`);
    if (translit) out.ipa = translit;
  }
  return out;
}

async function serverTranslate(text, source, target) {
  const r = await callApi({ path: "/api/translate", method: "POST", body: { text, source: source || "auto", target } });
  if (!r.ok) throw new Error(r.status === 503 ? "server chưa có API key Claude" : r.error);
  return r.data;
}

async function doTranslate({ engine, text, source, target = "vi" }) {
  try {
    const data = engine === "google" ? await googleTranslate(text, source, target) : await serverTranslate(text, source, target);
    return { ok: true, data };
  } catch (e) {
    return { ok: false, error: e.message || String(e) };
  }
}

// menu chuột phải: dùng được cả ở trang PDF / trang extension không chèn script được
function setupMenu() {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: "cnweb-translate", title: "Dịch “%s” sang tiếng Việt", contexts: ["selection"] });
  });
}
chrome.runtime.onInstalled.addListener(setupMenu);
chrome.runtime.onStartup.addListener(setupMenu);
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "cnweb-translate" || !info.selectionText) return;
  const text = info.selectionText;
  try {
    if (!tab || tab.id < 0) throw new Error("no tab");
    const r = await chrome.tabs.sendMessage(tab.id, { type: "translateSelection", text }, { frameId: info.frameId || 0 });
    if (!r || !r.ok) throw new Error("no content script");
  } catch {
    chrome.windows.create({ url: chrome.runtime.getURL("translate/translate.html?text=" + encodeURIComponent(text)),
                            type: "popup", width: 460, height: 560 });
  }
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === "kanji") {
    kanjiLookup(msg.chars || []).then((data) => sendResponse({ ok: true, data }), (e) => sendResponse({ ok: false, error: e.message }));
    return true;
  }
  if (msg && msg.type === "translate") {
    doTranslate(msg).then(sendResponse);
    return true;
  }
  if (msg && msg.type === "openTranslator") {
    chrome.windows.create({ url: chrome.runtime.getURL("translate/translate.html?text=" + encodeURIComponent(msg.text || "")),
                            type: "popup", width: 460, height: 560 });
    sendResponse({ ok: true });
    return false;
  }
  if (msg && msg.type === "api") {
    callApi(msg).then(sendResponse);
    return true; // trả lời bất đồng bộ
  }
  if (msg && msg.type === "server") {
    serverUrl().then((s) => sendResponse({ server: s }));
    return true;
  }
  return false;
});
