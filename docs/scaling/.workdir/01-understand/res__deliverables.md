Here is the dense research synthesis:

---

## Business Deliverables from a Constrained Python 3.9 Backend - State-of-the-Art (2025-2026)

---

### 1. PDF Generation - Template-Fill Approaches

**The core pattern: HTML Jinja2 template + Python fill + PDF renderer.** The model fills only named slots; the document structure is deterministic.

#### WeasyPrint (recommended for template-fill HTML-to-PDF)

- Pure-Python CSS3 renderer (Flexbox, grid, custom fonts, CSS Paged Media for headers/footers/page numbers). BSD 3-Clause. Python 3.6+.
- **Critical constraint:** requires system-level `pango`, `cairo`, and `gdk-pixbuf` libraries - these cannot be pip-installed. On a managed Dataiku instance, these native libs are not guaranteed to be present. Confirm with the instance admin before approving install.
- Pattern: `Jinja2.Template(...).render(**slots)` -> `WeasyPrint.HTML(string=rendered_html).write_pdf(buf)` -> stream as `application/pdf`.
- Images (charts) embedded as base64 data URIs in the HTML work out of the box without filesystem access.
- Docs: [https://doc.courtbouillon.org/weasyprint/stable/first_steps.html](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html)

#### ReportLab (best for code-driven, chart-heavy precise layouts)

- Pure Python, no system libs needed beyond pip. Handles text, images, charts natively via its `Flowables` and `Graphics` module. Permissive open-source license (BSD-like "ReportLab Open Source License") for the community edition.
- More verbose than WeasyPrint - you define layout in Python, not CSS. But zero external binary dependencies makes it the safest choice for a locked-down server.
- Best when: you need to assemble a report with pre-rendered chart PNGs (from matplotlib or client-side), tables, and text blocks in a predictable page layout.
- Docs: [https://www.reportlab.com/docs/reportlab-userguide.pdf](https://www.reportlab.com/docs/reportlab-userguide.pdf)

#### wkhtmltopdf / PDFKit

- **Avoid for new work.** wkhtmltopdf was archived in January 2023. No security fixes. [https://pdfbolt.com/blog/python-html-to-pdf-library](https://pdfbolt.com/blog/python-html-to-pdf-library)

#### Playwright / headless Chromium

- Pixel-perfect browser rendering. Apache licensed. But requires a ~150 MB Chromium binary - almost certainly blocked on a Dataiku managed instance. Overkill for template-fill reports. Only viable if Dataiku already has a Chromium sidecar (DSS graphics export uses this path for dashboard PDF export: [https://doc.dataiku.com/dss/latest/installation/custom/graphics-export.html](https://doc.dataiku.com/dss/latest/installation/custom/graphics-export.html)).

#### docxtpl + python-docx (Word-first pipeline)

- Create a `.docx` template in Word, insert `{{ slot }}` / `{%tr ... %}` Jinja2 tags, fill programmatically. No system dependencies beyond pip. Python 3.6+.
- **Limitation:** output is `.docx`, not PDF. Converting docx to PDF server-side without LibreOffice or a binary is hard. Only viable if users accept .docx download, or if LibreOffice is present on the Dataiku server.
- Docs: [https://docxtpl.readthedocs.io/](https://docxtpl.readthedocs.io/)

#### Dataiku's own PDF export

DSS can export dashboards to PDF/PNG via a headless browser sidecar, but this is an admin-configured feature for DSS-native dashboards, not callable from a plugin WebApp backend. Not usable here. [https://doc.dataiku.com/dss/latest/dashboards/exports.html](https://doc.dataiku.com/dss/latest/dashboards/exports.html)

**Recommendation for OWIsMind:**
- **Primary path:** ReportLab (zero system deps, already pip-installable if user approves). Pre-render chart PNGs server-side with matplotlib (see below), assemble with ReportLab Flowables. Template = a Python dict of named regions; model fills text slots only.
- **Secondary path (better visual):** WeasyPrint + Jinja2 HTML template, but only after confirming pango/cairo are present on the Dataiku instance.

---

### 2. Chart Image Export - "Download the Chart I See as PNG"

#### Client-side (zero server dependency - the right default)

Chart.js exposes `chart.toBase64Image()` which returns a `data:image/png;base64,...` URI synchronously after render. Pattern:

```js
const url = chartInstance.toBase64Image(); // or canvas.toDataURL('image/png')
const a = document.createElement('a');
a.href = url; a.download = 'chart.png'; a.click();
```

This is free, instant, requires no server round-trip, and works with the Chart.js already bundled in OWIsMind. The PNG exactly matches what the user sees (colors, theme, size). Call it from `onAnimationComplete` to avoid blank outputs.
- Official docs: [https://www.chartjs.org/docs/latest/developers/api.html](https://www.chartjs.org/docs/latest/developers/api.html)
- Export guide: [https://quickchart.io/documentation/chart-js/image-export/](https://quickchart.io/documentation/chart-js/image-export/)

For embedding a chart PNG in a server-side PDF: the frontend must POST the base64 PNG to the backend (or the backend re-generates the same chart with matplotlib).

#### Server-side chart rendering for PDF embedding

**matplotlib** (`import matplotlib; matplotlib.use('Agg')` before any pyplot import - mandatory on headless servers):

```python
from io import BytesIO
import base64, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

fig, ax = plt.subplots()
ax.bar(labels, values)
buf = BytesIO()
fig.savefig(buf, format='png')
png_b64 = base64.b64encode(buf.getvalue()).decode()
```

matplotlib is already present in most Dataiku Python environments. No display server needed when using the `Agg` backend. This is the safest server-side path.
- Flask/server guide: [https://matplotlib.org/stable/gallery/user_interfaces/web_application_server_sgskip.html](https://matplotlib.org/stable/gallery/user_interfaces/web_application_server_sgskip.html)

**QuickChart** (external API or self-hosted): Accepts a Chart.js config JSON, returns a PNG. Python client lib available. AGPL-3.0 (self-hosted). Usable as an external call if internet access is allowed from the Dataiku backend - but adds a network dependency and raises data-exfiltration concerns for revenue data. Not recommended for sensitive data unless self-hosted.
- [https://quickchart.io/](https://quickchart.io/) | [https://github.com/typpo/quickchart](https://github.com/typpo/quickchart)

**Recommendation for OWIsMind:** Use `chart.toBase64Image()` client-side for direct PNG downloads (one button per chart, no server call). For server-side PDF assembly, re-render with matplotlib `Agg` backend using the same data already held in the backend (`generated_sql[].result`). This avoids any new binary dependencies.

---

### 3. Email Draft Generation

The pattern used by analytics products (ThoughtSpot, Sigma, Qlik) in 2024-2026: the model fills named slots in a fixed email template (subject, greeting, insight paragraph, data table, signature), never free-forms the full body.

Concrete structure:
1. **Template (stored in i18n/config):** `Subject: Revenue update for {{ client_name }} - {{ period }}`. Body: fixed sections with `{{ slots }}` for model-filled text.
2. **Model call:** constrained prompt - "fill only these slots: summary sentence (max 2 sentences), key finding (one bullet per metric), action recommendation". Output = structured JSON (with `with_json_output`), not free prose.
3. **Delivery:** backend returns `{subject, body_html, body_text, attachments: [{name, content_type, data_b64}]}`. The UI renders a preview modal ("Draft email") with a "Copy" / "Open in mail client" button (using `mailto:` URI for simple cases, or a SMTP call for enterprise).

Attachments: include the chart PNG (from client-side `toBase64Image()` posted back) and/or the PDF report as base64 blobs. The `mailto:` approach cannot attach files - for true attachments, a backend SMTP relay is needed (smtplib, standard library, no new install).

**Pattern for OWIsMind:** surface as an "Export" button in the Evidence panel. The orchestrator already has the analysis text and the SQL result. One constrained LLM call fills the email template slots. Return the draft to the frontend for user review before any send.

---

### 4. XLSX / CSV Export

**CSV:** zero dependencies. `import csv; io.StringIO()` -> stream as `text/csv`. Always available.

**XLSX:**
- `openpyxl` (MIT, pip): read/write `.xlsx`. Multi-sheet, cell formatting, charts (via openpyxl chart objects). Already present in many Dataiku envs.
- `xlsxwriter` (BSD 2-Clause, pip): write-only but more feature-rich (conditional formatting, sparklines). [https://xlsxwriter.readthedocs.io/](https://xlsxwriter.readthedocs.io/)
- `xlsxtpl` (pip): Jinja2 template fill for `.xlsx` - apply headers/formulas from a template sheet, fill data rows. Niche but useful for formatted reports with pre-built Excel formatting.
- Pattern: `io.BytesIO()` -> write workbook -> `seek(0)` -> stream as `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.

**Recommendation:** CSV first (no approval needed, always works). XLSX via `openpyxl` if the user approves the install; check if it is already present in the Dataiku Python 3.9 env before requesting.

---

### 5. Pragmatic Recommendations for OWIsMind

| Feature | Approach | Install needed? | Notes |
|---|---|---|---|
| PNG download (current chart) | `chart.toBase64Image()` client-side | None | Trivial; add "Download PNG" button per chart |
| XLSX export | `openpyxl` (check if present first) | Maybe | Likely already in Dataiku env |
| CSV export | stdlib `csv` + `io.StringIO` | None | Always ship this first |
| PDF report | ReportLab (pure Python) | Yes (pip only) | Zero system deps; user must approve |
| PDF (better CSS) | WeasyPrint + Jinja2 HTML template | Yes (pip + system pango/cairo) | Confirm system libs exist on instance |
| Chart PNG for PDF | matplotlib `Agg` | Check if present | Standard in Dataiku sci envs |
| Email draft | Model fills JSON slots, smtplib sends | None | smtplib is stdlib |

**Template discipline:** the model never generates document structure. It fills a pre-approved slot set (`{summary, key_metric_1, key_metric_2, recommendation, period, client_name}`). The template is versioned in the plugin, not generated at runtime. This is the core safety property: the PDF structure is deterministic, only the text/number slots vary.

**Sequencing without new installs:**
1. Ship CSV and client-side PNG download immediately - zero new installs.
2. Check existing Dataiku Python 3.9 env for `openpyxl`, `matplotlib`, `reportlab` (`pip list` in a notebook) - likely some are present.
3. If ReportLab is present: enable PDF. If matplotlib is present: server-side chart PNGs for PDF embedding.
4. Request WeasyPrint only if the visual quality of HTML-templated PDFs justifies the sysadmin overhead (pango/cairo).

---

**Key sources:**
- [Nutrient: Top 10 Python PDF generation (2026)](https://www.nutrient.io/blog/top-10-ways-to-generate-pdfs-in-python/)
- [WeasyPrint First Steps](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html)
- [docxtpl docs](https://docxtpl.readthedocs.io/)
- [Chart.js API (toBase64Image)](https://www.chartjs.org/docs/latest/developers/api.html)
- [QuickChart image export guide](https://quickchart.io/documentation/chart-js/image-export/)
- [QuickChart GitHub (AGPL)](https://github.com/typpo/quickchart)
- [matplotlib Flask/server headless guide](https://matplotlib.org/stable/gallery/user_interfaces/web_application_server_sgskip.html)
- [XlsxWriter docs](https://xlsxwriter.readthedocs.io/)
- [openpyxl PyPI](https://pypi.org/project/openpyxl/)
- [Dataiku DSS PDF export (admin graphics)](https://doc.dataiku.com/dss/latest/installation/custom/graphics-export.html)
- [Dataiku DSS dashboard exports](https://doc.dataiku.com/dss/latest/dashboards/exports.html)
- [LlamaIndex: LLM report generation patterns](https://www.llamaindex.ai/blog/building-blocks-of-llm-report-generation-beyond-basic-rag)