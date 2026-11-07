// Chạy trong "MAIN world" của trang YouTube: đọc danh sách phụ đề của video đang phát
// (biến của trang, content script thường không đọc được) rồi gửi lại qua postMessage.
(() => {
  if (window.__cnwebYtMain) return;
  window.__cnwebYtMain = true;
  function playerResponse() {
    const p = document.getElementById("movie_player");
    try { if (p && typeof p.getPlayerResponse === "function") return p.getPlayerResponse(); } catch {}
    return window.ytInitialPlayerResponse || null;
  }
  window.addEventListener("message", (ev) => {
    if (ev.source !== window || !ev.data || ev.data.__cnweb !== "get-tracks") return;
    const resp = playerResponse() || {};
    const vd = resp.videoDetails || {};
    const list = (((resp.captions || {}).playerCaptionsTracklistRenderer || {}).captionTracks || []).map((t) => ({
      baseUrl: t.baseUrl, lang: t.languageCode, kind: t.kind || "manual",
      name: (t.name && (t.name.simpleText || (t.name.runs || []).map((r) => r.text).join(""))) || t.languageCode,
    }));
    window.postMessage({ __cnweb: "tracks", reqId: ev.data.reqId, videoId: vd.videoId || null,
      title: vd.title || null, duration: Number(vd.lengthSeconds) || null, tracks: list }, "*");
  });
})();
