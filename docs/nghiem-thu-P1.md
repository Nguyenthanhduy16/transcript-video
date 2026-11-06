# Biên bản nghiệm thu – Người 1: Tool transcript video (P1-1 → P1-5)

Ngày đo: 06/11/2026 · Máy đo: CPU Intel Xeon 2,1 GHz, **4 vCPU, không GPU**, 15 GB RAM · Commit: xem `git log`.
Số liệu gốc: `docs/bench-results/*.json`. Cách chạy lại: mục cuối.

## Tóm tắt

| Mã | Việc | Kết luận | Ghi chú chính |
|---|---|---|---|
| P1-1 | Thử nghiệm STT, chốt JSON | **Đạt phần kỹ thuật**, chờ Người 3 duyệt JSON | PoC 3 thể loại × 2 engine, có báo cáo so sánh. JSON Schema ở `docs/transcript.schema.json` |
| P1-2 | Transcript có mốc thời gian | **Đạt một phần** | Tốc độ đạt (52 phút → 5,7 phút). Lệch ≤300 ms và CER đạt với tin tức và show; **anime chưa đạt** |
| P1-3 | Dịch nháp, người nói, furigana | **Furigana đạt, người nói đạt; phần dịch chưa đo** | Dịch cần API key Claude và phiếu chấm của Người 4 (công cụ chấm đã có) |
| P1-4 | Worker, nguồn web, xử lý lỗi | **Đạt** | 20/20 job đúng kỳ vọng, worker không crash, job tự phục hồi khi worker bị kill |
| P1-5 | Tối ưu chi phí, sửa lỗi | **Chưa đạt với cấu hình mặc định (Opus)**. Có cấu hình tiết kiệm (ước tính) | Chi phí mới là **ước tính**, chưa đo thật do không có API key |

> **Giới hạn quan trọng của lần đo này.** Bộ chuẩn của Người 4 (phụ đề làm tay từ video thật) chưa có.
> Vì vậy mình tự tạo một **bộ benchmark tổng hợp**: 180 câu hội thoại tự viết thuộc 3 thể loại, đọc bằng giọng
> TTS tiếng Nhật (pyopenjtalk). Mỗi người nói dùng một giọng khác nhau (đổi formant và cao độ). Anime được trộn
> nhạc nền SNR 15 dB, show được trộn tiếng ồn đám đông SNR 18 dB. Có đáp án thời gian chính xác.
> Giọng TTS rõ hơn giọng thật nhưng kém tự nhiên hơn. **Mọi con số về ASR và người nói cần đo lại trên bộ chuẩn
> của Người 4** bằng cùng các script (chỉ cần thay file `.wav` và `.gt.json`).

---

## P1-1 · Thử nghiệm STT, chốt định dạng JSON

**Engine đã thử.** Cả hai chạy trên CPU qua sherpa-onnx, model tải từ GitHub release, không cần GPU hay token:

| Engine | Mô tả |
|---|---|
| **ReazonSpeech zipformer** (int8, 160 MB) | Huấn luyện trên 35.000 giờ truyền hình Nhật, có mốc thời gian từng token |
| **Whisper small** (int8, 375 MB) | Đa ngôn ngữ, có dấu câu, không có mốc thời gian token |

Faster-whisper/WhisperX large-v3 (GPU) và các API đám mây **chưa thử được**. Phiên làm việc không có GPU, và mạng
chặn HuggingFace cùng các nhà cung cấp API. Code vẫn hỗ trợ: `ASR_ENGINE=faster-whisper | whisperx`.

**Kết quả trên 3 video mẫu.** Cấu hình chung: khử nhiễu GTCRN cho bước VAD, Silero VAD (ngưỡng 0,5; quãng lặng 0,25 s).

| Video mẫu (thời lượng) | Engine | CER chữ | CER cách đọc | Câu khớp ±300 ms | RTF | Thời gian / 1 giờ video |
|---|---|---|---|---|---|---|
| Tin tức, sạch (4 ph 06 s) | **ReazonSpeech** | **7,2 %** | **1,8 %** | **95,0 %** | 0,10 | ~6 phút |
| | Whisper small | 11,6 % | 6,1 % | 93,3 % | 0,51 | ~31 phút |
| Anime, nhạc nền (2 ph 59 s) | **ReazonSpeech** | 33,0 % | **14,9 %** | **76,7 %** | 0,11 | ~7 phút |
| | Whisper small | 27,9 % | 19,5 % | 75,0 % | 0,52 | ~31 phút |
| Show thực tế, ồn (3 ph 18 s) | **ReazonSpeech** | **10,2 %** | **7,3 %** | **95,0 %** | 0,11 | ~7 phút |
| | Whisper small | 15,8 % | 10,6 % | 95,0 % | 0,49 | ~29 phút |

- **CER chữ** so trực tiếp mặt chữ sau khi bỏ dấu câu. **CER cách đọc** so theo hiragana nên không phạt
  分かる/わかる hay 七/7. ReazonSpeech hay viết bằng hiragana (はやく thay vì 早く), nên CER chữ cao hơn CER đọc.
- **Chi phí ASR / giờ video**, tự chạy trên CPU: ReazonSpeech ≈ 0,11 giờ CPU 4 nhân. Với VM 4 vCPU khoảng 0,15 USD/giờ
  (giá tham khảo, cần kiểm tra lại với nhà cung cấp), chi phí ≈ **0,02 USD/giờ video**. Whisper small ≈ 0,08 USD/giờ video.
- **Chọn ReazonSpeech làm mặc định.** Nhanh gấp 5 lần, CER đọc thấp hơn ở cả 3 thể loại, và có mốc thời gian từng token.
- **Sửa lỗi phát hiện khi thử nghiệm:**
  - ReazonSpeech chỉ trả về **một câu** cho mỗi đoạn audio, nên pipeline nhận dạng từng lượt nói (VAD) riêng.
  - Mẩu ngắn bị nhận sai ("まず" → "二"), nên mỗi mẩu được **đệm 0,4 s im lặng** hai đầu.
  - Khi có tiếng ồn liên tục, VAD coi cả file là tiếng nói (CER show thực tế 80 %), nên **khử nhiễu GTCRN trước VAD**. CER còn 10,2 %.

**Định dạng JSON:** `docs/transcript.schema.json` (JSON Schema 2020-12). Đầu ra thật của pipeline (1.405 câu) đã được
kiểm tra hợp lệ với schema. Gồm `cues[]` (start/end giây, speaker, type speech|music|sfx, text, tokens kèm furigana,
translation, vocab, kanji, grammar), `speakers[]`, `version`, `stats`. Hợp đồng job của hàng đợi ghi trong
`backend/app/queue.py`. ☐ **Chờ Người 3 duyệt.**

**Kết luận P1-1:** PoC chạy trên 3 video mẫu, có báo cáo độ chính xác, tốc độ và chi phí. **Đạt**, trừ mục "JSON được
Người 3 duyệt" và việc chưa so được với GPU/API.

---

## P1-2 · Transcript có mốc thời gian

| Tiêu chí | Kết quả | Đánh giá |
|---|---|---|
| Lệch ≤ 300 ms ở ≥ 90 % câu | Tin tức **95,0 %** · Show **95,0 %** · Anime **76,7 %** · Gộp 3 file 88,9 % · File dài 52 phút (bản sạch, ghép 3 thể loại) 81,2 % | **Đạt với tin tức và show, chưa đạt với anime** |
| CER ≤ 15 % với hội thoại rõ | Tin tức **7,2 %** · Show **10,2 %** · Anime 33,0 % (chữ) / **14,9 %** (đọc) · File dài 19,0 % / **8,1 %** | **Đạt với hội thoại rõ** (tin tức, show). Anime chỉ đạt theo CER cách đọc |
| Video 50 phút xử lý ≤ 15 phút | 51,9 phút audio → **5,7 phút** (ASR 5,0 phút, người nói 0,7 phút, furigana 0,2 s) trên 4 vCPU | **Đạt** |

Chi tiết độ lệch thời gian của ReazonSpeech: trung vị 16–21 ms ở đầu câu và 81–169 ms ở cuối câu; 90 % số câu lệch đầu câu ≤ 117 ms (tin tức, show).

**Đã sửa trong P1-2:**
- Không kéo dài mốc `end` thành 1 s nữa, vì làm lệch cuối câu. Frontend tự giữ phụ đề trên màn hình tối thiểu 1 s.
- Chỉ gộp mẩu < 1 s vào **mẩu kề gần nhất** khi quãng nghỉ ≤ 0,35 s.
- Hỗ trợ link `.m3u8` và link mp4 trực tiếp (tải về trước rồi mới xử lý).

**Còn lỗi với anime.** Câu cảm thán ngắn, tiếng cười, giọng Kansai bị nhận sai hoặc mất ("本当に？やったー！" → "じゃほら").
Đây là giới hạn của model ReazonSpeech với khẩu ngữ, cộng với giọng TTS kém tự nhiên. Hướng xử lý tiếp:
- thử Whisper large-v3 hoặc kotoba-whisper trên GPU;
- ưu tiên phụ đề có sẵn (luồng A) cho anime;
- đo lại trên anime thật của bộ chuẩn.

---

## P1-3 · Dịch nháp, người nói, furigana

| Tiêu chí | Kết quả | Đánh giá |
|---|---|---|
| ≥ 70 % câu dịch được Người 4 chấm "dùng được, sửa nhẹ" | Chưa đo: phiên không có API key Claude, và cần Người 4 chấm | **Chưa nghiệm thu được**. Công cụ chấm đã có (mục cuối) |
| Furigana đúng ≥ 98 % từ có kanji trên mẫu 200 câu | **99,73 %** (729/731 từ, 231 câu) · Tập giữ lại (40 câu viết sau khi chỉnh, 130 từ): **100 %** | **Đạt** (đáp án cần Người 4 xác nhận, xem dưới) |
| Gán đúng người nói ≥ 80 % với video 2–4 người | Không biết trước số người: tin tức **100 %**, show **96,7 %**, anime **88,3 %** · Biết trước số người: **100 / 96,7 / 91,7 %** | **Đạt** |

**Cách đo furigana.** Cách đọc của tool (SudachiPy) được so với OpenJTalk, một bộ phân tích dùng từ điển độc lập.
- Hai bên **đồng ý ở 96,7 %** đơn vị, và các đơn vị này được coi là đúng.
- 24 chỗ khác nhau được phân xử, ghi trong `scripts/bench/furigana_gold.json`. Phần lớn là tool đúng, OpenJTalk sai
  (降り→ふり, 明後日→あさって, 六百円→ろっぴゃくえん).
- **Người phân xử là Claude, chưa phải Người 4**, nên cần Người 4 xem lại file gold.
- Hai lỗi còn lại: 切 trong "親切の切は" (đúng phải đọc せつ), và 十分 trong "残り時間は十分です" (ngữ cảnh là 10 phút, tool đọc じゅうぶん).
- Đã thêm quy tắc đọc cho số đếm và ngày tháng (一日→ついたち, 二十日→はつか, 八つ→やっつ, 三十分→さんじゅっぷん,
  六本→ろっぽん, 四人→よにん…), từ đặc biệt (富士山, 一昨日, 一年中…), biến âm (作り→づくり) và 言う→いう.
  Tập giữ lại được viết **sau** khi chỉnh để kiểm tra không học tủ.

**Cách gán người nói.** Mỗi câu thoại lấy một embedding giọng (3D-Speaker ERes2Net, sherpa-onnx, CPU), không cần token HuggingFace.
- Không biết số người: gom cụm average-linkage với ngưỡng cosine 0,5.
- Biết số người (`num_speakers`): gom cụm Ward.
- Mô hình pyannote cắt đoạn (thử trước đó) gom nhầm nhiều nên không dùng.
- Còn lại: anime khi không biết số người bị tách thành 8 cụm (thực tế 4). Biên tập viên gộp lại bằng cách đổi tên trong trang Sửa.

**Dịch nháp (code đã có, chưa chạy thật):** Claude, structured output, lô 30 câu kèm ngữ cảnh trước/sau, bảng thuật ngữ
series, giữ nhãn người nói. Kanji (On/Kun/Hán Việt) lấy từ KANJIDIC2 thay vì LLM.

---

## P1-4 · Worker, nguồn web, xử lý lỗi

| Tiêu chí | Kết quả | Đánh giá |
|---|---|---|
| 20 job liên tiếp không crash | **20/20 job kết thúc đúng kỳ vọng**, worker vẫn chạy, 52,6 s (`docs/bench-results/worker_stress.json`) | **Đạt** |
| Job lỗi trả trạng thái và lý do rõ | Mỗi lỗi có **mã** và **lý do tiếng Việt** (bảng dưới) | **Đạt** |
| README cài đặt, cấu hình | `README.md` (mục Worker, Biến môi trường, Mã lỗi) | **Đạt** |

20 job gồm:
- **11 job thành công:** 3 upload, 3 link mp4 (một job có `num_speakers`), 2 link HLS `.m3u8`, video không tiếng kèm `.srt`, 2 job lặp lại.
- **9 job lỗi cố ý:** 404, trang HTML, file hỏng, video không có tiếng, audio im lặng, máy chủ không tồn tại, `ftp://`, dịch lại video không tồn tại.

Thêm một kiểm thử: **`kill -9` worker khi đang xử lý**. BullMQ phát hiện job bị treo, worker mới nhận lại và hoàn thành job (sau khoảng 2 phút).

Lần chạy đầu phát hiện và đã sửa 3 lỗi thật:
- Link mp4 hỏng khi máy chủ không hỗ trợ HTTP Range. Đã sửa: tải file về trước.
- Lỗi "audio im lặng" và "video không tồn tại" bị báo chung là INTERNAL. Đã tách mã riêng.
- `ftp://` bị báo sai thành "không kết nối được". Đã sửa thành báo giao thức không hỗ trợ.

Mã lỗi trả về trong `failedReason` của job BullMQ, hoặc trường `error` của API, dạng `MÃ: lý do`:

| Mã | Ý nghĩa | Thử lại? |
|---|---|---|
| SOURCE_NOT_FOUND | Link 404 / không tìm thấy file | Không |
| SOURCE_FORBIDDEN | 401/403 | Không |
| SOURCE_UNREACHABLE, SOURCE_TIMEOUT | Không kết nối được / hết thời gian chờ | **Có** (2 lần, backoff) |
| UNSUPPORTED_URL | Không phải http(s), hoặc trang không có video | Không |
| NOT_MEDIA | File hỏng / không phải video-audio | Không |
| NO_AUDIO | Không có kênh âm thanh (kèm `.srt` thì vẫn xử lý được) | Không |
| NO_SPEECH | Không nhận được câu thoại nào | Không |
| TOO_LONG, TOO_LARGE | Vượt `MAX_DURATION_MIN` / `MAX_DOWNLOAD_MB` | Không |
| ASR_UNAVAILABLE, LLM_UNAVAILABLE | Thiếu model ASR / API key | Không |
| NOT_FOUND | Dịch lại video chưa có transcript | Không |
| INTERNAL | Lỗi khác (kèm tên exception) | Không |

---

## P1-5 · Tối ưu chi phí và tốc độ

**Tối ưu đã làm:**
- Kanji (On/Kun/Hán Việt/số nét) lấy từ **KANJIDIC2**, 13.108 chữ (380 KB, CC BY-SA, đã ghi nguồn EDRDG), thay vì để LLM sinh.
- Nghĩa tiếng Việt của kanji chỉ hỏi LLM **một lần**, lưu cache dùng cho mọi tập sau.
- Cách đọc từ vựng lấy từ Sudachi.
- JSON gửi đi dạng gọn.
- System prompt được cache.
- Chạy song song 4 lô.
- Có thể tách model dịch và model phân tích (`LLM_PROFILE=economy`).
- Số token và chi phí **thật** được ghi vào `stats.llmUsage` của mỗi tập.

**Ước tính chi phí LLM cho file 52 phút** (1.405 câu, 3.550 từ vựng, 361 kanji khác nhau; `scripts/bench/estimate_cost.py`):
- Đếm token bằng công thức gần đúng (CJK 1 token/ký tự, tiếng Việt 0,5, ASCII 1/3,5), sai số khoảng ±30 %.
- Cộng thêm token suy nghĩ (adaptive thinking): 0–50 % đầu ra với effort `low`, 30–100 % với effort `medium`.
- **Chưa đo thật vì không có API key.**

| Cấu hình | USD / tập 52 phút |
|---|---|
| Opus 5.5, thiết kế ban đầu (kanji do LLM sinh), effort medium | 7,75 – 15,18 |
| **Opus 5.5 đã tối ưu (mặc định hiện tại)**, medium / low | 4,46 – 8,75 / 3,48 – 6,64 |
| Sonnet 5.5 đã tối ưu, low | 1,74 – 3,32 |
| **`LLM_PROFILE=economy`**: dịch bằng Sonnet 5.5, phân tích bằng Haiku 5.5, low | **0,49 – 0,87** |
| Haiku 5.5 cho cả hai, low | **0,09 – 0,17** |

Một tập anime 50 phút thực tế thường có khoảng 600–900 câu, ít hơn 1.405 câu của file đo. Chi phí tỉ lệ với số câu, nên
cấu hình economy ước tính khoảng **0,3–0,6 USD/tập**.

**Kết luận P1-5:**
- Tiêu chí "Chi phí AI ≤ 0,7 USD/tập 50 phút" **không đạt với cấu hình mặc định (Opus)**.
- **Có khả năng đạt** với `LLM_PROFILE=economy` hoặc dùng Haiku, nhưng:
  1. số liệu mới là ước tính, cần chạy thật một tập có API key rồi đọc `stats.llmUsage`;
  2. model rẻ có thể dịch kém hơn, nên phải để Người 4 chấm theo tiêu chí P1-3 trước khi chốt.
- **Việc chọn model là quyết định của nhóm.** Code giữ mặc định Opus.
- Có thể giảm thêm 50 % bằng Message Batches API (job không cần trả ngay). Chưa làm.

**Lỗi đã biết (chưa có lỗi làm hỏng job):**
1. Anime / khẩu ngữ: CER cao, lệch thời gian ở câu cảm thán (xem P1-2).
2. ReazonSpeech không sinh dấu câu và hay viết hiragana. Có thể nhờ LLM thêm dấu câu ở bước dịch.
3. Tách người nói dư cụm khi không biết số người.
4. Tải audio YouTube (yt-dlp) và gọi Claude API **chưa chạy thật trong phiên này**, do mạng chặn YouTube và không có key.

---

## Chạy lại các phép đo

```bash
scripts/download_models.sh --whisper                      # model CPU (ReazonSpeech, Whisper small, VAD, embedding)
python scripts/bench/make_bench.py --long 50              # tạo audio benchmark + đáp án
python scripts/bench/eval_asr.py --engines reazon whisper-onnx --files news anime variety   # P1-1, P1-2, người nói
python scripts/bench/eval_furigana.py && python scripts/bench/eval_furigana.py --heldout     # P1-3 furigana
python scripts/bench/stress_worker.py                     # P1-4 (cần redis-server)
python scripts/bench/estimate_cost.py data/videos/<tập>.json                                   # P1-5 ước tính
python scripts/bench/translation_review.py export data/videos/<tập>.json --sample 100          # P1-3 phiếu chấm cho Người 4
python scripts/bench/translation_review.py score phieu_cham_<tập>.csv
```

Đo trên **bộ chuẩn của Người 4**: đặt `ten.wav` (16 kHz mono) và `ten.gt.json` (định dạng như `docs/bench-results/news.gt.json`:
`lines[] = {start, end, speaker, text}`) vào `data/bench/`, rồi chạy `eval_asr.py --files ten`.
