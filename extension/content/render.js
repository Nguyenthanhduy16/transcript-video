// Hàm vẽ dùng chung cho content script (script thường, gắn vào window.CNWEB).
(() => {
  if (window.CNWEB) return;
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtTime = (sec) => {
    if (sec == null || isNaN(sec)) return "--:--";
    const m = Math.floor(sec / 60), s = Math.floor(sec % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
  };
  const rubyHTML = (tok) => (tok.furigana || [[tok.surface, null]]).map(([b, rt]) =>
    rt ? `<ruby>${esc(b)}<rt>${esc(rt)}</rt></ruby>` : esc(b)).join("");

  function speakerTag(name, speakerMap, latin) {
    const sp = speakerMap[name];
    const label = latin ? `(${esc(sp?.display || name)}) ` : `（${esc(sp?.display || name)}）`;
    return `<span class="spk" style="color:${esc(sp?.color || "#9aa0b4")}">${label}</span>`;
  }

  /** Câu gốc → các span .w (tra từ được) có furigana. idx = vị trí cue để popup tìm lại token. */
  function cueHTML(cue, idx, speakerMap, latin = false) {
    if (cue.type !== "speech" || !cue.tokens?.length) return `<span class="nonspeech">${esc(cue.text)}</span>`;
    const prefix = cue.speaker && !cue.multiSpeaker ? speakerTag(cue.speaker, speakerMap, latin) : "";
    return prefix + cue.tokens.map((t, i) => {
      if (t.pos === "speaker") return speakerTag(t.lemma, speakerMap, latin);
      if (t.pos === "space") return " ";
      return `<span class="w${t.isWord || t.reading ? " word" : ""}" data-c="${idx}" data-i="${i}">${rubyHTML(t)}</span>`;
    }).join("");
  }

  const CSS = `
  :host { all: initial; }
  * { box-sizing: border-box; }
  .root { --bg:#ffffff; --bg2:#f2f2f6; --fg:#1d1d24; --muted:#7c7c8a; --border:#e3e3ea; --accent:#e53945; --active:#2b2224;
          font-family: "Noto Sans JP", "Hiragino Sans", "Yu Gothic", system-ui, sans-serif; color: var(--fg); font-size: 14px; }
  @media (prefers-color-scheme: dark) { .root { --bg:#1b1b21; --bg2:#26262e; --fg:#ececf1; --muted:#9a9aa8; --border:#33333d; --active:#3a2a2d; } }
  .hidden { display: none !important; }
  button { font: inherit; color: inherit; cursor: pointer; }
  /* phụ đề trên video */
  .sub { position: fixed; pointer-events: none; display: flex; justify-content: center; z-index: 2; }
  .sub-box { pointer-events: auto; max-width: 92%; text-align: center; padding: 6px 16px 8px; border-radius: 10px;
             background: rgba(0,0,0,.62); color: #fff; line-height: 1.25; }
  .sub-box .ja { font-size: calc(26px * var(--scale,1)); font-weight: 700; line-height: 2; text-shadow: 0 1px 3px #000; }
  .sub-box .vi { font-size: calc(17px * var(--scale,1)); color: #f1f1f1; font-family: system-ui, sans-serif; margin-top: 2px; }
  .sub-box .romaji { font-size: calc(13px * var(--scale,1)); color: #ddd; font-family: system-ui, sans-serif; }
  .sub-box .hint { font-size: 12px; color: #ffb4b9; margin-top: 4px; font-family: system-ui, sans-serif; }
  .sub-box .nonspeech { color: #ccc; }
  .latin .ja { font-family: system-ui, "Segoe UI", Roboto, sans-serif; line-height: 1.35; }
  .sub-box.latin .ja { font-size: calc(24px * var(--scale,1)); font-weight: 600; }
  .body.latin .cue .ja { line-height: 1.5; padding-top: 4px; }
  ruby rt { font-size: .5em; opacity: .9; font-weight: 500; }
  .nofuri rt { visibility: hidden; }
  .w { border-radius: 4px; }
  .w.word { cursor: pointer; }
  .w.word:hover, .w.word.hl { background: rgba(229,57,69,.35); }
  .spk { font-size: .62em; font-weight: 700; margin-right: 4px; vertical-align: middle; }
  /* nút nổi */
  .fab { position: fixed; z-index: 3; pointer-events: auto; width: 34px; height: 34px; border-radius: 10px; border: 0;
         background: var(--accent); color: #fff; font-weight: 800; font-size: 16px; box-shadow: 0 3px 10px rgba(0,0,0,.35); }
  .fab.off { background: rgba(0,0,0,.55); }
  /* bảng transcript */
  .panel { position: fixed; z-index: 4; pointer-events: auto; width: 370px; height: min(72vh, 680px); right: 16px; top: 72px;
           background: var(--bg); border: 1px solid var(--border); border-radius: 18px; display: flex; flex-direction: column;
           box-shadow: 0 10px 40px rgba(0,0,0,.25); overflow: hidden; }
  .head { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid var(--border); cursor: move; user-select: none; }
  .head .title { flex: 1; min-width: 0; font-weight: 700; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .head .sub2 { display: block; font-weight: 500; color: var(--muted); font-size: 11px; }
  .iconbtn { border: 0; background: transparent; width: 28px; height: 28px; border-radius: 8px; color: var(--muted); font-size: 16px; }
  .iconbtn:hover { background: var(--bg2); color: var(--fg); }
  .dot { width: 9px; height: 9px; border-radius: 50%; background: #9a9aa8; flex: none; }
  .tabs { display: flex; border-bottom: 1px solid var(--border); }
  .tab { flex: 1; border: 0; background: transparent; padding: 9px 4px 8px; color: var(--muted); font-weight: 600; border-bottom: 2px solid transparent; }
  .tab.on { color: var(--accent); border-color: var(--accent); }
  .toggles { display: flex; gap: 6px; padding: 8px 10px; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
  .chip { border: 1px solid var(--border); background: var(--bg); border-radius: 999px; padding: 2px 10px; font-size: 12px; font-weight: 600; color: var(--muted); }
  .chip.on { background: var(--accent); border-color: var(--accent); color: #fff; }
  .body { flex: 1; overflow-y: auto; padding: 8px; }
  .cue { display: grid; grid-template-columns: 26px 1fr; gap: 2px 8px; padding: 9px 8px; border-radius: 12px; }
  .cue:hover { background: var(--bg2); }
  .cue.on { background: var(--active); color: #fff; outline: 1.5px solid var(--accent); }
  .cue.on .tr, .cue.on .romaji { color: #d9cdd0; }
  .play { width: 24px; height: 24px; border-radius: 50%; border: 0; color: #fff; font-size: 9px; margin-top: 6px; }
  .cue.on .play { background: var(--accent) !important; }
  .cue .ja { font-size: 15px; line-height: 2; word-break: break-word; }
  .cue .tr { color: var(--muted); font-size: 12.5px; font-family: system-ui, sans-serif; }
  .cue .romaji { color: var(--muted); font-size: 11.5px; font-family: system-ui, sans-serif; }
  .cue .nonspeech { color: var(--muted); }
  .empty { padding: 26px 14px; text-align: center; color: var(--muted); line-height: 1.6; }
  .empty b { color: var(--fg); }
  .btn { border: 1px solid var(--border); background: var(--bg); border-radius: 10px; padding: 8px 12px; font-weight: 700; margin: 4px 0; width: 100%; }
  .btn.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
  .btn:disabled { opacity: .5; cursor: default; }
  .err { color: var(--accent); font-size: 12.5px; margin-top: 8px; }
  .muted { color: var(--muted); }
  .bar { height: 6px; border-radius: 6px; background: var(--bg2); overflow: hidden; margin: 10px 0 6px; }
  .bar > div { height: 100%; background: var(--accent); transition: width .4s; }
  .now { background: var(--bg2); border-radius: 12px; padding: 10px; margin-bottom: 10px; }
  .now .meta { font-size: 11px; color: var(--muted); font-weight: 700; }
  .now .ja { font-size: 16px; line-height: 2; }
  .sec { font-size: 12px; font-weight: 800; color: var(--muted); margin: 12px 4px 6px; text-transform: uppercase; letter-spacing: .04em; }
  .item { border: 1px solid var(--border); border-radius: 10px; padding: 8px 10px; margin-bottom: 6px; }
  .item .big { font-size: 17px; font-weight: 700; }
  .item .rd { color: var(--accent); margin-left: 6px; }
  .jlpt { font-size: 10px; font-weight: 800; color: #fff; background: #6c8ebf; border-radius: 5px; padding: 1px 5px; margin-left: 6px; }
  .src { font-size: 10.5px; color: var(--muted); margin: 8px 4px; }
  select, input[type=number] { font: inherit; color: var(--fg); background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 4px 6px; }
  /* popup tra từ */
  .pop { position: fixed; z-index: 6; pointer-events: auto; width: 260px; background: var(--bg); color: var(--fg); border: 1px solid var(--border);
         border-radius: 12px; padding: 10px 12px; box-shadow: 0 8px 30px rgba(0,0,0,.3); }
  .pop .s { font-size: 22px; font-weight: 800; }
  .pop .r { color: var(--accent); font-weight: 600; }
  .pop .m { margin: 6px 0 8px; font-family: system-ui, sans-serif; }
  .pop .row { display: flex; gap: 6px; align-items: center; font-size: 11.5px; color: var(--muted); }
  .pop .row .btn { width: auto; margin: 0 0 0 auto; padding: 4px 10px; font-size: 12px; }
  .toast { position: fixed; left: 50%; bottom: 40px; transform: translateX(-50%); z-index: 7; background: #2b2224; color: #fff;
           padding: 8px 14px; border-radius: 10px; font-size: 13px; pointer-events: none; }
  `;
  window.CNWEB = { esc, fmtTime, rubyHTML, cueHTML, CSS };
})();
