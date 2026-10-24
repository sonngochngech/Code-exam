/* Hàm dùng chung cho mọi trang: gọi máy chủ, phiên đăng nhập, điều hướng,
   thông báo và hộp thoại. Mọi trang đều nạp file này trước tiên. */

// --------------------------------------------------------------- gọi máy chủ
const API = {
  async goi(duong_dan, phuong_thuc = "GET", du_lieu = null) {
    const tuy_chon = { method: phuong_thuc, headers: {} };
    if (du_lieu instanceof FormData) {
      tuy_chon.body = du_lieu;                 // trình duyệt tự đặt kiểu nội dung
    } else if (du_lieu !== null) {
      tuy_chon.headers["Content-Type"] = "application/json";
      tuy_chon.body = JSON.stringify(du_lieu);
    }
    // Gửi token phiên nếu đã đăng nhập, để máy chủ kiểm tra quyền.
    try {
      const nd = Phien.lay();
      if (nd && nd.token) tuy_chon.headers["Authorization"] = "Bearer " + nd.token;
    } catch (e) {}
    const r = await fetch(duong_dan, tuy_chon);
    // Hết phiên hoặc chưa đăng nhập: xóa phiên và đưa về trang chủ.
    if (r.status === 401) {
      Phien.xoa();
      if (location.pathname !== "/vao") location.href = "/vao";
      throw new Error("Phiên đã hết hạn, em đăng nhập lại nhé.");
    }
    if (!r.ok) {
      let thong_bao = `Máy chủ trả về lỗi ${r.status}`;
      try {
        const j = await r.json();
        if (j.detail) thong_bao = typeof j.detail === "string"
          ? j.detail : JSON.stringify(j.detail);
      } catch (e) {}
      const loi = new Error(thong_bao);
      loi.status = r.status;
      throw loi;
    }
    return r.status === 204 ? null : r.json();
  },
  get(d) { return this.goi(d); },
  post(d, x) { return this.goi(d, "POST", x); },
  put(d, x) { return this.goi(d, "PUT", x); },
  xoa(d) { return this.goi(d, "DELETE"); },
};

// ------------------------------------------------------------ phiên đăng nhập
// Lưu ngay trên máy người dùng. Mọi thao tác bọc try vì trình duyệt có thể
// chặn lưu trữ, ví dụ khi mở ở chế độ ẩn danh.
const Phien = {
  luu(nd) { try { localStorage.setItem("nguoi_dung", JSON.stringify(nd)); } catch (e) {} },
  lay() {
    try { return JSON.parse(localStorage.getItem("nguoi_dung") || "null"); }
    catch (e) { return null; }
  },
  xoa() { try { localStorage.removeItem("nguoi_dung"); } catch (e) {} },
  batBuoc() {
    const nd = this.lay();
    if (!nd) { location.href = "/vao"; return null; }
    return nd;
  },
  laGiaoVien() { const nd = this.lay(); return nd && nd.vai_tro === "giao_vien"; },
};

// -------------------------------------------------------------- biểu tượng
// Vẽ bằng SVG nét tròn thay vì dùng emoji, để đồng bộ với kiểu chữ tròn và
// để đổi màu theo từng hệ thống.
const BIEU_TUONG = {
  hoi: '<path d="M21 11.5a8.4 8.4 0 0 1-9 8.4L3 21l1.1-9A8.4 8.4 0 1 1 21 11.5Z"/>' +
       '<path d="M9 10h.01M12 10h.01M15 10h.01"/>',
  bai: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>' +
       '<path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"/>' +
       '<path d="M9 7h7M9 11h5"/>',
  bieu_do: '<path d="M3 3v16a2 2 0 0 0 2 2h16"/>' +
           '<rect x="7" y="11" width="3" height="6" rx="1"/>' +
           '<rect x="13" y="7" width="3" height="10" rx="1"/>',
  mat: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/>' +
       '<circle cx="12" cy="12" r="3"/>',
  banh_rang: '<circle cx="12" cy="12" r="3"/>' +
    '<path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 7 19.4a1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0-1.2-2.9H1a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 2.6 7a1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H7a1.7 1.7 0 0 0 1-1.5V1a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V7a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/>',
  sach: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V2H6.5A2.5 2.5 0 0 0 4 4.5v15Z"/>' +
        '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20v5H6.5A2.5 2.5 0 0 1 4 19.5Z"/>',
  hop_rong: '<path d="M3 7.5 12 3l9 4.5v9L12 21l-9-4.5v-9Z"/><path d="m3 7.5 9 4.5 9-4.5"/>' +
            '<path d="M12 12v9"/>',
  dong_ho: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  xong: '<circle cx="12" cy="12" r="9"/><path d="m8.5 12.5 2.5 2.5 4.5-5"/>',
  tiec: '<path d="m4 20 4.5-12L18 17.5 6 22a1.5 1.5 0 0 1-2-2Z"/>' +
        '<path d="M14 4.5 15 6M19 3l-1.5 2M21 9l-2-.5M17 12l1.5 1"/>',
  khoa: '<rect x="4" y="10" width="16" height="11" rx="2.5"/>' +
        '<path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
};

function icon(ten, lop = "") {
  const d = BIEU_TUONG[ten] || BIEU_TUONG.hop_rong;
  return `<svg class="${lop}" viewBox="0 0 24 24" aria-hidden="true">${d}</svg>`;
}

// ------------------------------------------------------------------ tiện ích
function tao(the, lop, chu) {
  const e = document.createElement(the);
  if (lop) e.className = lop;
  if (chu !== undefined) e.textContent = chu;
  return e;
}

function thoat(s) {
  return String(s ?? "").replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function dinhDangGiay(giay) {
  const p = Math.floor(giay / 60), s = Math.floor(giay % 60);
  return `${p}:${String(s).padStart(2, "0")}`;
}

function dinhDangNgay(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString("vi-VN", { day: "2-digit", month: "2-digit",
    hour: "2-digit", minute: "2-digit" });
}

// Lấy chữ cái cho ảnh đại diện. Tên người Việt thì tên riêng đứng cuối nên ưu
// tiên từ cuối, nhưng nếu từ cuối không bắt đầu bằng chữ cái (ví dụ "lớp 9A")
// thì lùi dần về đầu để khỏi hiện ra một chữ số.
function chuCaiDau(ten) {
  const tu = String(ten || "").trim().split(/\s+/).filter(Boolean);
  for (let i = tu.length - 1; i >= 0; i--) {
    const c = tu[i][0];
    if (/\p{L}/u.test(c)) return c.toUpperCase();
  }
  return "?";
}

// Cách xưng hô theo vai trò. Giáo viên mà bị gọi là "em" thì rất kỳ.
function xungHo() {
  return Phien.laGiaoVien() ? "thầy cô" : "em";
}

// ---------------------------------------------------------------- thông báo
function thongBao(chu, loai = "") {
  let khay = document.getElementById("khay-thong-bao");
  if (!khay) {
    khay = tao("div");
    khay.id = "khay-thong-bao";
    khay.setAttribute("role", "status");
    khay.setAttribute("aria-live", "polite");
    khay.setAttribute("aria-atomic", "true");
    document.body.appendChild(khay);
  }
  const o = tao("div", "thong-bao " + loai, chu);
  khay.appendChild(o);
  setTimeout(() => {
    o.style.transition = "opacity .25s, transform .25s";
    o.style.opacity = "0";
    o.style.transform = "translateX(24px)";
    setTimeout(() => o.remove(), 260);
  }, 3600);
}

// ----------------------------------------------------------------- hộp thoại
function hopThoai(tieu_de, noi_dung_html, cac_nut = []) {
  return new Promise(giai_quyet => {
    const phu = tao("div", "lop-phu");
    const the = tao("div", "the");
    const tieuDeId = "tieu-de-hop-thoai-" + Date.now();
    the.setAttribute("role", "dialog");
    the.setAttribute("aria-modal", "true");
    the.setAttribute("aria-labelledby", tieuDeId);
    the.innerHTML = `<h2 id="${tieuDeId}">${thoat(tieu_de)}</h2><div>${noi_dung_html}</div>`;
    const hang = tao("div", "hang cach");
    hang.style.justifyContent = "flex-end";

    const dong = (gt) => { phu.remove(); giai_quyet(gt); };
    (cac_nut.length ? cac_nut : [{ chu: "Đóng", gt: null }]).forEach(n => {
      const b = tao("button", n.lop || "phu", n.chu);
      b.onclick = () => dong(n.gt);
      hang.appendChild(b);
    });
    the.appendChild(hang);
    phu.appendChild(the);
    phu.onclick = e => { if (e.target === phu) dong(null); };
    document.addEventListener("keydown", function thoatPhim(e) {
      if (e.key === "Escape") { document.removeEventListener("keydown", thoatPhim); dong(null); }
    });
    document.body.appendChild(phu);
    hang.querySelector("button")?.focus();
  });
}

function xacNhan(chu, chuNut = "Đồng ý") {
  return hopThoai("Xác nhận", `<p class="mo">${thoat(chu)}</p>`, [
    { chu: "Hủy", gt: false },
    { chu: chuNut, gt: true, lop: "" },
  ]);
}

// ---------------------------------------------------------------- điều hướng
// Danh sách trang, lọc theo vai trò. Mỗi trang chỉ cần gọi dungKhung().
const TRANG = [
  { duong_dan: "/",                ten: "Tổng quan",         vai_tro: "ai", icon: "sach" },
  { duong_dan: "/tro-giang",       ten: "Hỏi bài",           vai_tro: "ai", icon: "hoi" },
  { duong_dan: "/lam-bai",         ten: "Bài kiểm tra",      vai_tro: "ai", icon: "bai" },
  { duong_dan: "/thong-tin",       ten: "Quy định giám sát", vai_tro: "ai", icon: "khoa" },
  { duong_dan: "/bang-dieu-khien", ten: "Tiến độ lớp",       vai_tro: "giao_vien", icon: "bieu_do" },
  { duong_dan: "/coi-thi",         ten: "Coi thi",           vai_tro: "giao_vien", icon: "mat" },
  { duong_dan: "/quan-tri",        ten: "Quản lý nội dung",  vai_tro: "giao_vien", icon: "banh_rang" },
];

// Chọn biểu tượng cho thanh tiêu đề theo trang đang mở, để mỗi trang có logo
// riêng mà vẫn đồng bộ với trang giới thiệu.
const ICON_THEO_TRANG = {
  "/tro-giang": "hoi",
  "/lam-bai": "bai",
  "/bang-dieu-khien": "bieu_do",
  "/coi-thi": "mat",
  "/quan-tri": "banh_rang",
  "/thong-tin": "sach",
};
function iconTheoTrang() {
  return ICON_THEO_TRANG[location.pathname] || "sach";
}

function dungKhung(tieu_de, phu_de) {
  const nd = Phien.lay();

  document.body.classList.toggle("co-lms", Boolean(nd));

  let header = document.querySelector("header.dinh");
  if (!header) {
    header = tao("header", "dinh");
    header.appendChild(tao("div", "trong"));
    document.body.insertBefore(header, document.body.firstChild);
  }
  const trong = header.querySelector(".trong");
  trong.innerHTML = "";

  const trai = tao("div");
  trai.style.cssText = "display:flex;align-items:center;gap:12px;min-width:0";
  const logo = tao("span", "logo-dau");
  logo.innerHTML = icon(iconTheoTrang());
  trai.appendChild(logo);
  const khoiChu = tao("div");
  khoiChu.style.minWidth = "0";
  const h = tao("h1", null, tieu_de);
  if (phu_de) {
    const s = tao("span", "phu", phu_de);
    h.appendChild(s);
  }
  khoiChu.appendChild(h);
  trai.appendChild(khoiChu);
  trong.appendChild(trai);

  const phai = tao("div");
  phai.style.cssText = "display:flex;gap:10px;align-items:center";
  if (nd) {
    const o = tao("div", "nguoi");
    const av = tao("div", "anh-dai-dien", chuCaiDau(nd.ho_ten));
    o.appendChild(av);
    const ten = tao("span", null, nd.ho_ten);
    ten.style.cssText = "max-width:210px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
    o.appendChild(ten);
    phai.appendChild(o);
    const ra = tao("a", null, "Thoát");
    ra.href = "#";
    ra.onclick = e => { e.preventDefault(); Phien.xoa(); location.href = "/"; };
    phai.appendChild(ra);
  } else {
    const ve = tao("a", null, "Trang chủ");
    ve.href = "/";
    phai.appendChild(ve);
  }
  trong.appendChild(phai);

  // Điều hướng LMS theo vai trò: thanh bên trên màn hình rộng, thanh cuộn
  // ngang trên thiết bị nhỏ.
  document.querySelector(".tab-phu")?.remove();
  if (nd) {
    const tab = tao("nav", "tab-phu");
    tab.setAttribute("aria-label", "Điều hướng chính");
    const t = tao("div", "trong");
    const nhan = tao("div", "nhan-dieu-huong");
    nhan.innerHTML = `<span class="logo-lms">${icon("sach")}</span><span>Không gian học tập</span>`;
    t.appendChild(nhan);
    TRANG.filter(x => x.vai_tro === "ai" || nd.vai_tro === x.vai_tro).forEach(x => {
      const a = tao("a", location.pathname === x.duong_dan ? "dang-o" : "", x.ten);
      a.href = x.duong_dan;
      a.innerHTML = `${icon(x.icon)}<span>${thoat(x.ten)}</span>`;
      if (location.pathname === x.duong_dan) a.setAttribute("aria-current", "page");
      t.appendChild(a);
    });
    const vaiTro = tao("div", "vai-tro-lms", nd.vai_tro === "giao_vien" ? "Không gian giáo viên" : "Không gian học sinh");
    t.appendChild(vaiTro);
    tab.appendChild(t);
    header.insertAdjacentElement("afterend", tab);
  }
}

// Chặn trang dành riêng cho giáo viên.
function chiGiaoVien() {
  const nd = Phien.batBuoc();
  if (!nd) return null;
  if (nd.vai_tro !== "giao_vien") {
    document.querySelector(".khung").innerHTML =
      '<div class="the trong-rong"><div class="hinh">' + icon("khoa") + '</div>' +
      "<h2>Trang này dành cho giáo viên</h2>" +
      '<p class="mo">Em quay lại trang chủ để vào phần của mình nhé.</p>' +
      '<a class="nut" href="/">Về trang chủ</a></div>';
    return null;
  }
  return nd;
}

function khungXuong(so_dong = 3) {
  return '<div class="khung-xuong">' +
    Array.from({ length: so_dong }, (_, i) =>
      `<i style="width:${[100, 82, 64][i % 3]}%"></i>`).join("") + "</div>";
}

function trongRong(ten_icon, tieu_de, mo_ta) {
  return `<div class="trong-rong"><div class="hinh">${icon(ten_icon)}</div>
    <h3 style="margin:0 0 6px">${thoat(tieu_de)}</h3>
    <p class="mo" style="margin:0">${thoat(mo_ta)}</p></div>`;
}

// Tải tệp từ endpoint cần đăng nhập. Không dùng thẻ a trỏ thẳng vì điều hướng
// trình duyệt không gửi được token; phải tải bằng fetch rồi lưu blob.
async function taiFile(url, tenGoiY) {
  try {
    const nd = Phien.lay();
    const r = await fetch(url, {
      headers: nd && nd.token ? { Authorization: "Bearer " + nd.token } : {},
    });
    if (r.status === 401) { Phien.xoa(); location.href = "/vao"; return; }
    if (!r.ok) throw new Error("Không tải được tệp (" + r.status + ")");
    const blob = await r.blob();
    let ten = tenGoiY || "du-lieu.csv";
    const cd = r.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename="?([^"]+)"?/);
    if (m) ten = m[1];
    const a = tao("a");
    a.href = URL.createObjectURL(blob);
    a.download = ten;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  } catch (e) { thongBao(e.message, "loi"); }
}

// Dựng công thức toán trong một phần tử bằng KaTeX, nếu thư viện đã nạp.
// Văn bản thường đặt bằng textContent trước, KaTeX chỉ thay phần giữa $...$,
// nên vẫn an toàn trước chèn mã. Lỗi thì giữ nguyên chữ, không vỡ giao diện.
function veCongThuc(el) {
  try {
    if (el && window.renderMathInElement) {
      renderMathInElement(el, {
        delimiters: [
          { left: "$$", right: "$$", display: true },
          { left: "$", right: "$", display: false },
          { left: "\\[", right: "\\]", display: true },
          { left: "\\(", right: "\\)", display: false },
        ],
        throwOnError: false,
      });
    }
  } catch (e) {}
}

// Đặt màu nhấn theo hệ thống: 1 là trợ giảng, 2 là kỳ thi.
function datHeThong(so) {
  document.body.dataset.heThong = String(so);
}
