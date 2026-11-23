const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");
const { selectTheme } = require("./theme_agent");

const rootDir = path.resolve(__dirname, "..");
const defaultLayoutPath = path.join(rootDir, "layout_samples", "dimension_detail.json");
const defaultOutputDir = path.join(rootDir, "output");

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function colorToken(theme, key) {
  return theme.colors[key] || key;
}

function buildHorizontalBarChart(chart, theme) {
  const width = 720;
  const height = 270;
  const left = 78;
  const right = 52;
  const top = 24;
  const rowGap = 40;
  const barHeight = 14;
  const axisWidth = width - left - right;
  const max = chart.x_max || 100;
  const rows = chart.series || [];
  const gridLines = 6;
  const colors = theme.colors;

  const grid = Array.from({ length: gridLines + 1 }, (_, index) => {
    const x = left + (axisWidth * index) / gridLines;
    const value = Math.round((max * index) / gridLines);
    return `
      <line x1="${x}" y1="${top - 4}" x2="${x}" y2="${height - 36}" stroke="${colors.line}" stroke-width="1" />
      <text x="${x}" y="${height - 12}" text-anchor="middle" font-size="12" fill="${colors.muted}">${value}</text>
    `;
  }).join("");

  const bars = rows.map((item, index) => {
    const y = top + index * rowGap;
    const refWidth = Math.max(0, Math.min(axisWidth, (axisWidth * item.reference) / max));
    const scoreWidth = Math.max(0, Math.min(axisWidth, (axisWidth * item.score) / max));
    const scoreColor = item.highlight ? colors.primary : colors.green_dark;
    return `
      <text x="${left - 12}" y="${y + 13}" text-anchor="end" font-size="15" fill="${colors.muted}">${escapeHtml(item.label)}</text>
      <rect x="${left}" y="${y}" width="${refWidth}" height="${barHeight}" fill="${colors.green}" opacity="0.9" />
      <rect x="${left}" y="${y + barHeight + 4}" width="${scoreWidth}" height="${barHeight}" fill="${scoreColor}" />
      <text x="${left + refWidth + 10}" y="${y + 12}" font-size="13" fill="${colors.body}">${escapeHtml(item.reference)}</text>
      <text x="${left + scoreWidth + 10}" y="${y + barHeight + 16}" font-size="13" fill="${colors.body}">${escapeHtml(item.score)}</text>
    `;
  }).join("");

  const legend = (chart.legend || []).map((item, index) => {
    const x = width / 2 - 64 + index * 112;
    return `
      <rect x="${x}" y="${height - 2}" width="10" height="10" fill="${colorToken(theme, item.color)}" />
      <text x="${x + 16}" y="${height + 8}" font-size="12" fill="${colors.muted}">${escapeHtml(item.label)}</text>
    `;
  }).join("");

  return `
    <figure class="chart-card" aria-label="${escapeHtml(chart.title || "")}">
      <figcaption>${escapeHtml(chart.title || "")}</figcaption>
      <svg viewBox="0 0 ${width} ${height + 18}" role="img">
        ${grid}
        ${bars}
        ${legend}
      </svg>
    </figure>
  `;
}

function buildTextBlocks(blocks) {
  return (blocks || []).map((block) => `
    <section class="text-block text-block-${escapeHtml(block.type || "default")}">
      <div class="diamond"></div>
      <div>
        <h3>${escapeHtml(block.title)}</h3>
        <p>${escapeHtml(block.body)}</p>
      </div>
    </section>
  `).join("");
}

function formatBadgeText(text) {
  const [prefix, ...rest] = String(text).split("\uFF1A");
  if (!rest.length) return escapeHtml(text);
  return `<strong>${escapeHtml(prefix)}：</strong>${escapeHtml(rest.join("\uFF1A"))}`;
}

function buildHtml(layout, theme) {
  const page = layout.page || {};
  const typography = theme.typography;
  const colors = theme.colors;
  const chartHtml = buildHorizontalBarChart(layout.chart || {}, theme);
  const textBlocks = buildTextBlocks(layout.text_blocks || []);

  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${escapeHtml(layout.document_title || page.title || "Report")}</title>
  <style>
    @page { size: A4; margin: 0; }
    * { box-sizing: border-box; }
    html, body {
      margin: 0;
      padding: 0;
      background: #e9e9e9;
      color: ${colors.body};
      font-family: ${typography.font_family};
    }
    body {
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }
    .page {
      position: relative;
      width: ${theme.page.width_mm}mm;
      height: ${theme.page.height_mm}mm;
      margin: 0 auto;
      background: ${colors.paper};
      overflow: hidden;
    }
    .content {
      position: absolute;
      left: ${theme.page.margin_left_mm}mm;
      right: ${theme.page.margin_right_mm}mm;
      top: ${theme.page.margin_top_mm}mm;
      bottom: ${theme.page.margin_bottom_mm + 6}mm;
    }
    .title {
      margin: 0;
      color: ${colors.ink};
      font-size: ${typography.title_px}px;
      line-height: 1.05;
      font-weight: 900;
      letter-spacing: 0;
    }
    .subtitle {
      margin-top: 5px;
      color: ${colors.primary_dark};
      font-size: ${typography.subtitle_px}px;
      line-height: 1.1;
      font-weight: 500;
      letter-spacing: 2px;
      text-transform: uppercase;
    }
    .badge-row {
      display: flex;
      align-items: flex-start;
      gap: 12px;
      margin-top: 24px;
      font-size: ${typography.body_px}px;
      line-height: ${typography.line_height};
    }
    .badge-mark {
      flex: 0 0 auto;
      width: 54px;
      height: 54px;
      border-radius: 50%;
      background: ${colors.soft_yellow};
      margin-top: -6px;
    }
    .badge-text { padding-top: 6px; }
    .badge-text strong {
      font-weight: 800;
      color: ${colors.ink};
    }
    .chart-card {
      margin: 22px 0 22px;
      padding: 0;
    }
    .chart-card figcaption { display: none; }
    .chart-card svg {
      display: block;
      width: 100%;
      height: 260px;
    }
    .text-block {
      display: grid;
      grid-template-columns: 18px 1fr;
      column-gap: 8px;
      margin-top: 18px;
      break-inside: avoid;
    }
    .diamond {
      width: 14px;
      height: 14px;
      margin-top: 8px;
      background: ${colors.primary};
      transform: rotate(45deg);
    }
    .text-block h3 {
      margin: 0 0 3px;
      color: ${colors.primary_dark};
      font-size: 17px;
      line-height: 1.35;
      font-weight: 900;
    }
    .text-block p {
      margin: 0;
      font-size: ${typography.body_px}px;
      line-height: ${typography.line_height};
      font-weight: 500;
      color: ${colors.body};
    }
    .bottom-band {
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      height: 10mm;
      background: ${colors.primary};
    }
  </style>
</head>
<body>
  <article class="page">
    <main class="content">
      <h1 class="title">${escapeHtml(page.title || "")}</h1>
      <div class="subtitle">${escapeHtml(page.subtitle || "")}</div>
      <section class="badge-row">
        <div class="badge-mark"></div>
        <div class="badge-text">${formatBadgeText(page.section_badge || "")}</div>
      </section>
      ${chartHtml}
      <section class="text-blocks">${textBlocks}</section>
    </main>
    <div class="bottom-band"></div>
  </article>
</body>
</html>`;
}

async function render() {
  const layoutPath = path.resolve(process.argv[2] || defaultLayoutPath);
  const outputDir = path.resolve(process.argv[3] || defaultOutputDir);
  const explicitThemeName = process.argv[4];
  fs.mkdirSync(outputDir, { recursive: true });

  const layout = readJson(layoutPath);
  const theme = selectTheme(layout, explicitThemeName);
  const html = buildHtml(layout, theme);
  const baseName = `${path.basename(layoutPath, ".json")}_${theme.name}`;

  const htmlPath = path.join(outputDir, `${baseName}.html`);
  const pdfPath = path.join(outputDir, `${baseName}.pdf`);
  const pngPath = path.join(outputDir, `${baseName}.png`);
  fs.writeFileSync(htmlPath, html, "utf8");

  const browser = await chromium.launch();
  const page = await browser.newPage({
    viewport: { width: 794, height: 1123 },
    deviceScaleFactor: 1,
  });
  await page.setContent(html, { waitUntil: "networkidle" });
  await page.emulateMedia({ media: "print" });

  const overflow = await page.evaluate(() => {
    const content = document.querySelector(".content");
    const pageEl = document.querySelector(".page");
    return {
      contentScrollHeight: content.scrollHeight,
      contentClientHeight: content.clientHeight,
      pageScrollHeight: pageEl.scrollHeight,
      pageClientHeight: pageEl.clientHeight,
      hasContentOverflow: content.scrollHeight > content.clientHeight + 1,
    };
  });

  await page.pdf({
    path: pdfPath,
    format: "A4",
    printBackground: true,
    margin: { top: "0", right: "0", bottom: "0", left: "0" },
  });
  await page.screenshot({ path: pngPath, fullPage: true });
  await browser.close();

  console.log(JSON.stringify({
    selectedTheme: theme.name,
    reportType: layout.report_type || null,
    htmlPath,
    pdfPath,
    pngPath,
    overflow,
  }, null, 2));
}

render().catch((error) => {
  console.error(error);
  process.exit(1);
});
