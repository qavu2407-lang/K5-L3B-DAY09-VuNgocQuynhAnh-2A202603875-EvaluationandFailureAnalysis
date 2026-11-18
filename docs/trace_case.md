# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-014 --seed 11
python -m lab9.trace_case --shape fixed --claim C-014 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Case: `seeded_regression` C-014@11

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-014@11`, run ID `E-seeded_regression-20261118-430d` (item E-014) |
| Triệu chứng | `refund_amount_correct` FAIL, `reply_matches_ledger` FAIL, lab8 FAIL `proposal_mismatch`. Reply nói "đã hoàn 120.000đ" trong khi ledger ghi **90.000**; nhãn yêu cầu 120.000. |
| Bước sai đầu tiên | Event **#5 `proposal`** `{"amount_vnd": 120000}`: agent lấy quote 150.000 trừ đi khoản 30.000 đã hoàn trước khi gọi host. |
| Vì sao là bước *đầu tiên* | #1 `handoff` và #2 `investigator` đọc đúng đơn O-515. #3 `quote` ra 150.000 khớp với `proposal_amount` của nhãn. #4 `refund_history` đọc đúng khoản đã hoàn 30.000, vì đây chỉ là thao tác đọc. Sai bắt đầu ở #5, khi agent dùng số vừa đọc để tự trừ; theo luật Lab 8, host mới là bên trừ phần đã hoàn. |
| Failure mode | **FM-05 pre_deducted**. Hệ quả kéo theo là FM-08: reply báo số mình đề xuất chứ không phải số host ghi. |
| Đối chứng | `fixed` C-014@11 không có event `refund_history` hay `proposal`: #3 quote 150.000 được chuyển thẳng cho host, host tự trừ 30.000, ledger 120.000 khớp nhãn, reply "đã hoàn 120.000đ". |
| Regression test | `src/tests/test_lab9_trace_case.py`: `test_trace_case_c014_pre_deducted_caught` kiểm event proposal = 120.000, ledger = 90.000 và `RefundAmountCorrect` FAIL trên `seeded_regression`; `test_trace_case_c014_fixed_passes` kiểm trên `fixed` không có proposal, ledger 120.000, `RefundAmountCorrect` và `ReplyMatchesLedger` PASS. Đã chạy: cả hai pass. |
| Chưa chắc chắn | Trace không ghi lời gọi `issue_refund` và phản hồi của host, nên việc host "trừ thêm 30.000" là suy ra từ chênh lệch ledger (120.000 → 90.000) và luật trong `business_rules.md` của Lab 8, không đọc trực tiếp từ event. Trace cũng không cho biết `seeded_regression` bật nhiều lỗi cùng lúc; trên claim này chỉ `pre_deducted` có tác động. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
