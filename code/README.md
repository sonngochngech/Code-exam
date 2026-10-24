# Hệ thống AI trợ giảng và giám sát kỳ thi

Hai sản phẩm dự thi dùng chung một nền tảng:

1. **AI trợ giảng theo môn học ngoài giờ lên lớp** (dự án kĩ thuật)
2. **Giám sát tự động trong kỳ thi trực tuyến** (dự án khoa học)

Dùng chung phần đăng nhập, cơ sở dữ liệu, giao diện và máy chủ, nên chi phí
hạ tầng chỉ tính một lần.

---

## Cài đặt

### Bước 1. Cài Python

Cần Python 3.10 trở lên. Tải tại python.org, khi cài nhớ **tích vào ô
"Add Python to PATH"**. Kiểm tra lại:

```
python --version
```

### Bước 2. Cài thư viện

```
cd code
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Bước 3. Cấu hình

```
copy .env.example .env
```

Mở `.env` và điền khóa API nếu có. **Để trống cũng chạy được**, khi đó hệ thống
tự vào chế độ giả lập: toàn bộ giao diện, luồng làm bài, giám sát camera và
bảng thống kê đều hoạt động, chỉ riêng câu trả lời của phần hỏi bài là theo mẫu
có sẵn thay vì do AI sinh ra. Rất tiện khi tập trình bày mà không muốn tốn tiền.

### Các trang trong hệ thống

| Đường dẫn | Dành cho | Nội dung |
|---|---|---|
| `/` | mọi người | Đăng nhập và chọn phần |
| `/tro-giang` | học sinh | Hỏi bài, xem lịch sử, chuỗi ngày học |
| `/lam-bai` | học sinh | Làm bài kiểm tra, giám sát bằng camera |
| `/bang-dieu-khien` | giáo viên | Thống kê điểm yếu lớp, sinh đề luyện tập |
| `/coi-thi` | giáo viên | Phán đoán hai vòng, xem bằng chứng |
| `/quan-tri` | giáo viên | Nạp học liệu, soạn đề, mở ca thi, xuất dữ liệu |

Trang quản trị làm được mọi việc mà trước đây phải gõ lệnh: nạp đề cương, sửa
nhãn chương bài khi máy đoán sai, soạn đề thi, mở ca thi, xem báo cáo buổi thi,
so sánh hai nhóm kèm kiểm định t, tải dữ liệu CSV và dọn dữ liệu tập dượt.

### Bước 4. Nạp dữ liệu mẫu

**Cách nhanh nhất (dùng ngay):** chép cơ sở dữ liệu mẫu có sẵn rồi chạy ứng dụng.

```
copy data\demo\hethong.demo.db data\hethong.db        (Windows)
cp data/demo/hethong.demo.db data/hethong.db            (macOS/Linux)
```

Cơ sở dữ liệu mẫu chỉ có dữ liệu giả để thử: 32 tài khoản mẫu, 36 đoạn học liệu
(Toán 9 và Vật lí 9, tự soạn), một đề mười câu và hai ca thi ở trạng thái nháp
(lớp 9A có giám sát, lớp 9B đối chứng). Không có ảnh, bài làm hay dữ liệu thật.
Giáo viên chỉ cần vào **Quản trị → Ca thi**, bấm **Mở** rồi **Tạo mã dự thi**.
Chạy lệnh trên sẽ ghi đè `data/hethong.db`, nên đừng chạy khi đã có dữ liệu riêng.

**Hoặc tự tạo từ đầu:**

```
python nap_du_lieu.py de-mau
```

Lệnh này tạo một đề mười câu và hai ca thi: lớp 9A thuộc nhóm có giám sát,
lớp 9B thuộc nhóm đối chứng.

Nạp học liệu cho phần hỏi bài (hai file đề cương mẫu đi kèm):

```
python nap_du_lieu.py hoc-lieu data\hoclieu\decuong_toan9.docx "Toán"
python nap_du_lieu.py hoc-lieu data\hoclieu\decuong_vatli9.docx "Vật lí"
```

### Bước 5. Chạy

```
python -m uvicorn app.main:app --reload
```

Mở trình duyệt vào `http://127.0.0.1:8000`.

### Bảo vệ dữ liệu khi triển khai

HTTP chỉ dùng khi chạy cục bộ. Trên máy chủ trường, đặt FastAPI sau reverse
proxy HTTPS, truyền `X-Forwarded-Proto: https` và đặt `BAT_BUOC_HTTPS=1`.
Ứng dụng sẽ từ chối HTTP không mã hóa ngoại localhost và gửi HSTS khi
dùng HTTPS.

SQLite không tự mã hóa. `DUONG_DAN_DB` bắt buộc phải trỏ tới ổ đĩa do
nhà trường quản lý và đã bật mã hóa toàn ổ (BitLocker trên Windows,
FileVault trên macOS hoặc LUKS trên Linux). Không sao chép tệp cơ sở dữ liệu
ra thiết bị cá nhân không mã hóa. Đây là chốt triển khai bắt buộc của
NFR-002, không phải tùy chọn của môi trường thật.

---

## Tài khoản và mã dự thi

| Mã | Vai trò |
|---|---|
| `TN01` đến `TN15` | Định danh học sinh lớp 9A, nhóm có giám sát |
| `DC01` đến `DC15` | Định danh học sinh lớp 9B, nhóm đối chứng |
| `gv01`, `gv02` | Giáo viên |

Giáo viên đăng nhập bằng mã mẫu. Trước ca thi, giáo viên bấm **Mã dự thi** để
sinh một mã ngẫu nhiên tám ký tự cho từng học sinh đã phân công. Học sinh dùng
mã này để đăng nhập đúng ca; mã cũ mất hiệu lực khi giáo viên sinh lại và mọi mã
hết hiệu lực khi ca đóng. Máy chủ chỉ lưu bản băm của mã dự thi.

Giáo viên vẫn **chưa có mật khẩu**, nên cơ chế này chỉ phù hợp phạm vi thử nghiệm
trong lớp có giám sát. Muốn mở rộng toàn trường thì phải bổ sung xác thực giáo
viên phù hợp.

---

## Cấu trúc mã nguồn

```
code/
  app/
    config.py     Mọi thiết lập, đọc từ .env
    db.py         Cơ sở dữ liệu SQLite, toàn bộ bảng
    llm.py        Cửa duy nhất gọi AI. Đổi nhà cung cấp chỉ sửa file này
    rag.py        Xử lý học liệu và tìm đoạn liên quan bằng BM25
    main.py       Khởi động, đăng nhập, gắn các trang
    routers/
      tutor.py    Hệ thống 1: hỏi bài, chứa quy tắc sư phạm
      exam.py     Hệ thống 2: kho đề, ca thi, chấm bài
      proctor.py  Hệ thống 2: mốc bất thường, phán đoán hai vòng
      stats.py    Thống kê và kiểm định thống kê cho báo cáo
  web/            Giao diện, HTML và JavaScript thuần
  data/           Cơ sở dữ liệu và học liệu, không đưa lên kho chung
  nap_du_lieu.py  Công cụ nạp học liệu và tạo dữ liệu mẫu
```

---

## Những chỗ cần giải thích được trước hội đồng

**Vì sao không dùng vector database.** Thuật toán BM25 trong `rag.py` chạy ngay
trên máy, không tốn tiền gọi dịch vụ ngoài, và đọc hiểu được từng bước. Với kho
học liệu cỡ một trường thì đủ nhanh và đủ chính xác. BM25 chấm điểm theo ba ý:
từ khóa xuất hiện nhiều thì điểm cao, từ hiếm đáng giá hơn từ phổ biến, và đoạn
quá dài bị phạt.

**Vì sao hệ thống không đưa đáp án ngay.** Toàn bộ quy tắc nằm trong hằng số
`LOI_DAN_HE_THONG` ở `routers/tutor.py`. Trong đó có cả phần xử lý khi học sinh
tìm cách lấy đáp án nhanh, ví dụ nói đã làm xong rồi chỉ cần đối chiếu.

**Vì sao video không rời khỏi máy học sinh.** Nhận diện khuôn mặt chạy bằng
MediaPipe ngay trong trình duyệt (`web/exam.html`). Máy chủ chỉ nhận mốc thời
gian kèm một ảnh nhỏ 160 nhân 120 điểm ảnh tại đúng thời điểm có dấu hiệu.
Không có đoạn mã nào gửi luồng video đi.

**Vì sao giáo viên phải phán đoán hai vòng.** Nếu lớp A có giáo viên dùng dữ
liệu còn lớp B có giáo viên không dùng, chênh lệch có thể do năng lực hai người
khác nhau. Cho cùng một giáo viên phán đoán hai lần trên chính lớp mình thì loại
được yếu tố đó. Máy chủ bắt buộc nộp vòng 1 xong mới mở dữ liệu cho vòng 2, xem
`routers/proctor.py`.

**Ngưỡng cảnh báo lấy từ đâu.** Bốn ngưỡng nằm trong `.env`, mục giám sát. Hạ
ngưỡng xuống thì bắt được nhiều hơn nhưng báo nhầm nhiều hơn. Đây là đánh đổi
học sinh tự thử trong buổi học thứ ba.

---

## Chi phí vận hành

Mô hình mặc định trong `.env.example` là `claude-opus-5-5`, mạnh nhất nhưng
cũng đắt nhất. Với ứng dụng hỏi bài hằng ngày, nên cân nhắc đổi sang mô hình
rẻ hơn, chỉ cần sửa dòng `MA_MO_HINH`. Phần `llm.py` có sẵn cơ chế ghi nhớ
đoạn lời dặn hệ thống để giảm chi phí ở những lượt hỏi sau.

Muốn dùng máy chủ nói chuẩn OpenAI thay vì Claude thì đặt `NHA_CUNG_CAP=openai`
và điền `OPENAI_BASE_URL`. Không phải sửa dòng mã nào.

---

## Giới hạn hiện tại

- Chưa có mật khẩu, xem mục tài khoản ở trên.
- Phần nhận diện hướng nhìn dùng vị trí sống mũi so với hai bên má để ước lượng
  hướng đầu. Cách này ổn định và giải thích được, nhưng không phải là đo hướng
  nhìn của mắt theo đúng nghĩa.
- Nếu máy học sinh không tải được mô hình nhận diện, hệ thống vẫn cho làm bài
  bình thường và vẫn ghi nhận việc chuyển cửa sổ, chỉ mất phần camera. Khi đó
  cần báo giáo viên để ghi vào nhật ký nghiên cứu.
- Phần tự luận ngắn trong kho đề mới có chỗ lưu, chưa có giao diện chấm.
