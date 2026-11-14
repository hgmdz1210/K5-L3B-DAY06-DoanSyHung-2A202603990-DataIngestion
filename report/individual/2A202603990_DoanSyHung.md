# Báo cáo cá nhân — Day 6

**Học viên:** Đoàn Sỹ Hưng · 2A202603990 · L3B

## Dữ liệu và pipeline
- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:** tiểu thuyết *Pride and Prejudice* (Jane Austen), Project Gutenberg eBook #1342, bản HTML minh họa (`data/pg1342-images.html`, 852.589 byte, SHA256 `387ab4b7…`; bản cập nhật 29/09/2026; truy cập 14/11/2026). Header Gutenberg cho phép dùng gần như không hạn chế tại Mỹ và hầu hết các nước; khi phân phối lại phải giữ Project Gutenberg License. **475 trang nội dung**: các trang in đánh số Ả Rập 1–476 có văn bản của chương I–LXI; trang 10 chỉ có tranh nên không tính. Loại bỏ: header/footer Gutenberg, trang bìa, lời tựa và danh mục tranh (15 trang số La Mã), chú thích tranh, ảnh và dòng nhà in. Trang chứa hai chương được tách thành 2 đơn vị (tổng 476 đơn vị) nhưng chỉ tính 1 trang. Tổng 682.967 ký tự sau chuẩn hóa. Chi tiết từng trang trong [data/manifest.json](../../data/manifest.json).
- **Chuẩn hóa, lỗi và giới hạn:** đọc HTML bằng BeautifulSoup; chuẩn hóa Unicode NFC, gộp khoảng trắng, giữ ngắt đoạn; tách văn bản theo mốc trang `{n}` (thường nằm giữa câu) và tiêu đề `Chapter N` (kể cả lỗi nguồn `CHAPTERXXVII.`). Chữ cái đầu mỗi chương là ảnh (60/61 chương), chữ chỉ có trong `alt`; parser khôi phục chữ đó và viết thường phần small caps (`M` + `R. BENNET was` → `Mr. Bennet was`). Ảnh chương 36 có `alt` trống: đã mở `images/i_282_b.png`, xác nhận chữ "IF" và ghi cứng trong code. 80 dấu đóng ngoặc kép bị mốc trang tách ra được gắn lại vào câu trước. 16 trang dưới 300 ký tự (cuối chương). **Lỗi phát hiện khi review (sau khi đã chạy test):** bản đầu bỏ mất chữ cái đầu chương (`R. BENNET`, `Ithin`). Đã sửa, chỉ embed lại chunk bị ảnh hưởng, chạy lại dev và test; Hit@1/Hit@3 không đổi (`starter/results/metrics_*_before_parser_fix.md`). **Giới hạn:** chunk không vượt trang nên câu nằm vắt hai trang bị tách; tiêu đề chương không nằm trong chunk; số trang là của bản in 1894, khác các ấn bản khác.
- **Embedding model/provider/version/số chiều, vector store/version, metric, lệnh chạy và chi phí:** OpenAI `text-embedding-3-small`, 1536 chiều, SDK `openai` 2.54.0. Query và document dùng cùng model, không thêm prefix, không có fallback mock (thiếu key hoặc lỗi API thì dừng và báo lỗi). PostgreSQL 16.16 + pgvector 0.8.7 (Docker `pgvector/pgvector:0.8.7-pg16`), một bảng `chunks`, khoảng cách cosine `<=>`, **tìm chính xác** (quét tuần tự, không dùng index ANN). Python 3.15.2, psycopg 3.3.8, beautifulsoup4 4.15.0. Lệnh chạy (từ `starter/`): `python scripts/validate_benchmark.py`, `python -m src.run --split dev`, `python -m src.run --split test --skip-ingest`. Chi phí: nạp lần đầu 315.560 token ≈ **$0,0063**; nạp lại phần thay đổi sau khi sửa parser 16.216 token ≈ $0,0003; embed câu hỏi không đáng kể; **tổng < $0,01**. Đây là ước tính theo giá niêm yết $0,02/1M token, cần đối chiếu bảng giá OpenAI.
- **Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn:** mỗi chunk có `document_id` (`pride-and-prejudice-pg1342`), `source` (tên file), `page` (số trang in, kiểu int, lấy từ mốc `{n}`), `char_start`/`char_end` (vị trí trong trang) và `language`. Trường lọc là **`chapter`** (int 1–61), chuyển từ số La Mã trong tiêu đề chương. Lý do chọn: giá trị có sẵn trong nguồn và kiểm chứng được, 61 giá trị phân biệt, và người đọc thường hỏi theo chương. Một số cảnh gần giống nhau xuất hiện ở các chương khác nhau (hai lần Darcy cầu hôn, hai phiên bản chuyện Wickham). Không tạo trường `volume` vì bản HTML này không có đánh dấu tập.

## Cấu hình và benchmark
- **A / B / C (tham số cụ thể, khác biệt duy nhất B–C):**
  - **A:** cửa sổ ký tự cố định 500, overlap 50, không vượt trang; index riêng; không lọc. 1.667 chunk, trung bình 445 ký tự.
  - **B:** gộp các đoạn liên tiếp tối đa 1.200 ký tự (đoạn dài hơn thì cắt ở cuối câu), không vượt trang; index riêng; không lọc. 879 chunk, trung bình 776, trung vị 796 ký tự.
  - **C:** cùng chunk và cùng index với B, thêm `WHERE chapter = N` **chỉ cho câu có filter**; câu không có filter chạy y như B.

  A–B chỉ đổi cách chunk; **B–C chỉ đổi metadata filter**. Cùng corpus, model, store, metric cosine và top-3 cho cả ba.
- **≥20 câu: phân chia ≥15 dev / ≥5 test, câu metadata filter và cách kiểm chứng evidence:**
  - **Bộ câu hỏi:** 24 câu trong [benchmark/questions.json](../../benchmark/questions.json), đánh số theo thứ tự truyện. Quy tắc chia chốt trước khi chạy: mỗi câu thứ 4 là test (q04, q08, q12, q16, q20, q24), còn lại dev, được **18 dev / 6 test**. Loại câu: 9 trực tiếp, 12 diễn đạt lại, 3 có điều kiện.
  - **Câu có filter (5):** q13 (ch34), q15 (ch35), q22 (ch58) ở dev; q08 (ch16), q20 (ch56) ở test. Câu hỏi tự nêu "In chapter N", nên filter là **input người dùng cung cấp trước khi truy xuất**, không lấy từ đáp án hay nguồn gold.
  - **Kiểm chứng evidence:** script `scripts/validate_benchmark.py` kiểm tra mỗi `evidence_quote` xuất hiện nguyên văn trên trang gold sau chuẩn hóa: 24/24 đạt. q04 và q20 có evidence thay thế (p79, p439), lấy cái nào cũng được chấp nhận.
  - **Định nghĩa hit:** chunk đúng `document_id` và `page`, và chứa **trọn** evidence.
- **Tiêu chí chọn chiến lược đã chốt trước khi xem test:** trên dev, so lần lượt (1) Evidence Hit@3 cao nhất, (2) Hit@1, (3) ít chunk hơn. C chỉ được chọn thay B nếu không kém B trên dev. Kết quả dev: B = C (12/18; 8/18), nên **chọn C**. Test chạy sau khi đã chốt.

## Kết quả
| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 6/18 | 7/18 | 1667 | nạp 20,9 s; truy vấn ~42 ms/câu | $0,0033 (164.892 token) |
| A | test | 1/6 | 2/6 | 1667 | nạp 20,9 s; truy vấn ~32 ms/câu | $0,0033 (164.892 token) |
| B | dev | 8/18 | 12/18 | 879 | nạp 8,6 s; truy vấn ~30 ms/câu | $0,0030 (150.668 token) |
| B | test | 3/6 | 5/6 | 879 | nạp 8,6 s; truy vấn ~31 ms/câu | $0,0030 (150.668 token) |
| C | dev | 8/18 | 12/18 | 879 (dùng chung B) | nạp 0 s (dùng index B); truy vấn ~29 ms/câu | $0 thêm |
| C | test | 4/6 | 5/6 | 879 (dùng chung B) | nạp 0 s (dùng index B); truy vấn ~32 ms/câu | $0 thêm |

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 1,10 (10) | 15/15 | 0/5 (dev 0/3, test 0/2; không áp filter) | 2 / 2 / 1 — 0,80 |
| B | 1,50 (10) | 15/15 | 0/5 (dev 0/3, test 0/2; không áp filter) | 1 / 1 / 3 — 1,40 |
| C | 1,50 (10, cùng chunk B) | 15/15 | 5/5 (dev 3/3, test 2/2) | 1 / 1 / 3 — 1,40 |

Nạp lại cùng phiên bản không nhân đôi: lần 2 có 0 chunk embed, số dòng giữ nguyên 1667→1667 và 879→879. Khi text thay đổi (sau khi sửa parser): A embed lại 105 chunk và xóa 60 chunk cũ, B embed lại 61 và xóa 61; số dòng vẫn giữ nguyên ([ingest_runs.jsonl](../../starter/results/ingest_runs.jsonl)).

**Đường dẫn trace, nhãn thủ công và cách chọn mẫu:**
- **Trace top-3 đầy đủ** (text, score, metadata, hit theo từng hạng): `starter/results/traces_dev.jsonl`, `traces_test.jsonl`. Chỉ số: `metrics_*.md/json`. Cấu hình và giả thuyết: [artifacts/experiment_log.csv](../../artifacts/experiment_log.csv).
- **Nhãn:** `starter/results/manual_labels/`, phương pháp ghi trong [README.md](../../starter/results/manual_labels/README.md).
  - **Coherence:** 10 vị trí chọn trước khi có kết quả (10 trang trải đều trong sách, vị trí = giữa trang).
  - **Metadata:** 5 câu test đầu × top-3 × 3 chiến lược = 45 bản ghi, kiểm tự động bằng `scripts/verify_metadata.py`. Script đọc lại HTML gốc bằng regex, độc lập với parser; đã thử cài 2 lỗi giả và script bắt được cả 2.
  - **Grounding:** 5 câu test đầu (q04, q08, q12, q16, q20).
  - Nhãn coherence và grounding do Claude Opus 5.5 đề xuất; học viên đọc lại từng dòng và sửa 7 nhãn (tất cả từ 2 xuống 1, theo quy ước chặt hơn); các dòng đã sửa có `reason` bắt đầu bằng "Học viên hạ 2→1".

## Phân tích và kết luận
- **So sánh A–B và B–C; 2 ví dụ sai có ID câu và nguồn:**
  - **A–B (chỉ đổi chunking):** B tốt hơn ở mọi chỉ số. Evidence Hit@3: dev 12/18 so với 7/18, test 5/6 so với 2/6. Coherence 1,50 so với 1,10; grounding 1,40 so với 0,80. B còn ít hơn 47% số chunk, nạp nhanh hơn (8,6 s so với 20,9 s) và tốn ít token hơn 9% (A tốn thêm do overlap). Cửa sổ 500 ký tự cắt ngang evidence: ở dev q06, q09, q17, A lấy đúng trang nhưng chunk không chứa trọn câu bằng chứng. 9/10 chunk A trong mẫu coherence bị cắt giữa từ hoặc giữa câu.
  - **B–C (chỉ đổi filter):** Hit@3 bằng nhau (12/18, 5/6). Hit@1 test 4/6 so với 3/6, chênh đúng một câu là q08. Filter tuân thủ 5/5 so với 0/5: không có filter, top-3 của B **chưa lần nào** nằm trọn trong chương được hỏi. Filter không làm xấu câu nào.
  - **Ví dụ q08** (test, gold p101 ch16): B xếp evidence ở hạng 3, sau hai đoạn gây nhầm là p325 ch44 và p250 ch35 (phiên bản của Darcy, mâu thuẫn với lời Wickham). C lọc chương 16 và đưa evidence lên hạng 1.
  - **Lỗi 1 — q12** (test, gold p232 ch33, lời Colonel Fitzwilliam "saved a friend from… a most imprudent marriage"): sai ở cả A, B, C. Top-3 của B là p125 ch18, p214 ch30, p180 ch25, đều có tên Darcy hoặc Fitzwilliam nhưng không có nội dung này. Câu không có filter nên C không giúp được. Embedding ưu tiên các đoạn nhắc tên nhân vật hơn đoạn có cùng sự kiện.
  - **Lỗi 2 — q22** (dev, filter ch58, gold p450): C lọc đúng chương và top-1 đúng trang 450, nhưng đó là chunk 930–1696; evidence nằm trọn trong chunk 0–928 cùng trang, bị xếp ngoài top-3. Filter thu hẹp được phạm vi nhưng không sửa được thứ hạng bên trong chương.
  - **Lỗi chunking:** q24 ở A (test, p476) lấy cửa sổ chỉ chứa một phần evidence; câu đầy đủ chỉ nằm trong cửa sổ cuối dài 176 ký tự.
- **Chiến lược chọn, đánh đổi, điều kiện áp dụng:** chọn **C** = chunk theo đoạn + filter chương khi có. Lý do: theo tiêu chí đã chốt, C không kém B trên dev, và giữ kết quả trong đúng phạm vi người hỏi. Các đánh đổi:
  - filter chỉ dùng được khi người dùng biết số chương; nếu nhập sai chương, kết quả mất hoàn toàn;
  - khi câu hỏi không có phạm vi, C giống hệt B;
  - chunk lớn hơn (tối đa 1.200 ký tự) đưa nhiều ngữ cảnh vào top-3 hơn, nhưng mỗi đoạn kém tập trung hơn.

  Điều kiện áp dụng: tài liệu có cấu trúc chương rõ ràng và câu hỏi có nêu phạm vi. Câu không có phạm vi thì dùng B.
- **Hạn chế của dữ liệu, nhãn, test nhỏ, đo thời gian/chi phí:**
  - **Dữ liệu:** chỉ một tiểu thuyết, nên dev và test cùng nhân vật, từ vựng và văn phong; không suy rộng kết quả ra ngoài corpus này.
  - **Test nhỏ:** test chỉ 6 câu, một câu thay đổi tương đương 17 điểm phần trăm. Chênh lệch B–C (một câu) chưa đủ để kết luận.
  - **Test đã chạy hai lần:** lần 2 sau khi sửa lỗi parser; không đổi câu hỏi hay tham số, kết quả giống hệt. Dù vậy test không còn hoàn toàn là hold-out độc lập.
  - **Nhãn:** coherence và grounding do LLM đề xuất và một người xem lại; không có người chấm thứ hai nên có thể thiên lệch. Grounding chỉ đo độ đủ của bằng chứng truy xuất, không phải độ đúng câu trả lời LLM.
  - **Thời gian và chi phí:** đo một lần trên máy cá nhân, phụ thuộc mạng tới API. Chi phí là ước tính theo giá niêm yết.
  - **Môi trường:** Python 3.15.2 nằm ngoài khoảng 3.11–3.14 starter khuyến nghị (vẫn chạy được).
  - **Công cụ AI:** Claude Code (Claude) hỗ trợ viết code, soạn nháp 24 câu hỏi từ văn bản nguồn, đề xuất nhãn và soạn nháp báo cáo. Cách kiểm tra: evidence xác minh bằng script; metadata đối chiếu với HTML gốc; học viên review từng câu hỏi trước khi chạy và thấy ổn; học viên đọc lại nhãn và báo cáo.
- **Nếu làm lại hoặc mở rộng, cải tiến gì?**
  1. Cho chunk vượt ranh giới trang và lưu `page_start`/`page_end`, để không cắt câu (nguyên nhân chính làm B mất điểm coherence).
  2. Thử hybrid dense + BM25 (chọn tham số trên dev) cho các câu trùng từ khóa nguyên văn như q12, q21.
  3. Thêm tiêu đề chương vào text của chunk.
  4. Mở rộng test lên 15–20 câu và có người chấm thứ hai để đo độ đồng thuận.
  5. Thử thêm kích thước chunk 800 và 1.600 ký tự.
