# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (trong `src/`). Lớp dương là FAIL: việc của judge là tìm ra reply hỏng.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | Đạt | **dùng** (chỉ chấm giọng điệu, không chặn release một mình) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | Không đạt (κ và R dưới sàn) | **loại** |

Ma trận nhầm lẫn (FAIL = dương):
- tone_ok: tp 24 · fp 4 · fn 6 · tn 66. Tỉ lệ FAIL quan sát 0.28, sau hiệu chỉnh Rogan-Gladen là 0.30.
- helpful: tp 9 · fp 0 · fn 21 · tn 70. Tỉ lệ FAIL quan sát 0.09, sau hiệu chỉnh Rogan-Gladen là 0.30. Judge chỉ thấy khoảng 1/3 số reply thực sự không giúp được khách.

## Case audit thủ công
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | Người | Xưng "em", kết câu bằng "nha" quá suồng sã với khách đang khiếu nại. **Rubric:** thêm luật xưng hô: chỉ dùng "LogiX" và "anh/chị"; cấm "em", "bạn ơi" và tiểu từ "nha/nhé". Thêm H-008 làm ví dụ FAIL trong prompt. |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ … rồi nha." | PASS | FAIL | Người | Cùng lỗi xưng hô như #1. Judge nhầm thân thiện với lễ phép. Luật xưng hô ở #1 sẽ bắt được case này. |
| 3 | H-029 "Dạ, vui lòng chờ. … không cần nhắn thêm." | PASS | FAIL | Người | Judge bị đánh lừa bởi từ mở đầu lịch sự ("Dạ, vui lòng") dù phần sau là câu ra lệnh. **Rubric:** chấm cả câu chứ không chấm từ mở đầu; thêm tiêu chí "không ra lệnh hay gạt khách đi". |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Judge phạt vì thiếu lời xin lỗi, nhưng reply ngắn mà đủ ý là đúng chuẩn. **Rubric:** ghi rõ "không bắt buộc xin lỗi; ngắn gọn không phải lỗi tone". |
| 5 | H-051 "Dạ, LogiX đã refund 90.000đ …" | FAIL | PASS | Người | Style guide CS của LogiX cho phép từ "refund". **Rubric:** thêm danh sách từ tiếng Anh được phép (refund, ship, voucher). |
| 6 | H-070 "… đã hoàn 90.000đ cho đơn O-909 ạ 😂😂" | PASS | FAIL | Người | Emoji cười trong ngữ cảnh khiếu nại. **Rubric:** cấm emoji trong reply khiếu nại. Nên chặn bằng code (regex emoji) thay vì để judge làm. |
| 7 | H-063 "… đã hoàn 20.000đ và sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | Người | Đây không phải lỗi tone mà là hứa vượt kết quả hệ thống (cùng họ với FM-08). **Hành động:** đưa ra khỏi tiêu chí tone; chấm bằng code: reply không được hứa khoản nào ngoài ledger. |
| 8 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn theo chính sách hiện hành ạ." | FAIL | PASS | **Judge** (theo ghi chú nhãn) | Ghi chú CSV nói người đọc nhầm ticket. **Hành động:** sửa nhãn người, không sửa rubric; cho người thứ hai gán lại nhãn cho các case judge thắng trước khi tính κ lần sau. |
| 9 | HL-016 xin lỗi dài 3 câu, "đã hoàn 55.000đ cho đơn O-404" (ledger 35.000) | PASS | FAIL | Người | Judge không thấy ledger, lại thiên vị reply dài và nhiều lời xin lỗi. 13/21 FN của helpful có dạng này. **Hành động:** việc đối chiếu số tiền với ledger chuyển sang code (`reply_matches_ledger`); rubric helpful phạt việc lặp lời xin lỗi thay cho thông tin. |
| 10 | HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | Người | Reply không nói kết quả (hoàn hay không, bao nhiêu). **Rubric:** reply helpful phải nêu status và số tiền (hoặc lý do từ chối). Đây là điều kiện kiểm được bằng code. |

## Kết luận
- **tone_ok dùng được:** κ 0.757, P 0.857, R 0.80, cả ba đều trên sàn. Lỗi còn lại tập trung ở xưng hô (FN #1, #2) và việc phạt nhầm reply ngắn hoặc có từ "refund" (FP #4, #5). Sửa rubric theo các case trên rồi calibrate lại trên một tập nhãn người mới.
- **helpful bị loại:** P = 1.0 nhưng R = 0.30 (fn 21/30), κ 0.375. Judge chỉ bắt được reply hỏng lộ liễu (9 TP, đều là câu cụt như "Bạn gửi lại thông tin đi."). Trong 21 FN có 18 reply nêu số tiền khác ledger (5 câu ngắn, 13 câu xin lỗi dài) và 3 reply mơ hồ "Ok bạn, … xử lý rồi nhé". Precision cao không cứu được judge này: dùng làm gate thì 70% reply không giúp được khách vẫn lọt qua, và tỉ lệ FAIL đo được (0.09) thấp hơn thực tế (~0.30) hơn ba lần. Phần lỗi chính (sai số tiền) phải chấm bằng code: tiền luôn chấm bằng code, không dùng judge.
- **Rủi ro còn lại:** judge chỉ được kiểm trên dữ liệu replay đã công khai. Cần nhãn người mới để có tập held-out thật. Nhãn người cũng có lỗi (H-081), nên cần người thứ hai gán nhãn.
