const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const outputDir = path.join(root, "output", "report_app_ui_checks");
const baseUrl = process.env.REPORT_APP_URL || "http://127.0.0.1:8765";

const viewports = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "tablet", width: 900, height: 900 },
  { name: "mobile", width: 390, height: 844 },
];

async function main() {
  fs.mkdirSync(outputDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const results = [];
  try {
    for (const viewport of viewports) {
      const page = await browser.newPage({ viewport });
      const consoleErrors = [];
      page.on("console", (message) => {
        if (message.type() === "error") consoleErrors.push(message.text());
      });
      await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
      await page.waitForFunction(
        () => document.querySelector("#service-state")?.classList.contains("online"),
        null,
        { timeout: 5000 },
      );
      const metrics = await page.evaluate(() => {
        const buttons = [...document.querySelectorAll("button")];
        const inputs = [...document.querySelectorAll("input")];
        return {
          title: document.title,
          viewportWidth: window.innerWidth,
          documentWidth: document.documentElement.scrollWidth,
          horizontalOverflow:
            document.documentElement.scrollWidth > window.innerWidth + 1,
          buttonCount: buttons.length,
          inputCount: inputs.length,
          feedbackDialogPresent: Boolean(document.querySelector("#feedback-dialog")),
          feedbackFormPresent: Boolean(document.querySelector("#feedback-form")),
          feedbackIssueContainerPresent: Boolean(document.querySelector("#feedback-issues")),
          serviceOnline: document
            .querySelector("#service-state")
            ?.classList.contains("online"),
        };
      });
      const screenshot = path.join(outputDir, `${viewport.name}.png`);
      await page.screenshot({ path: screenshot, fullPage: true });
      const feedbackMetrics = await page.evaluate(() => {
        const dialog = document.querySelector("#feedback-dialog");
        const issues = document.querySelector("#feedback-issues");
        issues.innerHTML = `
          <article class="feedback-issue">
            <div class="feedback-issue-heading">
              <div><span class="issue-index">1</span><span class="issue-severity major">major</span><span class="issue-category">style</span></div>
              <span>综合画像</span>
            </div>
            <h3>当前段落表达机械，需要人工确认修订方向。</h3>
            <div class="issue-evidence"><p><strong>当前原文：</strong>本次结果显示……</p><p><strong>期望结果：</strong>以具体、自然且不编造经历的语言解释结果。</p></div>
            <div class="feedback-fields">
              <label><span>复核决定</span><select><option>确认问题，等待修正</option></select></label>
              <label><span>审核说明</span><textarea rows="2">请保留数据边界并降低机械感。</textarea></label>
              <label class="replacement-field"><span>人工替换文字</span><textarea rows="3"></textarea></label>
            </div>
          </article>`;
        dialog.showModal();
        const rect = dialog.getBoundingClientRect();
        return {
          dialogWithinViewport:
            rect.left >= 0 && rect.right <= window.innerWidth && rect.top >= 0 && rect.bottom <= window.innerHeight,
          dialogHorizontalOverflow: dialog.scrollWidth > dialog.clientWidth + 1,
        };
      });
      const feedbackScreenshot = path.join(outputDir, `${viewport.name}-feedback.png`);
      await page.screenshot({ path: feedbackScreenshot, fullPage: false });
      results.push({
        ...viewport,
        ...metrics,
        ...feedbackMetrics,
        consoleErrors,
        screenshot,
        feedbackScreenshot,
      });
      await page.close();
    }
  } finally {
    await browser.close();
  }

  const failures = results.filter(
    (item) =>
      item.horizontalOverflow ||
      item.consoleErrors.length > 0 ||
      !item.serviceOnline ||
      !item.feedbackDialogPresent ||
      !item.feedbackFormPresent ||
      !item.feedbackIssueContainerPresent ||
      !item.dialogWithinViewport ||
      item.dialogHorizontalOverflow ||
      item.buttonCount < 1 ||
      item.inputCount < 7,
  );
  const summary = { pass: failures.length === 0, baseUrl, results };
  fs.writeFileSync(
    path.join(outputDir, "summary.json"),
    JSON.stringify(summary, null, 2),
    "utf8",
  );
  process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
  if (failures.length) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
