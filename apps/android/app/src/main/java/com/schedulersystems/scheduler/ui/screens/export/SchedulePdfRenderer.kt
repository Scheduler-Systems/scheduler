package com.schedulersystems.scheduler.ui.screens.export

import android.content.Context
import android.graphics.Color
import android.graphics.Paint
import android.graphics.pdf.PdfDocument
import android.graphics.pdf.PdfRenderer
import android.os.ParcelFileDescriptor
import com.schedulersystems.scheduler.domain.export.SchedulePdfDoc
import java.io.File

/**
 * Result of rendering a [SchedulePdfDoc] to a file: the file plus the page count
 * read back from the actual written PDF (proof it is a valid, non-empty document
 * rather than trusting our own pagination loop).
 */
data class RenderedPdf(val file: File, val pageCount: Int)

/**
 * Renders a [SchedulePdfDoc] to an A4 PDF using android.graphics.pdf.PdfDocument —
 * a real, on-device PDF (no stub, no external service). Lives in the UI layer
 * because it depends on android.graphics; the pure row/title/filename logic is in
 * domain/export/SchedulePdf.kt and is unit-tested separately.
 */
object SchedulePdfRenderer {
    private const val PAGE_W = 595 // A4 @72dpi, points
    private const val PAGE_H = 842
    private const val MARGIN = 40f
    private const val ROW_H = 22f

    fun render(context: Context, doc: SchedulePdfDoc): RenderedPdf {
        val pdf = PdfDocument()
        val titlePaint = Paint().apply { color = Color.BLACK; textSize = 16f; isFakeBoldText = true }
        val headerPaint = Paint().apply { color = Color.rgb(168, 85, 247); textSize = 11f; isFakeBoldText = true }
        val bodyPaint = Paint().apply { color = Color.BLACK; textSize = 10f }
        val footerPaint = Paint().apply { color = Color.GRAY; textSize = 8f }

        val colX = floatArrayOf(MARGIN, MARGIN + 110f, MARGIN + 220f)
        val rowsPerPage = ((PAGE_H - 130) / ROW_H).toInt()
        // Always at least one page, even when the roster is empty.
        val chunks = if (doc.rows.isEmpty()) listOf(emptyList()) else doc.rows.chunked(rowsPerPage)

        chunks.forEachIndexed { pageIdx, chunk ->
            val info = PdfDocument.PageInfo.Builder(PAGE_W, PAGE_H, pageIdx + 1).create()
            val page = pdf.startPage(info)
            val canvas = page.canvas
            var y = 50f
            if (pageIdx == 0) {
                canvas.drawText(doc.title, MARGIN, y, titlePaint)
                y += 30f
            }
            SchedulePdfDoc.HEADER.forEachIndexed { i, h -> canvas.drawText(h, colX[i], y, headerPaint) }
            y += ROW_H
            chunk.forEach { r ->
                canvas.drawText(r.shift, colX[0], y, bodyPaint)
                canvas.drawText(r.day, colX[1], y, bodyPaint)
                canvas.drawText(r.employee, colX[2], y, bodyPaint)
                y += ROW_H
            }
            canvas.drawText("Page ${pageIdx + 1} of ${chunks.size}", PAGE_W - 110f, PAGE_H - 20f, footerPaint)
            pdf.finishPage(page)
        }

        val file = File(context.cacheDir, doc.filename)
        file.outputStream().use { pdf.writeTo(it) }
        pdf.close()

        // Reopen the written file and count pages from the real bytes.
        val pageCount = ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY).use { pfd ->
            PdfRenderer(pfd).use { it.pageCount }
        }
        return RenderedPdf(file, pageCount)
    }
}
