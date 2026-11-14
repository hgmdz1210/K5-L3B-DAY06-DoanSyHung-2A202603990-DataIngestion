# Benchmark

- `questions.json`: 24 câu hỏi về *Pride and Prejudice* (18 dev / 6 test), mỗi câu có các trường `id, split, type,
  question, expected_answer, gold_source_id, gold_page, gold_chapter, evidence_quote, alt_evidence, filter`.
- Kiểm chứng trước khi chạy: `python scripts/validate_benchmark.py` (chạy từ `starter/`).

## Các quyết định chốt TRƯỚC khi chạy truy xuất

1. **Quy tắc chia:** câu hỏi đánh số theo thứ tự trong truyện; mỗi câu thứ 4 (q04, q08, q12, q16, q20, q24) là test,
   còn lại là dev.
2. **Câu có filter:** q08, q13, q15, q20, q22 (3 dev, 2 test). Filter `{"chapter": N}` là chương được nêu trong chính
   câu hỏi; đây là input giả định có sẵn trước khi truy xuất và chỉ chiến lược C áp dụng.
3. **Tiêu chí chọn chiến lược** (chỉ dùng dev, theo thứ tự): Evidence Hit@3 cao nhất; rồi Hit@1; rồi ít chunk hơn.
   C chỉ được chọn thay B nếu không kém B trên dev. Tập test chạy một lần, sau khi đã chọn.
4. **Nhãn đánh giá:** coherence (10 vị trí cố định), kiểm tra metadata và grounding trên 5 câu test đầu
   (q04, q08, q12, q16, q20); các sheet nằm trong `starter/results/manual_labels/`. Nhãn coherence và grounding do LLM
   đề xuất, học viên xem lại từng dòng; có nguy cơ thiên lệch vì chỉ một người chấm.
5. **Câu hỏi:** học viên review từng câu hỏi trước khi chạy và thấy ổn.

## Lịch sử chạy

1. 14/11/2026: nạp đầy đủ A và B, chạy dev, chọn chiến lược C theo tiêu chí trên (C bằng B trên dev, tức
   "không kém"). Chạy test một lần.
2. 14/11/2026, sau khi chạy test: khi review code phát hiện một lỗi parser không liên quan đến kết quả test: chữ cái
   đầu chương (dạng ảnh) của 60/61 chương bị mất ('R. BENNET', 'Ithin'). Đã sửa parser, chỉ embed lại các chunk bị
   ảnh hưởng, rồi chạy lại dev và test. **Không đổi câu hỏi, cách chia, tham số hay chiến lược nào.** Hit@1 / Hit@3
   giống hệt trước và sau khi sửa (xem `starter/results/metrics_*_before_parser_fix.md`). Vì tập test đã được xem
   trước đó, số liệu test được báo cáo nguyên trạng nhưng không nên coi là hold-out hoàn toàn độc lập.

## Rủi ro đã biết

- Chỉ một tiểu thuyết: dev và test có chung nhân vật và từ vựng, nên test không độc lập về chủ đề.
- Test chỉ có 6 câu, một câu làm tỷ lệ thay đổi 17 điểm phần trăm; không kết luận chiến lược nào tốt nhất tổng quát.
