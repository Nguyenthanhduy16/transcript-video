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

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
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
