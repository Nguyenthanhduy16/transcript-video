// Chạy trong "MAIN world" của trang YouTube (từ document_start).
// 1) Đọc danh sách phụ đề của video (captionTracks).
// 2) Bắt nội dung phụ đề do CHÍNH player YouTube tải về: YouTube yêu cầu mã PO token mà chỉ player
//    tạo được, nên extension không tự tải link phụ đề được nữa (trả về rỗng). Ta bọc fetch/XHR để
//    nhận bản sao phản hồi /api/timedtext, và khi cần thì tạm bật phụ đề trong player để nó tự tải.
(() => {
  if (window.__cnwebYtMain) return;
  window.__cnwebYtMain = true;
  const captured = new Map();     // "videoId|lang|kind" → { body, url }

  function keyFromUrl(u) {
    try {
      const x = new URL(u, location.origin);
      return `${x.searchParams.get("v") || ""}|${x.searchParams.get("lang") || ""}|${x.searchParams.get("kind") || ""}`;
    } catch { return null; }
  }
  function remember(url, body) {
    if (!body || !body.trim()) return;
    const k = keyFromUrl(url);
    if (k) captured.set(k, { body, url });
  }
  const isTimedtext = (u) => typeof u === "string" && u.includes("/api/timedtext");

  // --- bọc fetch
  const _fetch = window.fetch;
  window.fetch = function (input, init) {
    const url = typeof input === "string" ? input : (input && input.url) || "";
    const p = _fetch.apply(this, arguments);
    if (isTimedtext(url)) p.then((r) => r.clone().text().then((t) => remember(url, t))).catch(() => {});
    return p;
  };
  // --- bọc XMLHttpRequest
  const _open = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.__cnwebUrl = typeof url === "string" ? url : String(url || "");
    return _open.apply(this, arguments);
  };
  const _send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function () {
    if (isTimedtext(this.__cnwebUrl)) {
      this.addEventListener("load", () => {
        try {
          const t = this.responseType === "" || this.responseType === "text" ? this.responseText
            : (typeof this.response === "string" ? this.response : "");
          remember(this.__cnwebUrl, t);
        } catch {}
      });
    }
    return _send.apply(this, arguments);
  };

  function player() { return document.getElementById("movie_player"); }
  function playerResponse() {
    const p = player();
    try { if (p && typeof p.getPlayerResponse === "function") return p.getPlayerResponse(); } catch {}
    return window.ytInitialPlayerResponse || null;
  }
  function tracksInfo() {
    const resp = playerResponse() || {};
    const vd = resp.videoDetails || {};
    const list = (((resp.captions || {}).playerCaptionsTracklistRenderer || {}).captionTracks || []).map((t) => ({
      baseUrl: t.baseUrl, lang: t.languageCode, kind: t.kind || "manual", vssId: t.vssId,
      name: (t.name && (t.name.simpleText || (t.name.runs || []).map((r) => r.text).join(""))) || t.languageCode,
    }));
    return { videoId: vd.videoId || null, title: vd.title || null, duration: Number(vd.lengthSeconds) || null, tracks: list };
  }

  function findCaptured(videoId, lang, kind) {
    const k = kind === "asr" ? "asr" : "";
    return captured.get(`${videoId}|${lang}|${k}`) || [...captured.entries()].find(([key]) =>
      key.startsWith(`${videoId}|${lang}|`))?.[1] || null;
  }

  /** Dùng lại PO token từ một lần player đã tải phụ đề của video này → tự tải ngôn ngữ cần, không đụng player. */
  async function fetchWithCapturedToken(videoId, lang, kind) {
    const any = [...captured.values()].find((v) => keyFromUrl(v.url)?.startsWith(videoId + "|") && v.url.includes("pot="));
    if (!any) return null;
    try {
      const u = new URL(any.url, location.origin);
      u.searchParams.set("lang", lang);
      if (kind === "asr") u.searchParams.set("kind", "asr"); else u.searchParams.delete("kind");
      u.searchParams.delete("tlang");                 // bỏ dịch tự động
      const t = await (await _fetch(u.toString(), { credentials: "include" })).text();
      return t && t.trim() ? { body: t, url: u.toString() } : null;
    } catch { return null; }
  }

  /** Lấy phụ đề `lang`: (1) đã bắt được, (2) dùng lại token, (3) tạm bật phụ đề trong player rồi trả lại đúng trạng thái cũ. */
  async function captureViaPlayer(lang, kind, timeoutMs = 10000) {
    const p = player();
    const info = tracksInfo();
    const have = findCaptured(info.videoId, lang, kind) || await fetchWithCapturedToken(info.videoId, lang, kind);
    if (have) return have;
    if (!p || typeof p.setOption !== "function") return null;
    let prev = null;
    try { prev = p.getOption && p.getOption("captions", "track"); } catch {}
    const wasOn = !!(prev && prev.languageCode);
    try {
      if (typeof p.loadModule === "function") p.loadModule("captions");
      const track = { languageCode: lang };
      if (kind === "asr") track.kind = "asr";
      p.setOption("captions", "track", track);
    } catch {}
    const t0 = Date.now();
    let got = null;
    while (Date.now() - t0 < timeoutMs) {
      got = findCaptured(info.videoId, lang, kind);
      if (got) break;
      await new Promise((r) => setTimeout(r, 250));
    }
    // trả phụ đề của người dùng về đúng như trước; KHÔNG unloadModule (làm nút CC hết hiện chữ tới khi tải lại trang)
    try { p.setOption("captions", "track", wasOn ? prev : {}); } catch {}
    return got;
  }

  window.addEventListener("message", async (ev) => {
    if (ev.source !== window || !ev.data) return;
    const d = ev.data;
    if (d.__cnweb === "get-tracks") {
      window.postMessage({ __cnweb: "tracks", reqId: d.reqId, ...tracksInfo() }, "*");
    } else if (d.__cnweb === "capture-subs") {
      let res = null;
      try { res = await captureViaPlayer(d.lang, d.kind); } catch {}
      window.postMessage({ __cnweb: "subs", reqId: d.reqId, body: res ? res.body : null, url: res ? res.url : null }, "*");
    }
  });
})();
