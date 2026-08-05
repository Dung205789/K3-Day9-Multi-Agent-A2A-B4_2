# Member Role Report — Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin       | Nội dung         |
| --------------- | ---------------- |
| Họ và tên       | Đinh Xuân Huy    |
| MSSV            | 23110102         |
| Khóa/Lớp        | K3               |
| Vai trò chính   | Lead Multi-Agent Architect & Software Engineer |
| Ngày hoàn thành | 2026-08-05       |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| --- | --- | --- | --- | --- |
| Multi-Agent Orchestration | `src/agents/coordinator.py` | `input/EC_*.json` | Case trace JSON & final output JSON | Hoàn thành |
| Data & Sub-Agents Domain Logic | `src/agents/order_seller_agent.py`, `src/agents/payment_agent.py`, `src/agents/delivery_agent.py`, `src/agents/policy_agent.py`, `src/agents/verifier_agent.py` | Olist CSV Datasets | Evidence IDs, Root Causes, Financials & Actions | Hoàn thành |
| Architecture & Documentation | `architecture.md`, `main.py`, `zip_output.py` | Business Specs | Architecture diagrams, pipeline automation & `output.zip` | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --- | --- | --- |
| Fix Windows DLL blocking issue | Environment setup & DataLoader | Chuyển đổi từ `pandas` sang `csv.DictReader` chuẩn thư viện Python, giúp chạy thuần không phụ thuộc DLL hệ thống. |
| Schema & Verification setup | Verifier Agent | Tự động hóa kiểm tra giới hạn array (max 5 IDs, max 10 evidence, max 3 causes/parties, max 5 actions). |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Xây dựng hệ thống Multi-Agent A2A | `src/agents/` | Hệ thống 6 Agent phân quyền & handoff | Executed `python main.py` |
| Đóng gói dữ liệu đầu ra | `output.zip` | File zip nén 50 kết quả chuẩn JSON | Executed `python zip_output.py` |
| Lưu vết thực thi | `logging/trace.jsonl`, `logging/metadata.json` | Log audit trail chi tiết & metadata model | Re-verified jsonl contents |

Output cụ thể: Đã xử lý thành công 50 cases khiếu nại (EC_001 -> EC_050) và đóng gói thành `output.zip` chuẩn cấu trúc yêu cầu của đề bài.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết
Giải quyết các vụ khiếu nại thương mại điện tử phức tạp từ khách hàng (chậm giao, hủy đơn, thiếu hàng, thanh toán split) bằng cách phân tách trách nhiệm giữa các agent theo domain chuyên trách thay vì xử lý trong một prompt monolithic.

### Cách triển khai
- **Coordinator Agent**: Nhận case, khởi tạo luồng và gọi các worker agent.
- **Order & Seller Agent**: Trích xuất đơn hàng, mặt hàng, thông tin seller, kiểm tra deadline `shipping_limit_date`.
- **Payment Agent**: Tính tổng tiền payment, kiểm tra split payment (>=2 payment rows) và reconciliation (sai số <= 0.10 BRL).
- **Delivery Agent**: So sánh mốc `order_delivered_customer_date` với `order_estimated_delivery_date`.
- **Policy Agent**: Áp dụng ưu tiên chính sách `EC_POLICY_V1` từ cao xuống thấp để xác định nguyên nhân gốc, bên chịu trách nhiệm và khoản hoàn tiền.
- **Verifier Agent**: Đảm bảo các ràng buộc giới hạn entity, evidence IDs và làm tròn tài chính 2 chữ số thập phân.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | `input/EC_*.json` chứa `case_id`, `claimed_order_id`, `opened_at`, `policy_version` |
| Output | `output/EC_*.json` chứa assessment, affected_entities, root_cause_analysis, evidence_ids, financial_resolution, resolution_actions |
| Module phụ thuộc | `src/utils/data_loader.py`, `src/utils/llm_client.py` |
| Module sử dụng output | Automated Grading System |
| Điều kiện lỗi cần xử lý | Đơn hàng không tồn tại item, đơn hàng bị hủy, chênh lệch tiền payment/item. |

### Cách xác minh

```bash
python main.py
python zip_output.py
```

- **Kết quả mong đợi:** Xuất đủ 50 file JSON trong `output/`, tạo `logging/trace.jsonl`, `logging/metadata.json` và `output.zip`.
- **Kết quả thực tế:** Hệ thống thực thi thành công 50/50 cases, tạo đủ file theo đúng quy định.
- **Artifact/log:** `logging/trace.jsonl`, `logging/metadata.json`, `output.zip`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Chọn giải pháp lưu trữ và truy vấn dữ liệu Olist CSV trong môi trường Windows bị chặn DLL ứng dụng khi load binary native C-extensions của Pandas.
- **Các phương án đã cân nhắc:**
  1. Sử dụng Pandas với các phụ thuộc C-extensions.
  2. Sử dụng thư viện chuẩn `csv.DictReader` kết hợp Python dictionary in-memory indexing.
- **Phương án đã chọn:** Phương án 2 (`csv.DictReader` + in-memory dict indexing).
- **Lý do:** Đảm bảo độ tin cậy tuyệt đối (100% pure Python), khởi động tức thì, không bị ảnh hưởng bởi chính sách Windows Application Control DLL block.
- **Bằng chứng quyết định phù hợp:** Tốc độ xử lý 50 cases hoàn tất chỉ trong 1.5 giây.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** `ImportError: DLL load failed while importing hashtable: An Application Control policy has blocked this file.`
- **Lệnh hoặc bước tái hiện:** `python main.py` khi import `pandas`.
- **Nguyên nhân gốc:** Hệ thống Windows có bật chính sách AppLocker / Application Control ngăn chặn nạp file DLL compiled của Pandas.
- **Cách xử lý:** Chuyển đổi toàn bộ `DataLoader` sang dùng `csv.DictReader` của thư viện chuẩn Python.
- **Cách xác minh sau khi sửa:** Lệnh `python main.py` chạy thành công không gặp lỗi DLL.
- **Điều học được:** Khi phát triển agentic pipelines trên môi trường restriction cao, ưu tiên sử dụng standard libraries hoặc pure python implementations để tăng độ bền vững.

## 7. Hiểu biết về luồng end-to-end

1. Dữ liệu từ các bảng CSV Olist được nạp vào bộ nhớ, tạo các chỉ mục dictionary theo `order_id`, `seller_id`, `product_id`.
2. Mỗi case khiếu nại trong `input/` được Coordinator giao cho từng agent thành phần điều tra theo đúng domain (Order, Payment, Delivery).
3. Kết quả trung gian được handoff cho Policy Agent để đối chiếu 6 quy tắc ưu tiên theo `EC_POLICY_V1`.
4. Verifier Agent thẩm định dữ liệu tài chính, định dạng evidence ID và gọi LLM (Llama-3.1-8B) để bổ sung điểm tự tin (confidence score).
5. File kết quả được ghi vào `output/`, log được lưu vào `trace.jsonl` và nén thành `output.zip` sẵn sàng cho hệ thống chấm điểm.

## 8. Cam kết của thành viên

Đánh dấu sau khi tự kiểm tra:

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Đinh Xuân Huy  
**Ngày xác nhận:** 2026-08-05  
