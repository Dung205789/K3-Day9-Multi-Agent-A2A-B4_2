# Member Role Report — Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin       | Nội dung                                            |
| --------------- | --------------------------------------------------- |
| Họ và tên       | Ngô Quang Dũng                                      |
| MSSV            | …01819                                              |
| Khóa/Lớp        | K3                                                  |
| Vai trò chính   | Thiết kế kiến trúc agent, rule engine và lớp kiểm chứng |
| Ngày hoàn thành | 2026-08-05                                          |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable      | File/hàm phụ trách                                  | Input nhận vào                        | Output bàn giao                                 | Trạng thái |
| ----------------------- | --------------------------------------------------- | ------------------------------------- | ----------------------------------------------- | ---------- |
| Lớp truy cập dữ liệu    | `src/datastore.py` — `DataStore`, `ScopedView`       | 9 CSV Olist                           | Kho index theo `order_id` + hàng rào quyền đọc   | Hoàn thành |
| Rule engine EC_POLICY_V1| `src/policy.py` — `evaluate`, `build_evidence`, `_ambiguity` | Fact sheet của một đơn        | `primary_issue`, refund, evidence ID, cờ mơ hồ   | Hoàn thành |
| Giao thức A2A           | `src/a2a.py` — `Message`, `Bus`, `TraceRecorder`     | Lời gọi từ agent                       | `trace.jsonl` phát lại được                      | Hoàn thành |
| Sáu agent               | `src/agents/*.py`                                    | Row CSV trong phạm vi từng agent       | Payload bằng chứng qua A2A                       | Hoàn thành |
| Điều phối + hiệu chỉnh confidence | `src/pipeline.py` — `run_case`, `facts_from_bundle` | Case JSON                    | `output/EC_xxx.json`                             | Hoàn thành |
| Bộ tự chấm              | `src/audit.py` — `score_case`, `hard_gates`          | `output/` + CSV                        | `logging/audit.json`                             | Hoàn thành |
| Console demo            | `src/server.py`, `web/`                              | `trace.jsonl`, `output/`               | Giao diện vận hành + chạy live qua SSE           | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động                          | Thành viên/module được hỗ trợ | Kết quả                                                        |
| ---------------------------------- | ----------------------------- | -------------------------------------------------------------- |
| Đóng gói và kiểm tra bài nộp       | Toàn nhóm                     | `src/package_submission.py` từ chối nén nếu thiếu case/sai tên |
| Tài liệu kiến trúc                 | Toàn nhóm                     | `architecture.md` — sơ đồ, phạm vi dữ liệu, luồng 8 bước       |
| Skill chạy lại dự án               | Người tiếp nhận repo          | `.claude/skills/run-k3-day9-multi-agent-a2a/driver.mjs`         |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện                                     | File/hàm/artifact liên quan            | Kết quả bàn giao                              | Cách xác minh                       |
| --------------------------------------------------------- | -------------------------------------- | ---------------------------------------------- | ----------------------------------- |
| Cưỡng chế phạm vi dữ liệu từng agent bằng code             | `datastore.ScopedView._guard`          | Agent đọc sai bảng → `PermissionError`         | Test ở mục 4 bên dưới               |
| Mã hoá bảng luật mục 4 thành rule engine ghi lại 6 phép thử | `policy.evaluate`                       | Mỗi case kèm 6 dòng lý do đạt/không đạt        | `python -m src.audit`               |
| Chọn evidence theo nguyên tắc "đúng dòng mà luật đã đọc"   | `policy.build_evidence`                | 0 evidence sai trên 5.328 đơn kiểm thử          | Stress test ở mục 4                 |
| Đo mức lệch giữa LLM và dữ liệu                            | `agents/base.Agent.reconcile`          | 70 field lệch (44 trọng yếu) bị chặn hết       | `metadata.json → run_stats`         |
| Chạy toàn bộ 50 case chính thức                            | `src/run_all.py`                       | 50 output, 651 message A2A, ~$0.065            | `python -m src.run_all --workers 8` |

Output cụ thể do phần việc của tôi tạo ra:

`logging/audit.json` — bộ tự chấm dựng lại đáp án đúng trực tiếp từ CSV rồi so với `output/` theo đúng 6 trọng số mục 8, kèm kiểm tra hard gate riêng. Trên bộ 50 case chính thức: trung bình 100.00/100, 0 hard-gate lỗi, 0 case sai `primary_issue`. Đây là thứ bắt được lỗi verifier hạ nhầm confidence xuống dưới 0.7 làm mất điểm, mô tả ở mục 6.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Đề bài giới hạn mỗi agent dùng model ≤10B tham số. Model ở cỡ đó đọc bảng luật thì ổn nhưng cộng tiền và so timestamp thì không ổn định. Nếu để model tự quyết toàn bộ, sai số rơi thẳng vào `financial_resolution` và `primary_issue` — hai hạng mục chiếm 40% điểm. Vấn đề tôi phải giải là: **dùng được model nhỏ mà vẫn cho ra kết quả tất định**, đồng thời không biến hệ thống thành một script rồi dán nhãn "multi-agent".

### Cách triển khai

Ba quyết định chính:

**Chia việc theo dữ liệu, không theo bước xử lý.** Mỗi agent sở hữu một tập bảng CSV, khai báo trong `AGENT_SCOPES`. `ScopedView._guard` ném `PermissionError` nếu agent chạm bảng ngoài phạm vi. Hệ quả là Payment agent không nhìn thấy mốc giao hàng nên không thể tự kết luận đơn có trễ hay không — nó buộc phải nhận kết quả từ Delivery agent qua message A2A. Bàn giao trở thành ràng buộc kỹ thuật chứ không phải quy ước trong prompt.

**Tách phán đoán khỏi số học.** Agent vẫn được yêu cầu tự đưa ra con số, sau đó `Agent.reconcile` so với giá trị tính từ CSV: lệch thì lấy giá trị CSV nhưng **ghi lại vào trace** kèm mức độ `critical`/`minor`. Nếu chỉ tính bằng code thì sạch hơn, nhưng sẽ không đo được model yếu ở đâu. Con số 70 field lệch trong 50 case là sản phẩm trực tiếp của lựa chọn này.

**Hai đường quyết định độc lập.** Câu hỏi "đơn này thuộc loại vi phạm nào" được trả lời hai lần: Policy agent (LLM, chỉ thấy bằng chứng đồng nghiệp bàn giao, không có quyền đọc CSV) và `policy.evaluate` (code, đọc thẳng dữ liệu). Khớp nhau thì yên tâm; lệch nhau thì lấy rule engine và phát message `reject/policy_disagreement` vào trace.

**Evidence = đúng những dòng mà luật đã đọc.** Bản đầu tiên cắt cứng mỗi loại 2–4 dòng nên chỉ dùng 3–7 trên hạn mức 10, mất recall ở đơn nhiều item/nhiều payment. Bản hiện tại xếp hạng theo mức quyết định rồi lấy đủ tới hạn mức: với `late_delivery_seller`, item và seller **vi phạm** đứng trước, vì dòng của một seller giao đúng hạn không chứng minh được vi phạm nào cả.

**Confidence đo chất lượng dữ liệu, không đo độ lúng túng của model.** `policy._ambiguity` liệt kê lý do khiến kết luận đứng trên dữ liệu thiếu: không luật nào khớp, thiếu ngày bàn giao carrier, đơn không có payment row, nhiều seller mà chỉ một số vi phạm, chênh lệch thanh toán nằm đúng ngưỡng 0.10 BRL, và trường hợp giao đúng ngày cam kết nhưng sau 00:00.

### Input, output và contract

| Thành phần              | Mô tả                                                                                     |
| ----------------------- | ----------------------------------------------------------------------------------------- |
| Input                   | `input/EC_xxx.json` — `case_id`, `opened_at`, `customer_request.claimed_order_id`, `policy_version` |
| Output                  | `output/EC_xxx.json` theo schema mục 6 + `trace.jsonl` + `metadata.json`                   |
| Module phụ thuộc        | `datastore` (dữ liệu), `llm` (gọi model), `a2a` (vận chuyển message)                        |
| Module sử dụng output   | `audit` (tự chấm), `server`/`web` (console), `package_submission` (đóng gói)                |
| Điều kiện lỗi cần xử lý | `order_id` không tồn tại → `escalate` + output rỗng hợp lệ; đơn không có item row → `item_ids`/`seller_ids` rỗng và tiền hàng/freight = `0.0`; JSON model trả về hỏng → nhét lại vào hội thoại và yêu cầu sửa; lượt LLM lỗi mạng → retry có backoff |

### Cách xác minh

```bash
python -m src.run_all --workers 8
python -m src.audit
```

- **Kết quả mong đợi:** 50 output hợp lệ, không case nào dính hard gate.
- **Kết quả thực tế:** `50 cases in 95.5s`, tự chấm `mean score 100.00/100`, `hard-gate failures 0`, `wrong primary_issue 0`. 350 lượt gọi LLM, 651 message A2A, ~$0.065.
- **Artifact/log:** `logging/audit.json`, `trace.jsonl`, `metadata.json` (không chứa secret; API key nằm trong `.env` đã gitignore).

Hai kiểm chứng riêng cho phần hàng rào quyền và phần evidence:

```bash
# 1. Agent doc ngoai pham vi thi chuong trinh dung
python -c "
from src.datastore import DataStore, scoped
v = scoped(DataStore(), 'payment')
try: v.order('x')
except PermissionError as e: print('chan dung:', e)"

# 2. Evidence khong bia tren 5328 don (ke ca don nhieu seller)
python -c "
from src.datastore import DataStore
from src.policy import evaluate, build_evidence
# ... duyet mau don, kiem tra moi evidence ID ton tai that trong CSV"
```

- Kết quả 1: `PermissionError: agent 'payment' is not allowed to read table 'orders' (scope: order_payments, order_items)`.
- Kết quả 2: 5.328 đơn, **0 evidence sai định dạng hoặc không tồn tại**, 0 case vượt hạn mức 10, `policy:` luôn có mặt.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** `order_estimated_delivery_date` trong Olist **luôn là 00:00:00** — nó mã hoá một *ngày*, không phải một mốc giờ. Một đơn giao lúc 21:52 đúng ngày cam kết sẽ bị tính là "trễ" nếu so timestamp, nhưng là "đúng hạn" nếu so ngày. Hai cách đọc cho hai kết luận trái ngược, ảnh hưởng trực tiếp tới `primary_issue`, bên chịu trách nhiệm và số tiền hoàn.
- **Các phương án đã cân nhắc:** (a) so timestamp thô như dữ liệu ghi; (b) so theo ngày lịch, coi giao trong ngày cam kết là đúng hạn.
- **Phương án đã chọn:** (a) so timestamp, đồng thời **đánh dấu mơ hồ và hạ confidence** cho case rơi vào vùng này.
- **Lý do:** README mục 2 ghi "các timestamp được so sánh theo giá trị trong CSV". Quan trọng hơn, tôi đo trên toàn bộ 96.476 đơn có đủ hai mốc: 1.292 đơn rơi vào vùng nhập nhằng, chiếm **16,5% tổng số đơn được coi là trễ** — đủ lớn để đổi cách đọc là một canh bạc. Kiểm tra bộ 50 case chính thức thì **không case nào rơi vào vùng đó**, độ trễ nhỏ nhất là 2,76 ngày. Biên an toàn đó cho thấy đề bài cố tình tránh sự nhập nhằng, nên đổi cách đọc nhiều khả năng làm hỏng hơn là sửa được gì.
- **Bằng chứng quyết định phù hợp:** số liệu 1.292/7.827 đơn nhập nhằng và 0/16 case trễ trong bộ chính thức, đo bằng script quét toàn bộ dataset. Việc gắn cờ mơ hồ giữ được phần phòng thân: nếu private test có ca như vậy và tôi đọc sai, confidence của riêng case đó đã tự tụt xuống ~0.85 thay vì báo 0.95 một cách sai lầm.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** Verifier từ chối **mọi** bản nháp dù kết luận đúng, kéo confidence xuống 0.58–0.76 và làm mất điểm hạng mục "Primary issue và confidence". Nội dung trong `trace.jsonl`:

  ```
  EC_001 approved: False  adj: -0.25
     concern: primary_issue không có bằng chứng ủng hộ
     concern: responsible_parties không nhất quán với primary_issue
  ```

- **Lệnh tái hiện:** `python -m src.run_all --limit 6 --workers 3` rồi lọc `intent == "verification_report"` trong `trace.jsonl`.
- **Nguyên nhân gốc:** prompt của Verifier liệt kê 4 mục cần kiểm tra, và model 8B **nhại lại chính checklist đó thành danh sách lỗi** thay vì đối chiếu với bằng chứng. Đây là kiểu hỏng đặc trưng của LLM-làm-giám-khảo: nó bám mẫu câu trong prompt chứ không suy luận trên dữ liệu. Một ca lộ rõ nguyên nhân là `EC_031`: model gắn nhãn `fail` cho `refund_type_correct` nhưng bằng chứng nó tự trích ra — `recommended_refund_brl=77.88, expected_total_brl=77.88` — lại **chứng minh là đúng**.
- **Cách xử lý:** ba lớp trong `src/agents/verifier.py`. Một, đổi schema để mỗi check bắt buộc trích `field=giá trị` cụ thể thay vì viết nhận xét tự do. Hai, `fail` nào không trích nổi bằng chứng (dưới 8 ký tự) bị hạ xuống `pass`. Ba, `fail` trên hạng mục mà lớp kiểm tra tất định **đã chứng minh bằng số** (`refund_type_correct`, `parties_consistent`) bị hạ xuống `advisory` — một tín hiệu yếu không được phép lật một chứng minh.
- **Cách xác minh sau khi sửa:** chạy lại và đọc `llm_review.checks` trong trace. Verifier chuyển sang trích field thật (`assessment.primary_issue=valid_split_payment`, `financial_resolution.recommended_refund_brl=0.0`), confidence hồi lên 0.91–0.95, và `python -m src.audit` đạt 100.00/100.
- **Điều học được:** không đưa checklist vào prompt của một model nhỏ rồi hỏi nó "có lỗi gì không" — nó sẽ trả lại chính checklist. Phải bắt nó trích bằng chứng cụ thể cho từng kết luận, và không cho tín hiệu yếu ghi đè lên phần đã được kiểm chứng bằng phép tính.

## 7. Hiểu biết về luồng end-to-end

> Ghi chú: 5 câu hỏi trong mẫu (Crossref, vector index, retrieval/answer quality, corrupted/repaired test set) thuộc về lab RAG khác, không có thành phần nào tương ứng trong bài Day 9 này. Tôi trả lời theo đúng tinh thần câu hỏi nhưng áp vào luồng thật của bài multi-agent.

**1. Dữ liệu đi từ CSV Olist đến kết luận như thế nào?**
`DataStore` nạp 8 CSV một lần, đánh chỉ mục theo `order_id` (bỏ geolocation 1 triệu dòng vì không luật nào cần). Mỗi agent nhận một `ScopedView` chỉ mở đúng phần bảng thuộc phạm vi của nó. Agent đọc row thô, tự rút kết luận domain, rồi gửi payload qua `Bus.send`. Coordinator dựng lại fact sheet **chỉ từ các payload đó** bằng `facts_from_bundle` — bản thân nó không có quyền chạm CSV, nên mọi con số trong output đều đã đi qua một message A2A từ agent được phép đọc bảng chứa nó.

**2. Lấy gì làm đáp án đúng để đo chất lượng?**
`src/audit.py` dựng lại đáp án trực tiếp từ CSV bằng chính rule engine, rồi so với `output/` theo 6 trọng số mục 8 (F1 cho các tập ID, so khớp chính xác cho action, sai số 0.01 cho tiền). Đây là đáp án độc lập với đường chạy agent, nên nó bắt được lỗi mà pipeline tự nó không thấy — cụ thể là ca confidence bị hạ nhầm ở mục 6.

**3. Kiểm chứng khác giám sát ở điểm nào?**
Kiểm chứng chặn từng case trước khi ghi file: Verifier soi schema, sự tồn tại thật của mọi ID trong CSV, số tiền đúng loại theo issue, giới hạn số lượng — và được phép sửa bản nháp. Giám sát thì đo trên cả lượt chạy và không chặn gì: tỷ lệ đồng thuận giữa hai đường quyết định, số field LLM đọc lệch dữ liệu, token và chi phí. Một cái quyết định "case này có được ghi ra không", cái kia trả lời "lượt chạy này có gì bất thường không".

**4. Vì sao phải giữ nguyên bộ dữ liệu khi so sánh các phiên bản?**
Vì mọi thay đổi tôi làm — sửa prompt Verifier, đổi cách chọn evidence, hiệu chỉnh confidence — đều phải đo trên cùng 50 case thì mới biết là cải thiện hay hồi quy. Đổi cả input lẫn code cùng lúc thì không quy được nguyên nhân cho thay đổi nào. Riêng phần rule engine tôi kiểm thêm trên mẫu 5.328 đơn ngẫu nhiên để bắt ca biên mà bộ 50 không chứa.

**5. Dựa vào artifact và metric nào để coi là đạt?**
`logging/audit.json` (trung bình 100.00/100, `hard_gate_failures = 0`, `wrong_primary_issue = 0`), `metadata.json → run_stats` (tỷ lệ đồng thuận, số field lệch bị chặn, token và chi phí), và `trace.jsonl` (651 message, phát lại được toàn bộ hội thoại). Cả ba đều sinh ra từ lượt chạy thật, không phải ghi tay.

## 8. Cam kết của thành viên

Đánh dấu sau khi tự kiểm tra:

- [ ] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [ ] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [ ] Tôi không ghi "đã chạy thành công" cho phần chưa được kiểm chứng.
- [ ] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [ ] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Ngô Quang Dũng
**Ngày xác nhận:** 2026-08-05
