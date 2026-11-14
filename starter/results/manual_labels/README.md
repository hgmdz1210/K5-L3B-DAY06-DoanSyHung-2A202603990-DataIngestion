# Nhãn đánh giá: phương pháp và tổng hợp

| Sheet | Ai chấm | Phương pháp |
|---|---|---|
| `coherence_sheet.csv` | Claude Opus 5.5 đề xuất, học viên xem lại | Đọc toàn văn chunk chứa 10 vị trí cố định (chọn trước khi có kết quả: 10 trang trải đều, vị trí = giữa trang). Thang GUIDE 0/1/2. Học viên chọn quy ước chặt: chunk có mảnh câu bị cắt (kể cả ở ranh giới trang) tối đa 1 điểm. |
| `grounding_sheet.csv` | Claude Opus 5.5 đề xuất, học viên xem lại | Đọc top-3 của 5 câu test đầu (q04, q08, q12, q16, q20) so với `expected_answer` và evidence gold. 0 = không có bằng chứng; 1 = có nhưng thiếu điều kiện/nội dung; 2 = đủ trả lời và truy nguồn. Evidence thay thế được chấp nhận, nhưng phải đủ các ý của đáp án mẫu mới được 2. |
| `metadata_audit_sheet.csv` | Tự động: `scripts/verify_metadata.py` | Parse lại HTML gốc bằng regex (độc lập với `src/ingestion.py`), tìm vị trí từng chunk, so `source`/`page`/`chapter`. Đã thử cài 2 lỗi giả và script bắt được cả 2. |

**Quy trình xem lại:** học viên đọc từng dòng (cột `reason`), đồng ý với 28 nhãn và sửa 7 nhãn, tất cả từ 2 xuống 1: coherence B pos02, pos05, pos07, pos09 và grounding q20 ở cả A, B, C. Các dòng đã sửa có `reason` bắt đầu bằng "Học viên hạ 2→1".

**Giới hạn:** nhãn do một LLM đề xuất và một người (tác giả bài) xem lại; không có người chấm độc lập thứ hai, nên có nguy cơ thiên lệch. Grounding chỉ đo độ đủ của bằng chứng truy xuất, không phải độ chính xác câu trả lời LLM.

## Kết quả

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ dev / test | Grounding 0/1/2 (số câu) · trung bình /2 |
|---|---|---|---|---|
| A | 1.10 (10) | 15/15 | 0/3 · 0/2 | 2 / 2 / 1 · 0.80 |
| B | 1.50 (10) | 15/15 | 0/3 · 0/2 | 1 / 1 / 3 · 1.40 |
| C | 1.50 (10, cùng chunk B) | 15/15 | 3/3 · 2/2 | 1 / 1 / 3 · 1.40 |

- Coherence A: 9/10 chunk bị cắt giữa từ hoặc giữa câu (chỉ pos01 = 2). B: 5/10 đạt 2; 5 chunk còn lại mất điểm vì mảnh câu ở ranh giới trang (pos02, pos05, pos07, pos09) hoặc trang quá ngắn (pos08, 294 ký tự). Nguyên nhân chung: chunk không được vượt trang.
- Grounding: q20 đạt 1 ở cả ba chiến lược vì top-3 chỉ có lời từ chối, thiếu câu nêu lý do (p440); q12 đạt 0 ở cả ba.
- Metadata đúng 100% nhưng **đủ không có nghĩa là hữu dụng**: `chapter` giúp lọc (C giữ top-3 trong đúng chương 5/5 câu filter, A/B 0/5); hạn chế: `page` là trang bản in 1894, khác số trang các ấn bản khác, và người dùng phải biết số chương mới lọc được.
- Grounding: B và C bằng điểm, nhưng ở q08 B xếp evidence ở hạng 3 sau hai đoạn gây nhầm (ch44, ch35 — phiên bản của Darcy), C đưa lên hạng 1.
