# MEBLOCK – CORE (Experimental)  
**Mind Explore Block · ESP32 · MicroPython**

> CORE thử nghiệm cho dự án **MEBLOCK – Mind Explore Block**.  
> Mục tiêu: vận hành **nạp app qua OTA BLE**, thực thi **một file app .py duy nhất**, lưu & tự chạy lại sau reset, đồng thời hỗ trợ **cập nhật Core** và **bổ sung thư viện** từ xa.

---

## 🔧 Thiết bị & Nền tảng

- **Board:** ESP32 (đang thực hiện trên ESP32/ESP32-S3)
- **Firmware:** **MicroPython** (dùng bản tương thích với thiết bị)
- **Kết nối OTA:** **Bluetooth Low Energy (BLE)**

---

## ✨ Chức năng chính của CORE

1. **OTA qua BLE:** nhận và ghi **một file app .py** từ xa (PC/Web) qua BLE.  
2. **Thực thi app ngay & tự khởi động lại:** chạy app vừa nạp; **lưu “app gần nhất”** để tự chạy sau khi **reset/khởi động lại**.  
3. **OTA nền:** trong khi app đang chạy vẫn có thể **nạp app mới**; sau khi nạp xong **reset** để chạy app mới.  
4. **Nâng cấp CORE & cập nhật thư viện:**  
   - **Nâng cấp CORE** (bộ **4 file .py** - **main** - **ble_ota** - **fw_ota** - **boot**)
   - **Nạp thêm/cập nhật thư viện** (nhiều file .py) **Không phải app**.

---

## 📁 Cấu trúc CORE (4 file)

| File        | Vai trò (giải thích nhanh)                                                                 |
|-------------|---------------------------------------------------------------------------------------------|
| `boot.py`   | Khởi động **an toàn**: gắn cờ safe-mode (nếu cần), chuẩn bị môi trường, mount FS, chuyển điều khiển cho `main.py`. |
| `main.py`   | **Điều phối CORE**: khởi tạo BLE OTA, đọc cấu hình/lần app gần nhất, chạy app hoặc vào safe-mode nếu lỗi. |
| `ble_ota.py`| **Giao thức BLE**: quảng bá, bắt tay, nhận gói, kiểm tra toàn vẹn, ghi file (app/thư viện/CORE) theo **manifest**. |
| `fw_ota.py` | **Trình cập nhật**: xử lý **gói nâng cấp CORE** (4 file) & **gói thư viện** (nhiều file).|

---

## 🔄 Luồng hoạt động (Demo)

1. **Boot** → `boot.py` chuẩn bị môi trường.  
2. **Main** → `main.py` bật **BLE OTA**, đọc **app gần nhất** từ cấu hình.  
3. **Nếu có yêu cầu OTA:** `ble_ota.py` nhận file, kiểm tra CRC/size, ghi tạm;  
   - Nếu là **app** → thay **“app hiện tại”**, ghi dấu làm **last app**, và **reset**.  
   - Nếu là **CORE update** → chuyển cho `fw_ota.py` thay 4 file; **reset**.  
   - Nếu là **thư viện** → xử lý tương tự CORE.
4. **Sau reset** → `main.py` chạy app mới.

---

## 🚀 Bắt đầu nhanh

### 1) Flash MicroPython cho ESP32
- Dùng `esptool.py` để nạp firmware MicroPython phù hợp - Updating --------------------------------

### 2) Chép CORE vào thiết bị
- Sao chép **4 file** `boot.py`, `main.py`, `ble_ota.py`, `fw_ota.py` lên **/** (root) của ESP32.  
- Có thể dùng **mpremote/Thonny/ampy** qua USB lần đầu. (Đây là gòi Core cơ bản)

### 3) Kết nối & nạp app qua BLE
- Trên PC/Web, dùng công cụ OTA **Tool_host/ble_push.py** (Updating)
  - **Ghép nối** với thiết bị 
  - **Gửi 1 file app .py** (ví dụ **`app.py`**) 
  - CORE sẽ ghi nhận, **chạy app ngay** và **lưu làm app gần nhất**.

### 4) Nâng cấp CORE / Thêm thư viện
- Gửi **core_vx.zip** chứa file **manifest.json** mô tả Core.
  - **CORE update:** 4 file `boot.py`, `main.py`, `ble_ota.py`, `fw_ota.py`.  
  - **LIB update:** một hoặc nhiều file `.py` gói lại tương tự core.

---

## 📦 Định dạng gói cập nhật 

Updating ---------------------------------------------------------------------

> **Quy ước:**  
> - **App**: đúng **1 file `.py`** (ví dụ `/app.py`).  
> - **CORE**: đúng **4 file** ghi đè vào root.  
> - **LIB**: nhiều file `.py` 
> - **post_action**: mặc định `reset` sau khi ghi đủ & kiểm tra checksum.

---

## 🧩 Skeleton app mẫu (một file)

Updating -----------------------------------------------------------------------

**Yêu cầu:** app **không** quản lý BLE OTA; CORE sẽ làm việc đó ở nền.

---

## 🗂️ Thư mục gợi ý trên thiết bị

Updating -----------------------------------------------------------------------

> Cách tổ chức có thể thay đổi theo build, nhưng nguyên tắc là **tách app** và **lib** để OTA lib không kích hoạt “chạy app”.

---

## 🧪 Log & Safe Mode

Updating -----------------------------------------------------------------------
ĐỀ XUẤT 1 VÀI TÍNH NĂNG:
- **Log khởi động**: in tên phiên bản CORE, trạng thái BLE OTA sẵn sàng.  ---- DONE
- **Safe-mode**: nếu app lỗi khi khởi động N lần liên tiếp, CORE có thể vào chế độ 
- **REPL only**, vẫn bật BLE để cho phép **nạp app mới** khi cổng giao tiếp bị Treo

---

## ⚠️ Lưu ý & Hạn chế

- Chỉ hỗ trợ **một file app .py** mỗi lần nạp.  
- Trong khi **OTA nền**, app vẫn chạy; khi ghi xong sẽ **reset** để áp dụng.  
- Đảm bảo **nguồn ổn định** trong quá trình OTA CORE.

---

## 🙌 Đóng góp

Đóng góp theo các mục: cải tiến BLE, ổn định OTA nền,tự động hóa các quy trình (Tạo app, tạo config, nhận diện thiết bị ...vv..)
  
> CORE = 4 file `boot.py`, `main.py`, `ble_ota.py`, `fw_ota.py`  
> → OTA qua BLE **1 file app.py**, chạy ngay & auto-restart, lưu “last app”.  
> → Hỗ trợ **update CORE** (4 file) & **nạp LIB** (nhiều file) qua mô tả trong `manifest.json` đi kèm
