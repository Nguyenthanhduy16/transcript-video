// Bộ dịch dùng chung (content script + cửa sổ dịch). Gắn vào globalThis.CNWEB_TR.
//   chrome : Translator API có sẵn trong Chrome 138+ (chạy trên máy, miễn phí, không gửi văn bản đi đâu)
//   google : Google Dịch (qua background, online)
//   server : Claude qua server của tool (/api/translate; cần API key trên server) – có giải thích từ
//   auto   : chrome → google → server (dừng ở bộ đầu tiên chạy được)
(() => {
  if (globalThis.CNWEB_TR) return;
  const LANG_NAMES = { en: "Tiếng Anh", ja: "Tiếng Nhật", vi: "Tiếng Việt", zh: "Tiếng Trung", ko: "Tiếng Hàn",
                       fr: "Tiếng Pháp", de: "Tiếng Đức", es: "Tiếng Tây Ban Nha", ru: "Tiếng Nga", th: "Tiếng Thái" };
  const ENGINE_NAMES = { chrome: "Chrome (trên máy)", google: "Google Dịch", server: "Claude (server)", claude: "Claude (server)" };
  const withTimeout = (p, ms, msg = "quá thời gian") => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error(msg)), ms))]);

  function guessLang(text) {
    if (/[぀-ヿ]/.test(text)) return "ja";
    if (/[가-힯]/.test(text)) return "ko";
    if (/[一-鿿]/.test(text)) return "zh";
    if (/[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]/i.test(text)) return "vi";
    if (/[Ѐ-ӿ]/.test(text)) return "ru";
    if (/[฀-๿]/.test(text)) return "th";
    return "en";
  }

  let detector = null;
  async function detect(text) {
    try {
      if (typeof LanguageDetector !== "undefined") {
        if (!detector) {
          const a = await withTimeout(LanguageDetector.availability(), 2000);
          if (a === "available") detector = await withTimeout(LanguageDetector.create(), 3000);
        }
        if (detector) {
          const r = (await withTimeout(detector.detect(text), 2000))[0];
          if (r && r.confidence > 0.5 && r.detectedLanguage !== "und") return r.detectedLanguage.split("-")[0];
        }
      }
    } catch { /* dùng đoán theo chữ */ }
    return guessLang(text);
  }

  const translators = new Map();        // "en>vi" → Translator đã sẵn sàng
  const pending = new Map();            // "en>vi" → Promise đang tải gói ngôn ngữ
  let lastProgress = 0;

  function startCreate(source, target, onProgress) {
    const key = `${source}>${target}`;
    if (!pending.has(key)) {
      lastProgress = Date.now();
      const pr = Translator.create({ sourceLanguage: source, targetLanguage: target,
        monitor(m) { m.addEventListener("downloadprogress", (e) => { lastProgress = Date.now(); onProgress && onProgress(e.loaded); }); } })
        .then((tr) => { translators.set(key, tr); return tr; })
        .finally(() => pending.delete(key));
      pr.catch(() => {});
      pending.set(key, pr);
    }
    return pending.get(key);
  }

  /** wait=false (chế độ tự động): gói ngôn ngữ chưa có thì tải nền và báo lỗi ngay để dùng bộ dịch khác. */
  async function chromeTranslate(text, source, target, onProgress, wait = true) {
    if (typeof Translator === "undefined") throw new Error("Chrome này chưa có bộ dịch tích hợp (cần Chrome 138 trở lên)");
    const key = `${source}>${target}`;
    let tr = translators.get(key);
    if (!tr) {
      if (!pending.has(key)) {
        const a = await withTimeout(Translator.availability({ sourceLanguage: source, targetLanguage: target }), 3000,
          "bộ dịch của Chrome không phản hồi");
        if (a === "unavailable") throw new Error(`Chrome chưa hỗ trợ dịch ${LANG_NAMES[source] || source} → ${LANG_NAMES[target] || target}`);
        if (a === "available") {
          tr = await withTimeout(Translator.create({ sourceLanguage: source, targetLanguage: target }), 5000);
          translators.set(key, tr);
        } else {
          startCreate(source, target, onProgress);
        }
      }
      if (!tr) {
        if (!wait) throw new Error("đang tải gói ngôn ngữ về máy (lần sau sẽ dịch trên máy)");
        // chờ tải; không có tiến triển 20 s thì bỏ
        tr = await new Promise((resolve, reject) => {
          pending.get(key).then(resolve, reject);
          const iv = setInterval(() => {
            if (translators.has(key)) { clearInterval(iv); resolve(translators.get(key)); }
            else if (Date.now() - lastProgress > 20000) { clearInterval(iv); reject(new Error("tải gói ngôn ngữ của Chrome không tiến triển")); }
          }, 1000);
        });
      }
    }
    return { translation: await withTimeout(tr.translate(text), 20000), detectedLang: source, engine: "chrome", kind: "text" };
  }

  function viaBackground(engine, text, source, target) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage({ type: "translate", engine, text, source, target }, (r) => {
        if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
        if (!r || !r.ok) return reject(new Error((r && r.error) || "lỗi không rõ"));
        resolve(r.data);
      });
    });
  }

  /** Dịch `text` sang `target`. engine: auto | chrome | google | server. Trả {translation, detectedLang, engine, kind, …}. */
  async function translate(text, { engine = "auto", target = "vi", onProgress } = {}) {
    const source = await detect(text);
    if (source === target) return { translation: text, detectedLang: source, engine: "none", kind: "same" };
    const order = engine === "auto" ? ["chrome", "google", "server"] : [engine];
    const errors = [];
    for (const e of order) {
      try {
        if (e === "chrome") return await chromeTranslate(text, source, target, onProgress, engine !== "auto");
        return await viaBackground(e, text, source, target);
      } catch (err) {
        errors.push(`${ENGINE_NAMES[e] || e}: ${err.message}`);
      }
    }
    throw new Error(errors.join(" · "));
  }

  globalThis.CNWEB_TR = { translate, detect, guessLang, LANG_NAMES, ENGINE_NAMES };
})();
