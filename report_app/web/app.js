const form = document.querySelector("#job-form");
const fileInput = document.querySelector("#json-files");
const fileList = document.querySelector("#file-list");
const fileCount = document.querySelector("#file-count");
const fileDrop = document.querySelector("#file-drop");
const apiKeyInput = document.querySelector("#api-key");
const showKey = document.querySelector("#show-key");
const submitButton = document.querySelector("#submit-button");
const formMessage = document.querySelector("#form-message");
const serviceState = document.querySelector("#service-state");
const emptyState = document.querySelector("#empty-state");
const queueWrap = document.querySelector("#queue-table-wrap");
const queueBody = document.querySelector("#queue-body");
const queueSummary = document.querySelector("#queue-summary");
const feedbackDialog = document.querySelector("#feedback-dialog");
const feedbackForm = document.querySelector("#feedback-form");
const feedbackIssues = document.querySelector("#feedback-issues");
const feedbackContext = document.querySelector("#feedback-context");
const feedbackReviewer = document.querySelector("#feedback-reviewer");
const feedbackMessage = document.querySelector("#feedback-message");
const feedbackClose = document.querySelector("#feedback-close");
const feedbackCancel = document.querySelector("#feedback-cancel");
const feedbackSave = document.querySelector("#feedback-save");

let selectedFiles = [];
let activeJobId = null;
let pollTimer = null;
let activeJobSnapshot = null;
let activeReviewItem = null;

const statusLabels = {
  queued: "等待中",
  running: "生成中",
  approved: "已通过",
  review: "待复核",
  failed: "失败",
};

function formatSize(size) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function setFiles(files) {
  selectedFiles = Array.from(files).filter((file) => file.name.toLowerCase().endsWith(".json"));
  fileList.replaceChildren();
  selectedFiles.forEach((file) => {
    const item = document.createElement("li");
    const name = document.createElement("span");
    const size = document.createElement("small");
    name.textContent = file.name;
    size.textContent = formatSize(file.size);
    item.append(name, size);
    fileList.append(item);
  });
  fileCount.textContent = selectedFiles.length ? `已选择 ${selectedFiles.length} 份` : "尚未选择";
}

fileInput.addEventListener("change", () => setFiles(fileInput.files));
showKey.addEventListener("change", () => {
  apiKeyInput.type = showKey.checked ? "text" : "password";
});

["dragenter", "dragover"].forEach((eventName) => {
  fileDrop.addEventListener(eventName, (event) => {
    event.preventDefault();
    fileDrop.classList.add("dragging");
  });
});

["dragleave", "drop"].forEach((eventName) => {
  fileDrop.addEventListener(eventName, (event) => {
    event.preventDefault();
    fileDrop.classList.remove("dragging");
  });
});

fileDrop.addEventListener("drop", (event) => {
  setFiles(event.dataTransfer.files);
});

async function readFiles() {
  return Promise.all(
    selectedFiles.map(async (file) => ({
      name: file.name,
      content: await file.text(),
    })),
  );
}

function resultLinks(item) {
  const links = [];
  item.pdfs.forEach((pdf, index) => {
    links.push(`<a href="${pdf.url}" target="_blank" rel="noreferrer">PDF${item.pdfs.length > 1 ? ` ${index + 1}` : ""}</a>`);
  });
  if (item.quality_review_url) links.push(`<a class="review-link" href="${item.quality_review_url}" target="_blank" rel="noreferrer">复核说明</a>`);
  if (item.report_url) links.push(`<a href="${item.report_url}" target="_blank" rel="noreferrer">结构化 JSON</a>`);
  if (item.check_url) links.push(`<a href="${item.check_url}" target="_blank" rel="noreferrer">原始检查 JSON</a>`);
  return links.join("");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function reviewPanel(item) {
  const review = item.review_summary || {};
  if (!review.requires_human_review) return "";
  const problems = Array.isArray(review.problem_preview) ? review.problem_preview : [];
  const actions = Array.isArray(review.next_actions) ? review.next_actions : [];
  const problemList = problems.length
    ? `<ol>${problems.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ol>`
    : "<p>请打开完整复核说明查看未通过原因。</p>";
  const actionList = actions.length
    ? `<ul>${actions.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul>`
    : "";
  const issues = Array.isArray(review.issues) ? review.issues : [];
  const feedback = item.feedback_summary || {};
  const progress = Number(feedback.reviewed_issue_count || 0)
    ? `<p class="feedback-progress">已复核 ${Number(feedback.reviewed_issue_count || 0)} / ${issues.length} 项，已解决 ${Number(feedback.resolved_issue_count || 0)} 项</p>`
    : "";
  const feedbackButton = issues.length
    ? `<button class="review-button" type="button" data-review-item="${escapeHtml(item.item_id)}">处理反馈</button>`
    : "";
  return `
    <div class="review-panel">
      <div class="review-score">质量分 ${Number(review.score || 0)} / 目标 ${Number(review.target_score || 0)}</div>
      <strong>${escapeHtml(review.headline || "需要人工复核")}</strong>
      ${problemList}
      ${actionList}
      ${progress}
      ${feedbackButton}
      ${item.quality_review_url ? `<a href="${item.quality_review_url}" target="_blank" rel="noreferrer">打开完整复核说明</a>` : ""}
    </div>`;
}

function renderJob(job) {
  activeJobSnapshot = job;
  emptyState.hidden = true;
  queueWrap.hidden = false;
  const complete = job.items.filter((item) => ["approved", "review", "failed"].includes(item.status)).length;
  queueSummary.textContent = `${job.stage_label} · ${complete}/${job.items.length} 完成`;
  queueBody.innerHTML = job.items
    .map((item) => {
      const log = item.log_tail
        ? `<details class="log-details"><summary>运行日志</summary><pre>${escapeHtml(item.log_tail)}</pre></details>`
        : "";
      return `
        <tr>
          <td>
            <div class="filename">${escapeHtml(item.filename)}</div>
            ${item.student_number ? `<div class="student-number">被试编号：${escapeHtml(item.student_number)}</div>` : ""}
          </td>
          <td>
            <div class="status-line"><span class="status-badge ${escapeHtml(item.status)}">${statusLabels[item.status] || item.status}</span></div>
            <div class="status-message">${escapeHtml(item.message)}</div>
          </td>
          <td>
            <div class="result-links">${resultLinks(item)}</div>
            ${reviewPanel(item)}
            ${log}
          </td>
        </tr>`;
    })
    .join("");
}

const decisionLabels = {
  confirmed_issue: "确认问题，等待修正",
  false_positive: "Checker 误报",
  manual_revision: "已人工改写",
  targeted_regeneration: "请求局部重生成",
};

function issueField(label, value) {
  if (!value) return "";
  return `<p><strong>${escapeHtml(label)}：</strong>${escapeHtml(value)}</p>`;
}

function openFeedbackWindow(item) {
  activeReviewItem = item;
  feedbackMessage.textContent = "";
  feedbackContext.textContent = `${item.filename}${item.student_number ? ` · ${item.student_number}` : ""}`;
  const review = item.review_summary || {};
  const issues = Array.isArray(review.issues) ? review.issues : [];
  const latest = (item.feedback_summary || {}).latest_decisions || {};
  feedbackIssues.innerHTML = issues.map((issue, index) => {
    const saved = latest[issue.issue_id] || {};
    const options = [
      ["", "暂不处理"],
      ...Object.entries(decisionLabels),
    ].map(([value, label]) => `<option value="${value}" ${saved.decision === value ? "selected" : ""}>${escapeHtml(label)}</option>`).join("");
    return `
      <article class="feedback-issue" data-issue-id="${escapeHtml(issue.issue_id)}">
        <div class="feedback-issue-heading">
          <div>
            <span class="issue-index">${index + 1}</span>
            <span class="issue-severity ${escapeHtml(issue.severity)}">${escapeHtml(issue.severity)}</span>
            <span class="issue-category">${escapeHtml(issue.category)}</span>
          </div>
          <span>${escapeHtml(issue.metric || issue.section_id || "整份报告")}</span>
        </div>
        <h3>${escapeHtml(issue.problem)}</h3>
        <div class="issue-evidence">
          ${issueField("当前原文", issue.current_excerpt)}
          ${issueField("检查依据", issue.evidence)}
          ${issueField("期望结果", issue.expected)}
          ${issueField("自动修订建议", issue.fix_instruction)}
        </div>
        <div class="feedback-fields">
          <label>
            <span>复核决定</span>
            <select class="feedback-decision">${options}</select>
          </label>
          <label>
            <span>审核说明</span>
            <textarea class="feedback-note" rows="2" maxlength="4000" placeholder="说明为什么接受、驳回或如何修改">${escapeHtml(saved.note || "")}</textarea>
          </label>
          <label class="replacement-field">
            <span>人工替换文字（选择“已人工改写”时填写）</span>
            <textarea class="feedback-replacement" rows="3" maxlength="12000" placeholder="粘贴修订后的局部文字">${escapeHtml(saved.replacement_text || "")}</textarea>
          </label>
        </div>
      </article>`;
  }).join("");
  feedbackDialog.showModal();
}

function closeFeedbackWindow() {
  activeReviewItem = null;
  feedbackDialog.close();
}

queueBody.addEventListener("click", (event) => {
  const button = event.target.closest("[data-review-item]");
  if (!button || !activeJobSnapshot) return;
  const item = activeJobSnapshot.items.find((value) => value.item_id === button.dataset.reviewItem);
  if (item) openFeedbackWindow(item);
});

feedbackClose.addEventListener("click", closeFeedbackWindow);
feedbackCancel.addEventListener("click", closeFeedbackWindow);
feedbackDialog.addEventListener("click", (event) => {
  if (event.target === feedbackDialog) closeFeedbackWindow();
});

feedbackForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!activeReviewItem || !activeJobId) return;
  const reviews = Array.from(feedbackIssues.querySelectorAll(".feedback-issue"))
    .map((card) => ({
      issue_id: card.dataset.issueId,
      decision: card.querySelector(".feedback-decision").value,
      note: card.querySelector(".feedback-note").value.trim(),
      replacement_text: card.querySelector(".feedback-replacement").value.trim(),
    }))
    .filter((value) => value.decision);
  if (!reviews.length) {
    feedbackMessage.textContent = "请至少选择一项复核决定。";
    return;
  }
  feedbackSave.disabled = true;
  feedbackMessage.textContent = "正在保存";
  try {
    const response = await fetch(
      `/api/jobs/${encodeURIComponent(activeJobId)}/items/${encodeURIComponent(activeReviewItem.item_id)}/feedback`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reviewer: feedbackReviewer.value.trim(), reviews }),
      },
    );
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "保存反馈失败");
    activeReviewItem.feedback_summary = result.feedback_summary;
    feedbackMessage.textContent = `已保存 ${Number(result.saved_count || 0)} 条复核意见。`;
    await pollJob();
    setTimeout(closeFeedbackWindow, 600);
  } catch (error) {
    feedbackMessage.textContent = error.message;
  } finally {
    feedbackSave.disabled = false;
  }
});

async function pollJob() {
  if (!activeJobId) return;
  try {
    const response = await fetch(`/api/jobs/${encodeURIComponent(activeJobId)}`, { cache: "no-store" });
    if (!response.ok) throw new Error("无法读取任务状态");
    const job = await response.json();
    renderJob(job);
    if (["approved", "needs_review", "completed_with_errors"].includes(job.status)) {
      clearInterval(pollTimer);
      pollTimer = null;
      submitButton.disabled = false;
      submitButton.textContent = "开始批量生成";
      apiKeyInput.value = "";
    }
  } catch (error) {
    formMessage.textContent = error.message;
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  formMessage.textContent = "";
  if (!selectedFiles.length) {
    formMessage.textContent = "请先选择至少一个 JSON 文件";
    return;
  }
  if (!apiKeyInput.value.trim()) {
    formMessage.textContent = "请填写 DeepSeek API Key";
    return;
  }

  submitButton.disabled = true;
  submitButton.textContent = "正在创建任务";
  try {
    const payload = {
      api_key: apiKeyInput.value.trim(),
      stage: document.querySelector('input[name="stage"]:checked').value,
      files: await readFiles(),
      max_rounds: Number(document.querySelector("#max-rounds").value),
      quality_target_score: Number(document.querySelector("#quality-score").value),
      render_review_draft: document.querySelector("#render-review").checked,
      theme: "hybrid_expert_dashboard",
    };
    const response = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "任务创建失败");
    activeJobId = result.job_id;
    renderJob(result);
    submitButton.textContent = "批次运行中";
    clearInterval(pollTimer);
    pollTimer = setInterval(pollJob, 1800);
    await pollJob();
  } catch (error) {
    submitButton.disabled = false;
    submitButton.textContent = "开始批量生成";
    formMessage.textContent = error.message;
  }
});

async function checkHealth() {
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    if (!response.ok) throw new Error();
    serviceState.classList.add("online");
    serviceState.lastChild.textContent = " 本地服务已连接";
  } catch {
    serviceState.classList.remove("online");
    serviceState.lastChild.textContent = " 本地服务未连接";
  }
}

checkHealth();
