import { ImageResponse } from "next/og";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

/**
 * Ảnh xem trước khi dán link (Zalo, Messenger, LinkedIn, Slack, X…).
 *
 * Sinh tại thời điểm build thay vì lưu một file PNG tĩnh: đổi câu chữ chỉ cần
 * sửa ở đây, không phải mở phần mềm ảnh. Hai họ chữ được nhúng kèm repo vì
 * trình render chạy phía máy chủ, không dùng được font tải qua CSS của trình
 * duyệt — và font hệ thống sẽ phá vỡ hợp đồng typography của sản phẩm.
 */
export const alt = "LitReview — Bàn nghiên cứu dựa trên bằng chứng";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const INK = "#172238";
const PAPER = "#f4f1ea";
const CORAL = "#d04f35";
const RULE = "rgba(244,241,234,.22)";

export default async function OpengraphImage() {
  const dir = join(process.cwd(), "app", "_og");
  const [serif, mono] = await Promise.all([
    readFile(join(dir, "SourceSerif4-SemiBold.woff")),
    readFile(join(dir, "IBMPlexMono-Medium.woff")),
  ]);

  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column",
                    background: INK, color: PAPER, fontFamily: "Serif", padding: 72 }}>
        {/* Thanh nhận diện: con dấu chữ L, giống hệt đầu trang web */}
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          {/* Cùng polygon với .v2-mark trên web, nên con dấu ở ảnh xem trước và
              con dấu ở đầu trang là một. */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center",
                        width: 64, height: 74, background: CORAL, color: "#fff",
                        clipPath: "polygon(0 0, 77% 0, 100% 22%, 100% 100%, 0 100%)",
                        fontFamily: "Serif", fontSize: 40, lineHeight: 1 }}>L</div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span style={{ fontSize: 30, letterSpacing: "-0.02em" }}>LitReview</span>
            <span style={{ fontFamily: "Mono", fontSize: 15, letterSpacing: "0.14em",
                           color: "#9aa6bd", textTransform: "uppercase", marginTop: 6 }}>
              Research Desk
            </span>
          </div>
        </div>

        <div style={{ display: "flex", flex: 1, alignItems: "center" }}>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 74, lineHeight: 1.06, letterSpacing: "-0.04em", maxWidth: 900 }}>
              Mọi kết luận đều truy được
            </div>
            <div style={{ fontSize: 74, lineHeight: 1.06, letterSpacing: "-0.04em", color: CORAL }}>
              về đúng bài báo gốc.
            </div>
          </div>
        </div>

        {/* Ba con số lấy từ lượt benchmark thật, không phải số minh hoạ */}
        <div style={{ display: "flex", borderTop: `1px solid ${RULE}`, paddingTop: 26, gap: 64 }}>
          {[
            ["0%", "Trích dẫn bịa"],
            ["100%", "Khớp nguyên văn"],
            ["215", "Trích dẫn đã kiểm"],
          ].map(([value, label]) => (
            <div key={label} style={{ display: "flex", flexDirection: "column" }}>
              <span style={{ fontSize: 40, lineHeight: 1 }}>{value}</span>
              <span style={{ fontFamily: "Mono", fontSize: 14, letterSpacing: "0.1em",
                             color: "#9aa6bd", textTransform: "uppercase", marginTop: 8 }}>
                {label}
              </span>
            </div>
          ))}
        </div>
      </div>
    ),
    {
      ...size,
      fonts: [
        { name: "Serif", data: serif, style: "normal", weight: 600 },
        { name: "Mono", data: mono, style: "normal", weight: 500 },
      ],
    },
  );
}
