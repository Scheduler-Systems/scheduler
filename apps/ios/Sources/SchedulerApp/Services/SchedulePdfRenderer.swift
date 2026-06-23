import UIKit

/// Result of rendering a SchedulePdfDoc: the written file URL plus the page count
/// read back from the real rendered bytes (proof it is a valid, non-empty PDF).
struct RenderedSchedulePdf {
    let url: URL
    let pageCount: Int
}

/// Renders a SchedulePdfDoc to an A4 PDF using UIGraphicsPDFRenderer — a real,
/// on-device PDF (no stub, no external service). Mirrors the Android
/// SchedulePdfRenderer; the pure row/title/filename logic lives in SchedulePdf.swift
/// and is unit-tested separately.
enum SchedulePdfRenderer {
    private static let pageWidth: CGFloat = 595 // A4 @72dpi, points
    private static let pageHeight: CGFloat = 842
    private static let margin: CGFloat = 40
    private static let rowHeight: CGFloat = 22

    static func render(_ doc: SchedulePdfDoc) -> RenderedSchedulePdf {
        let pageRect = CGRect(x: 0, y: 0, width: pageWidth, height: pageHeight)
        let renderer = UIGraphicsPDFRenderer(bounds: pageRect)

        let rowsPerPage = max(1, Int((pageHeight - 130) / rowHeight))
        let chunks: [[SchedulePdfRow]] = doc.rows.isEmpty
            ? [[]]
            : stride(from: 0, to: doc.rows.count, by: rowsPerPage).map {
                Array(doc.rows[$0..<min($0 + rowsPerPage, doc.rows.count)])
            }

        let colX: [CGFloat] = [margin, margin + 110, margin + 220]
        let titleAttr: [NSAttributedString.Key: Any] = [.font: UIFont.boldSystemFont(ofSize: 16)]
        let headerAttr: [NSAttributedString.Key: Any] = [
            .font: UIFont.boldSystemFont(ofSize: 11),
            .foregroundColor: UIColor(red: 168 / 255, green: 85 / 255, blue: 247 / 255, alpha: 1)
        ]
        let bodyAttr: [NSAttributedString.Key: Any] = [.font: UIFont.systemFont(ofSize: 10)]
        let footerAttr: [NSAttributedString.Key: Any] = [
            .font: UIFont.systemFont(ofSize: 8), .foregroundColor: UIColor.gray
        ]

        let data = renderer.pdfData { ctx in
            for (pageIdx, chunk) in chunks.enumerated() {
                ctx.beginPage()
                var y: CGFloat = 50
                if pageIdx == 0 {
                    (doc.title as NSString).draw(at: CGPoint(x: margin, y: y), withAttributes: titleAttr)
                    y += 30
                }
                for (i, header) in SchedulePdfDoc.header.enumerated() {
                    (header as NSString).draw(at: CGPoint(x: colX[i], y: y), withAttributes: headerAttr)
                }
                y += rowHeight
                for row in chunk {
                    (row.shift as NSString).draw(at: CGPoint(x: colX[0], y: y), withAttributes: bodyAttr)
                    (row.day as NSString).draw(at: CGPoint(x: colX[1], y: y), withAttributes: bodyAttr)
                    (row.employee as NSString).draw(at: CGPoint(x: colX[2], y: y), withAttributes: bodyAttr)
                    y += rowHeight
                }
                let footer = "Page \(pageIdx + 1) of \(chunks.count)"
                (footer as NSString).draw(at: CGPoint(x: pageWidth - 110, y: pageHeight - 30), withAttributes: footerAttr)
            }
        }

        let url = FileManager.default.temporaryDirectory.appendingPathComponent(doc.filename)
        try? data.write(to: url)

        let pageCount: Int = {
            guard let provider = CGDataProvider(data: data as CFData),
                  let pdf = CGPDFDocument(provider) else { return 0 }
            return pdf.numberOfPages
        }()

        return RenderedSchedulePdf(url: url, pageCount: pageCount)
    }
}
