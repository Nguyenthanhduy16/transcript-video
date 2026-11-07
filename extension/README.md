# Extension Chrome: Transcript học ngoại ngữ

Phụ đề song ngữ **Nhật – Việt** (có furigana) và **Anh – Việt**, tra từ, phân tích câu, ngay trên YouTube và các trang có video.
Extension dùng chung server (backend) của tool transcript: server tạo transcript, extension hiển thị.

## Cài đặt

1. Chạy server (xem `README.md` ở thư mục gốc):
   ```bash
   cd backend && uvicorn app.main:app --port 8000
   ```
2. Mở Chrome (hoặc Edge, Brave), vào `chrome://extensions`, bật **Developer mode** (góc trên bên phải).
3. Bấm **Load unpacked** rồi chọn thư mục `extension/`. Hoặc giải nén file `transcript-extension.zip` rồi chọn thư mục vừa giải nén.
4. Ghim extension lên thanh công cụ (biểu tượng mảnh ghép, rồi ghim "Transcript học ngoại ngữ").

Server không chạy ở `http://localhost:8000` thì mở popup của extension, sửa địa chỉ trong mục **Server** và bấm **Lưu**.
Với server khác localhost, Chrome sẽ hỏi quyền truy cập địa chỉ đó.

## Ngôn ngữ video

| | Tiếng Nhật | Tiếng Anh |
|---|---|---|
| Nhận dạng giọng nói trên server | ReazonSpeech (nhanh, ~0,1 × thời lượng video) | Whisper small (~0,5 × thời lượng video, cần `scripts/download_models.sh --whisper`) |
| Tách từ | SudachiPy, furigana, romaji, kanji (âm Hán Việt) | dạng gốc của từ (went → go), bỏ qua từ chức năng |
| Cấp độ từ vựng (khi có API key) | JLPT N5–N1 | CEFR A1–C2 |

Ô **Ngôn ngữ video** trong bảng mặc định là **Tự nhận**: trên YouTube, extension đọc ngôn ngữ của phụ đề tự động
(chính là ngôn ngữ nói trong video). Trang khác: mặc định tiếng Nhật, có thể đổi sang tiếng Anh trước khi tạo.

## Sử dụng

**YouTube.** Extension tự chạy trên mọi trang video YouTube.
- Video đã có transcript: phụ đề hiện trên video và bảng **Hội thoại / Phân tích** hiện cạnh video.
- Video chưa có: bấm nút **字** ở góc video, chọn một trong hai cách:
  - **Tạo từ phụ đề YouTube**: dùng phụ đề tiếng Nhật có sẵn của video, nhanh và chính xác nhất. Server không cần tải video.
  - **Nhận dạng giọng nói trên server**: dùng khi video không có phụ đề. Server phải tải được audio từ YouTube.
- Tạo một lần, lần sau mở lại video là có ngay. Có thể tiếp tục xem trong lúc server xử lý.

**Trang khác có video** (file mp4, HLS…): mở popup, bấm **Bật trên trang này**.
- Nếu video phát từ link file (`http…mp4/m3u8`), server tải file đó về để nhận dạng.
- Nếu video phát dạng luồng (`blob:`), server thử tải từ link trang (yt-dlp).
- Video có DRM (Netflix…) không lấy được audio.

**Trên phụ đề và bảng:**
- **Rê chuột** (hoặc bấm) vào một từ để xem cách đọc, nghĩa, JLPT, rồi bấm **Lưu vào sổ từ**.
- Bấm **▶** ở một câu để tua tới câu đó.
- Tab **Phân tích**: từ vựng, kanji (âm Hán Việt) và ngữ pháp của câu đang phát.
- Các nút trên bảng: bật/tắt Phụ đề, Nhật, Việt, Furigana, Romaji; **Dừng mỗi câu**; **A− / A+** đổi cỡ chữ.
- Kéo thanh tiêu đề để di chuyển bảng. Nút **字** ẩn/hiện bảng.
- Phím tắt: `[` câu trước · `]` câu sau · `\` nghe lại câu. Không trùng phím của YouTube.

**Popup** (bấm biểu tượng extension):
- trạng thái video ở tab hiện tại;
- cài đặt hiển thị: cỡ chữ, vị trí phụ đề, chỉnh lệch thời gian;
- **Sổ từ** có xuất CSV cho Anki;
- địa chỉ server.

## Cách hoạt động

| Thành phần | Việc |
|---|---|
| `content/yt-main.js` | Chạy trong trang YouTube, đọc danh sách phụ đề của video (`captionTracks`) |
| `content/content.js` + `render.js` | Tìm `<video>`, hỏi server `GET /api/resolve?url=…`, vẽ phụ đề và bảng trong Shadow DOM (không ảnh hưởng CSS trang), đồng bộ theo `video.currentTime` |
| `background.js` | Gọi API server (`/api/resolve`, `/api/videos/{id}`, `/api/jobs`, `/api/jobs/subtitle`, `/api/jobs/{id}`) |
| `popup/` | Cài đặt (`chrome.storage.sync`), sổ từ (`chrome.storage.local`), bật extension trên trang khác (`chrome.scripting`) |

Quyền xin: `storage`, `activeTab`, `scripting`, truy cập `localhost`. Truy cập server khác chỉ khi người dùng lưu địa chỉ đó.
Extension không đọc dữ liệu trang ngoài video và phụ đề, và không gửi gì ngoài địa chỉ video tới server bạn cấu hình.

## Giới hạn

- Chưa thử trên youtube.com thật: môi trường phát triển chặn YouTube. Luồng YouTube được kiểm tra trên trang giả lập
  có cùng cấu trúc player và phụ đề. YouTube có thể chặn tải phụ đề từ extension (yêu cầu token). Khi đó extension báo
  lỗi và gợi ý dùng **Nhận dạng giọng nói trên server**.
- Chưa có bản dịch nếu server chưa đặt `ANTHROPIC_API_KEY`. Phụ đề tiếng Nhật, furigana và kanji vẫn có.
