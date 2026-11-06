// Lớp trừu tượng trình phát: YouTube IFrame API hoặc thẻ <video> HTML5 – cùng một giao diện.

class BasePlayer {
  constructor() { this.listeners = {}; this.ready = false; this.error = null; }
  on(ev, fn) { (this.listeners[ev] ||= []).push(fn); }
  emit(ev, ...a) { (this.listeners[ev] || []).forEach((f) => f(...a)); }
}

export class HTML5Player extends BasePlayer {
  constructor(el, src) {
    super();
    const v = document.createElement("video");
    v.src = src;
    v.controls = true;
    v.playsInline = true;
    v.preload = "metadata";
    el.replaceWith(v);
    v.id = "player";
    this.v = v;
    v.addEventListener("loadedmetadata", () => { this.ready = true; this.emit("ready"); });
    v.addEventListener("play", () => this.emit("state", "playing"));
    v.addEventListener("pause", () => this.emit("state", "paused"));
    v.addEventListener("ended", () => this.emit("state", "ended"));
    v.addEventListener("error", () => { this.error = "Không phát được file video"; this.emit("error", this.error); });
  }
  getTime() { return this.v.currentTime; }
  getDuration() { return this.v.duration; }
  seek(t) { this.v.currentTime = Math.max(0, t); }
  play() { return this.v.play().catch(() => {}); }
  pause() { this.v.pause(); }
  isPaused() { return this.v.paused; }
  setRate(r) { this.v.playbackRate = r; }
}

let ytApiPromise;
function loadYTApi() {
  if (window.YT?.Player) return Promise.resolve();
  ytApiPromise ||= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://www.youtube.com/iframe_api";
    s.onerror = () => reject(new Error("Không tải được YouTube IFrame API"));
    window.onYouTubeIframeAPIReady = resolve;
    document.head.appendChild(s);
  });
  return ytApiPromise;
}

const YT_ERRORS = {
  2: "Mã video không hợp lệ", 5: "Lỗi trình phát HTML5", 100: "Video đã bị xoá hoặc để riêng tư",
  101: "Chủ kênh không cho phép nhúng video", 150: "Chủ kênh không cho phép nhúng video",
};

export class YouTubePlayer extends BasePlayer {
  constructor(el, videoId) {
    super();
    this._paused = true;
    loadYTApi().then(() => {
      this.p = new YT.Player(el, {
        videoId,
        playerVars: { playsinline: 1, rel: 0, modestbranding: 1, cc_load_policy: 0, iv_load_policy: 3 },
        events: {
          onReady: () => { this.ready = true; this.emit("ready"); },
          onStateChange: (e) => {
            const s = { 1: "playing", 2: "paused", 0: "ended", 3: "buffering" }[e.data];
            if (s === "playing") this._paused = false;
            if (s === "paused" || s === "ended") this._paused = true;
            if (s) this.emit("state", s);
          },
          onError: (e) => { this.error = YT_ERRORS[e.data] || `Lỗi YouTube ${e.data}`; this.emit("error", this.error); },
        },
      });
    }).catch((e) => { this.error = e.message; this.emit("error", e.message); });
  }
  getTime() { return this.ready ? this.p.getCurrentTime() : 0; }
  getDuration() { return this.ready ? this.p.getDuration() : NaN; }
  seek(t) { if (this.ready) this.p.seekTo(Math.max(0, t), true); }
  play() { if (this.ready) this.p.playVideo(); }
  pause() { if (this.ready) this.p.pauseVideo(); }
  isPaused() { return this._paused; }
  setRate(r) { if (this.ready) this.p.setPlaybackRate(r); }
}

export function createPlayer(el, cfg) {
  return cfg.type === "youtube" ? new YouTubePlayer(el, cfg.youtubeId) : new HTML5Player(el, cfg.src);
}
