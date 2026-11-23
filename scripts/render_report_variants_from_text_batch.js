const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..");
const DEFAULT_TEXT_DIR = path.join(ROOT, "output", "text_agent_batch_v4");
const DEFAULT_SAMPLE_DIR = path.join(ROOT, "samples", "text_agent_batch");
const DEFAULT_OUTPUT_DIR = path.join(ROOT, "output", "report_design_variants_v1");
const REPORT_ILLUSTRATION_DIR = path.join(ROOT, "assets", "report_illustrations");
const REPORT_ILLUSTRATION_FILES = {
  elementary: {
    "创新": "innovation-gouache-v1.png",
    "好奇": "curiosity-gouache-v1.png",
    "思维": "thinking-gouache-v1.png",
    "认知": "cognition-gouache-v1.png",
    "情绪": "emotion-gouache-v1.png",
  },
  secondary: {
    "创新": "junior-innovation-gouache-v1.png",
    "好奇": "junior-curiosity-gouache-v2.png",
    "思维": "junior-thinking-gouache-v2.png",
    "认知": "junior-cognition-gouache-v2.png",
    "情绪": "junior-emotion-gouache-v2.png",
  },
};
const illustrationDataUrlCache = new Map();

const SECTION_TITLES = {
  preface: "前言",
  core_growth_portrait: "核心成长画像",
  detailed_indicator_analysis: "详细指标分析",
  growth_support_suggestions: "成长支持建议",
  boundary_note: "报告说明",
};

const THEMES = {
  professional_blue: {
    label: "专家剖面蓝",
    subtitle: "更接近传统测评报告，适合专家审核与附录",
    primary: "#245B89",
    primaryDark: "#173D61",
    accent: "#D97845",
    mid: "#7AA7A3",
    bg: "#FFFFFF",
    soft: "#F2F6FA",
    soft2: "#E7EEF5",
    ink: "#1F2933",
    body: "#303B45",
    muted: "#68737D",
    line: "#D9E2EA",
    topBand: "#245B89",
    chart: "profile",
    density: "compact",
  },
  parent_dashboard_teal: {
    label: "家长仪表盘青绿",
    subtitle: "分数清楚、建议直接，适合正式家长版主线",
    primary: "#2D7A78",
    primaryDark: "#1D5B5A",
    accent: "#E59A3C",
    mid: "#78A9A5",
    bg: "#FBFCFA",
    soft: "#EAF5F1",
    soft2: "#F4FAF8",
    ink: "#243536",
    body: "#304344",
    muted: "#687A7A",
    line: "#D6E6E1",
    topBand: "#2D7A78",
    chart: "bars",
    density: "balanced",
  },
  story_sage_cards: {
    label: "图文叙事鼠尾草",
    subtitle: "一页一个主题，温和、亲和，适合交付版体验",
    primary: "#6B7F3B",
    primaryDark: "#4E6228",
    accent: "#C07D53",
    mid: "#80AAA3",
    bg: "#FFFEFB",
    soft: "#F3F0E8",
    soft2: "#FBF7EF",
    ink: "#2E3327",
    body: "#3B4134",
    muted: "#6F7567",
    line: "#E4DED0",
    topBand: "#6B7F3B",
    chart: "cards",
    density: "airy",
  },
  hybrid_expert_dashboard: {
    label: "专家控制板 × 家长仪表盘",
    subtitle: "总体画像用折线图，模块解读用仪表盘，保持先图后文",
    primary: "#245B89",
    primaryDark: "#173D61",
    accent: "#E59A3C",
    mid: "#2D7A78",
    bg: "#FBFCFA",
    soft: "#EAF5F1",
    soft2: "#F3F7FA",
    ink: "#1F2933",
    body: "#303B45",
    muted: "#667085",
    line: "#D7E3EA",
    topBand: "#245B89",
    chart: "profile",
    layout: "hybrid_expert_dashboard",
    density: "balanced",
  },
};

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function writeText(filePath, text) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, text, "utf8");
}

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function parseFinalReport(txtPath) {
  const text = fs.readFileSync(txtPath, "utf8");
  const start = text.indexOf("=== Final Report ===");
  const end = text.indexOf("=== Final Check ===", start);
  if (start < 0 || end < 0) {
    throw new Error(`Missing Final Report markers: ${txtPath}`);
  }
  return JSON.parse(text.slice(start, end).replace("=== Final Report ===", "").trim());
}

function section(report, id) {
  const found = (report.sections || []).find((item) => item.section_id === id);
  return found || { section_id: id, title: SECTION_TITLES[id] || id, body: "" };
}

function getScores(sample) {
  return Object.entries(sample.scores || {}).map(([key, value]) => ({
    key,
    name: value.dimension_name || key,
    domain: value.domain || "其他维度",
    score: Number(value.score || 0),
    rawScore: value.raw_score === undefined || value.raw_score === null || value.raw_score === ""
      ? Number(value.score || 0)
      : Number(value.raw_score),
    normP20: value.norm_p20 === undefined || value.norm_p20 === null || value.norm_p20 === ""
      ? null
      : Number(value.norm_p20),
    normP80: value.norm_p80 === undefined || value.norm_p80 === null || value.norm_p80 === ""
      ? null
      : Number(value.norm_p80),
    rawScoreRange: Array.isArray(value.raw_score_range) ? value.raw_score_range.map(Number) : null,
    plotRange: Array.isArray(value.plot_range) ? value.plot_range.map(Number) : null,
    level: value.level || "",
    percentile: value.percentile_band || "",
    rankPercentile: value.rank_percentile === undefined || value.rank_percentile === null || value.rank_percentile === ""
      ? null
      : Number(value.rank_percentile),
    interpretation: value.interpretation || "",
  }));
}

function displayLevel(level = "", percentile = "") {
  const sourceLevel = String(level || "").trim();
  if (sourceLevel) return sourceLevel;

  const sourcePercentile = String(percentile || "").trim().toLowerCase();
  if (sourcePercentile.includes("top_20")) return "前20%";
  if (sourcePercentile.includes("bottom_20")) return "后20%";
  if (sourcePercentile.includes("top_30")) return "前30%";
  if (sourcePercentile.includes("bottom_30")) return "后30%";
  if (sourcePercentile.includes("middle")) return "中间水平";
  return "未提供层级";
}

function band(score, level = "", percentile = "") {
  return displayLevel(level, percentile);
}

function scoreRole(item) {
  const level = String(item.level || "").toLowerCase();
  const percentile = String(item.percentile || "").toLowerCase();
  if (percentile.includes("bottom") || /潜力|发展|偏低|较低|低/.test(level)) return "support";
  if (percentile.includes("top") || /优势|较高|高/.test(level)) return "strength";
  return "neutral";
}

function bandClass(item, theme) {
  const role = scoreRole(item);
  if (role === "support") return theme.accent;
  if (role === "strength") return theme.primary;
  return theme.mid;
}

function scoreReferenceLines(sample) {
  const metadata = sample.scale_config || sample.report_metadata || {};
  const rawLines = metadata.score_reference_lines || sample.score_reference_lines || [];
  if (!Array.isArray(rawLines)) return [];
  return [...new Set(rawLines.map(Number).filter((value) => Number.isFinite(value) && value >= 0 && value <= 100))]
    .sort((a, b) => a - b);
}

function peerRankLabel(item) {
  if (!Number.isFinite(item.rankPercentile)) return "未提供同伴位置";
  return `超过约 ${item.rankPercentile.toFixed(1)}% 同伴`;
}

function referenceLineCaption(referenceLines, sample = {}) {
  const config = sample.scale_config || sample.report_metadata || {};
  if (config.classification_basis === "fixed_norm_20_80_raw_score") {
    const subject = isSecondaryReport(sample) ? "你" : "孩子";
    return `图中使用原始分数作图；各指标的 P20/P80 分界线在视觉上对齐，具体阈值来自固定常模表，箭头表示${subject}本次原始分在该指标常模区间中的位置。`;
  }
  if (config.classification_basis === "class_rank_percentile") {
    return "图中分数用于展示本次测验位置；潜力区、常态区和优势区依据同龄参照数据划定，而非原始分数阈值。";
  }
  if (!referenceLines.length) {
    return "图中分数用于展示本次结果位置；水平解释以本次测评提供的层级与说明为准。";
  }
  return `图中的 ${referenceLines.join("、")} 为本量表提供的阅读参考线；具体水平以本次测评说明为准。`;
}

function hasNormBoundary(item) {
  return Number.isFinite(item.rawScore) && Number.isFinite(item.normP20) && Number.isFinite(item.normP80) && item.normP80 > item.normP20;
}

function classificationBasis(sample) {
  const config = sample.scale_config || sample.report_metadata || {};
  return String(config.classification_basis || "");
}

function expectedFixedNormLevel(item) {
  if (!hasNormBoundary(item)) return "";
  if (item.rawScore <= item.normP20) return "潜力区";
  if (item.rawScore >= item.normP80) return "优势区";
  return "常态区";
}

function assertFixedNormChartContract(sample, scores) {
  if (classificationBasis(sample) !== "fixed_norm_20_80_raw_score") return;

  const missing = scores.filter((item) => !hasNormBoundary(item));
  if (missing.length) {
    throw new Error(
      `fixed_norm_20_80_raw_score requires raw_score, norm_p20, and norm_p80 for every charted metric. Missing: ${missing.map((item) => item.name).join(", ")}`,
    );
  }

  const mismatched = scores.filter((item) => {
    const expected = expectedFixedNormLevel(item);
    return expected && item.level && !String(item.level).includes(expected);
  });
  if (mismatched.length) {
    throw new Error(
      `Score level does not match fixed norm P20/P80 rule: ${mismatched.map((item) => `${item.name} expected ${expectedFixedNormLevel(item)} but got ${item.level}`).join("; ")}`,
    );
  }
}

function rawScoreText(value) {
  if (!Number.isFinite(value)) return "";
  return Number.isInteger(value) ? String(value) : value.toFixed(Math.abs(value) < 10 ? 2 : 1).replace(/\.?0+$/, "");
}

function normPlotRange(item) {
  if (hasNormBoundary(item)) {
    const explicit = [item.plotRange, item.rawScoreRange]
      .find((range) => Array.isArray(range)
        && range.length >= 2
        && range.every(Number.isFinite)
        && Math.min(range[0], range[1]) < item.normP20
        && Math.max(range[0], range[1]) > item.normP80);
    if (explicit) {
      return {
        min: Math.min(explicit[0], explicit[1]),
        max: Math.max(explicit[0], explicit[1]),
      };
    }
    const middleSpan = Math.max(0.001, item.normP80 - item.normP20);
    const sideSpan = middleSpan / 3;
    return {
      min: item.normP20 - sideSpan,
      max: item.normP80 + sideSpan,
    };
  }

  const fixed = Array.isArray(item.plotRange) && item.plotRange.length >= 2
    ? item.plotRange.filter(Number.isFinite)
    : [];
  const minCandidate = fixed.length >= 2 ? Math.min(fixed[0], fixed[1]) : Math.min(0, item.score);
  const maxCandidate = fixed.length >= 2 ? Math.max(fixed[0], fixed[1]) : Math.max(100, item.score);
  const min = minCandidate;
  const max = maxCandidate;
  return { min, max: max <= min ? min + 1 : max };
}

function normBandPosition(item) {
  if (!hasNormBoundary(item)) return Math.max(0, Math.min(100, item.score));
  const { min, max } = normPlotRange(item);
  const lowerSpan = Math.max(0.001, item.normP20 - min);
  const middleSpan = Math.max(0.001, item.normP80 - item.normP20);
  const upperSpan = Math.max(0.001, max - item.normP80);
  if (item.rawScore <= item.normP20) {
    return 20 * (Math.max(min, item.rawScore) - min) / lowerSpan;
  }
  if (item.rawScore < item.normP80) {
    return 20 + 60 * (item.rawScore - item.normP20) / middleSpan;
  }
  return 80 + 20 * (Math.min(max, item.rawScore) - item.normP80) / upperSpan;
}

function sampleTitle(samplePath) {
  return path.basename(samplePath, ".json")
    .replace(/^sample_\d+_/, "")
    .replace(/_/g, " ");
}

function splitDetailed(body) {
  const matches = [...String(body || "").matchAll(/【([^】]+)】([\s\S]*?)(?=【[^】]+】|$)/g)];
  if (matches.length) {
    return matches.map((match) => ({
      title: match[1].trim(),
      body: cleanText(match[2]),
    })).filter((item) => item.body || item.title);
  }
  return [{ title: "指标解读", body: cleanText(body) }];
}

function cleanText(text) {
  return String(text || "")
    .replace(/\r/g, "")
    .replace(/本项得分满分，按本量表规则列为优势区。?/g, "该指标处于优势区。")
    .replace(/本指标达到量表满分，按评分规则作为优势区处理。?/g, "该指标处于优势区。")
    .replace(/按输入的量表解释，本项处于/g, "本项指标目前处于")
    .replace(/同班同伴排名/g, "同龄参照数据")
    .replace(/同班参照/g, "同龄参照")
    .replace(/同班排名/g, "同龄参照数据")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function paraHtml(text) {
  return cleanText(text)
    .split(/\n+/)
    .filter(Boolean)
    .map((line) => `<p>${esc(line)}</p>`)
    .join("");
}

function baseCss(theme) {
  const bodySize = theme.density === "compact" ? 12.2 : theme.density === "airy" ? 13.4 : 12.8;
  const lineHeight = theme.density === "compact" ? 1.58 : theme.density === "airy" ? 1.72 : 1.66;
  return `
    @page { size: A4; margin: 0; }
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; background: #d8d8d8; color: ${theme.ink}; }
    body {
      font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", Arial, sans-serif;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }
    .page {
      --page-primary: ${theme.primary};
      --page-primary-dark: ${theme.primaryDark};
      --page-accent: ${theme.accent};
      --page-top-band: ${theme.topBand};
      --page-soft: ${theme.soft};
      --page-soft2: ${theme.soft2};
      --page-line: ${theme.line};
      width: 210mm;
      height: 297mm;
      margin: 0 auto;
      background: ${theme.bg};
      position: relative;
      overflow: hidden;
      page-break-after: always;
    }
    .page:last-child { page-break-after: auto; }
    .top-band { position: absolute; top: 0; left: 0; right: 0; height: 8mm; background: color-mix(in srgb, var(--page-top-band) 38%, white); }
    .inner { position: absolute; inset: 18mm 17mm 15mm 17mm; }
    .footer { position: absolute; left: 17mm; right: 17mm; bottom: 7mm; display: flex; justify-content: space-between; color: ${theme.muted}; font-size: 9.5px; }
    .kicker { color: var(--page-primary); font-weight: 800; font-size: 11px; letter-spacing: 0; text-transform: uppercase; }
    h1 { margin: 6px 0 5px; font-size: 28px; line-height: 1.16; letter-spacing: 0; color: ${theme.ink}; }
    h2 { margin: 0 0 12px; font-size: 18px; line-height: 1.35; color: var(--page-primary); }
    h3 { margin: 0 0 8px; font-size: 15px; line-height: 1.35; color: var(--page-primary-dark); }
    h4 { margin: 0 0 5px; font-size: 13px; line-height: 1.35; color: var(--page-primary-dark); }
    p { margin: 0 0 7px; font-size: ${bodySize}px; line-height: ${lineHeight}; color: ${theme.body}; }
    .lead { margin-top: 13px; padding: 13px 15px; background: var(--page-soft); border-left: 5px solid var(--page-primary); }
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 9px; }
    .card { background: var(--page-soft2); border: 1px solid var(--page-line); border-radius: 8px; padding: 12px 13px; }
    .plain-card { background: #fff; border: 1px solid var(--page-line); border-radius: 8px; padding: 12px 13px; }
    .score-card { color: #fff; border-radius: 8px; padding: 10px 11px; min-height: 72px; }
    .score-card b { display: block; font-size: 13px; line-height: 1.25; }
    .score-card strong { display: block; font-size: 27px; line-height: 1.05; margin-top: 3px; }
    .score-card span { display: block; font-size: 10.5px; margin-top: 3px; opacity: .95; }
    .chart-box { margin-top: 13px; padding: 11px; border: 1px solid var(--page-line); border-radius: 8px; background: #fff; }
    .chart-box:first-child { margin-top: 0; }
    .profile-chart { width: 100%; overflow: hidden; }
    .figure-caption { margin-top: 7px; color: ${theme.muted}; font-size: 10.5px; line-height: 1.5; }
    .pill { display: inline-block; padding: 3px 8px; border-radius: 999px; font-size: 10.5px; font-weight: 700; color: var(--page-primary-dark); background: var(--page-soft); margin: 0 5px 5px 0; }
    .suggestion { display: grid; grid-template-columns: 20mm 1fr; gap: 10px; margin-bottom: 9px; break-inside: avoid; }
    .suggestion-num { width: 20mm; height: 20mm; border-radius: 50%; background: var(--page-primary); color: #fff; display: flex; align-items: center; justify-content: center; font-size: 20px; font-weight: 900; }
    .suggestion .plain-card { padding: 10px 12px; }
    .mini-label { font-size: 10px; color: ${theme.muted}; font-weight: 700; margin-top: 6px; }
    .appendix-table { width: 100%; border-collapse: collapse; font-size: 11px; }
    .appendix-table th { background: var(--page-soft); color: var(--page-primary-dark); text-align: left; }
    .appendix-table th, .appendix-table td { border: 1px solid var(--page-line); padding: 6px 7px; vertical-align: top; }
    .detail-card { margin-bottom: 8px; break-inside: avoid; }
    .flow-module-heading { margin: 18px 0 8px; padding-top: 12px; border-top: 1px solid var(--page-line); color: ${theme.ink}; font-size: 28px; font-weight: 900; line-height: 1.16; }
    .flow-appendix-heading { margin: 13px 0 8px; padding-top: 9px; border-top: 1px solid var(--page-line); color: ${theme.ink}; font-size: 21px; font-weight: 900; line-height: 1.2; }
    .module-note { margin: 9px 0 10px; padding: 8px 10px; border-radius: 8px; background: var(--page-soft); color: ${theme.body}; font-size: 11.5px; line-height: 1.55; }
    .support-closing-note { margin-top: 10px; padding: 11px 13px; border-left: 4px solid var(--page-primary); background: var(--page-soft); }
    .support-closing-note strong { display: block; margin-bottom: 5px; color: var(--page-primary-dark); font-size: 13px; }
    .support-closing-note p { margin: 0; font-size: 10.9px; line-height: 1.55; }
    .first-page .inner { inset: 18mm 20mm 15mm 20mm; }
    .first-page h1 { margin-top: 10px; margin-bottom: 6px; font-size: 30px; text-align: center; }
    .student-line { margin: 0 0 9px; color: ${theme.muted}; text-align: center; font-size: 11px; font-weight: 700; }
    .first-page-intro { margin: 6px 0 10px; padding: 10px 12px; border-radius: 8px; background: var(--page-soft); color: ${theme.body}; }
    .first-page-intro p { margin-bottom: 0; font-size: 12.2px; line-height: 1.62; }
    .first-page-intro strong { color: var(--page-primary-dark); }
    .first-page-intro .student-meta { margin-top: 5px; color: ${theme.muted}; font-size: 10.5px; }
    .first-page .chart-box { margin-top: 9px; padding: 9px; }
    .first-page .lead { margin-top: 11px; padding: 13px 15px; }
    .first-page .lead h3 { margin-bottom: 7px; font-size: 15px; }
    .first-page .lead p { margin-bottom: 7px; font-size: 12.35px; line-height: 1.62; }
    .scene-band { display: flex; align-items: baseline; gap: 8px; margin: 0 0 10px; padding: 8px 10px; border-left: 4px solid var(--page-accent); background: var(--page-soft); }
    .scene-band span { color: ${theme.muted}; font-size: 10px; font-weight: 800; }
    .scene-band strong { color: var(--page-primary-dark); font-size: 14px; }
    .metric-card { padding: 0; overflow: hidden; border-left: 4px solid var(--page-primary); }
    .metric-card-top { display: grid; grid-template-columns: 122px 1fr; align-items: stretch; border-bottom: 1px solid var(--page-line); }
    .metric-card-title { display: grid; grid-template-columns: 30px minmax(0, 1fr); align-content: start; align-items: center; gap: 9px; padding: 13px 11px 12px; background: var(--page-soft); color: var(--page-primary-dark); font-size: 18px; font-weight: 900; line-height: 1.25; text-align: left; }
    .metric-card-logo { width: 28px; height: 28px; border: 1px solid var(--page-line); border-radius: 7px; background: rgba(255,255,255,.78); display: flex; align-items: center; justify-content: center; color: var(--page-primary); }
    .metric-card-logo svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
    .metric-card-name { min-width: 0; overflow-wrap: anywhere; }
    .metric-card-definition { padding: 12px 15px 11px; background: #fff; }
    .metric-card-label { display: block; margin-bottom: 4px; color: var(--page-primary); font-size: 10px; font-weight: 900; letter-spacing: 0; }
    .metric-card-definition p { margin: 0; font-size: 11.45px; line-height: 1.58; }
    .metric-card-analysis { padding: 11px 15px 12px; background: #fff; }
    .metric-card-analysis > .metric-card-label { color: var(--page-primary-dark); }
    .metric-card-analysis p { margin-bottom: 6px; font-size: 11.65px; line-height: 1.62; }
    .metric-card-analysis p:last-child { margin-bottom: 0; }
    .illustration-card { min-height: var(--illustration-height, 272px); height: var(--illustration-height, 272px); margin-top: 12px; border: 1px solid var(--page-line); border-radius: 8px; background: var(--page-soft2); display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(150px, .85fr); overflow: hidden; color: ${theme.body}; }
    .illustration-art { min-height: var(--illustration-height, 272px); }
    .illustration-card img { display: block; width: 100%; height: 100%; min-height: var(--illustration-height, 272px); object-fit: cover; object-position: left center; }
    .illustration-art svg { display: block; width: 100%; height: var(--illustration-height, 272px); }
    .illustration-copy { display: flex; flex-direction: column; justify-content: center; padding: 22px 21px; background: var(--page-soft); border-left: 1px solid var(--page-line); }
    .illustration-copy strong { display: block; color: var(--page-primary-dark); font-size: 17px; line-height: 1.35; margin-bottom: 8px; }
    .illustration-copy p { margin: 0; font-size: 11.4px; line-height: 1.62; }
    .compact-suggestion .suggestion { grid-template-columns: 16mm 1fr; gap: 8px; margin-bottom: 7px; }
    .compact-suggestion .suggestion-num { width: 16mm; height: 16mm; font-size: 16px; }
    .compact-suggestion .plain-card { padding: 9px 11px; }
    .support-page .inner { inset: 15mm 17mm 13mm 17mm; }
    .support-page h1 { margin-top: 3px; margin-bottom: 5px; }
    .support-page .module-note { margin: 6px 0 8px; padding: 7px 9px; }
    .support-page .compact-suggestion .suggestion { margin-bottom: 5px; }
    .support-page .compact-suggestion .plain-card { padding: 8px 10px; }
    .support-page .compact-suggestion h4 { margin-bottom: 4px; }
    .support-page .compact-suggestion p { margin-bottom: 5px; }
    .support-page .compact-suggestion .mini-label { margin-top: 4px; }
    .support-page .support-closing-note { margin-top: 6px; padding: 8px 11px; }
    .support-page .support-closing-note strong { margin-bottom: 3px; }
    .cover-page {
      background: #F7FBFA;
      color: #143F3B;
    }
    .cover-page::before {
      content: "";
      position: absolute;
      right: -32mm;
      bottom: -35mm;
      width: 112mm;
      height: 112mm;
      border-radius: 50%;
      background: #D7EFEB;
    }
    .cover-page::after {
      content: "";
      position: absolute;
      right: 18mm;
      bottom: 23mm;
      width: 48mm;
      height: 48mm;
      border-radius: 50%;
      border: 16mm solid rgba(122, 190, 181, .18);
    }
    .cover-bars {
      position: absolute;
      top: 0;
      bottom: 0;
      left: 0;
      width: 24mm;
      background-color: #F7FBFA !important;
      forced-color-adjust: none;
    }
    .cover-bars span {
      position: absolute;
      top: 0;
      bottom: 0;
      display: block;
      forced-color-adjust: none;
    }
    .cover-bars .cover-bar-1 {
      left: 0;
      width: 7mm;
      background-color: #83C7BE !important;
    }
    .cover-bars .cover-bar-2 {
      left: 7mm;
      width: 7mm;
      background-color: #C8E7E2 !important;
    }
    .cover-bars .cover-bar-3 {
      left: 14mm;
      width: 5mm;
      background-color: #E5F3F0 !important;
    }
    .cover-inner {
      position: absolute;
      inset: 34mm 25mm 30mm 39mm;
      z-index: 2;
    }
    .cover-eyebrow {
      color: #4E8E87;
      font-size: 13px;
      font-weight: 800;
      letter-spacing: 0;
    }
    .cover-english {
      margin-top: 13mm;
      color: #1F5C56;
      font-family: Arial, sans-serif;
      font-size: 42px;
      font-weight: 900;
      line-height: 1.03;
      letter-spacing: 0;
    }
    .cover-rule {
      width: 100%;
      height: 2px;
      margin: 12mm 0 9mm;
      background: #83C7BE;
    }
    .cover-title {
      margin: 0;
      max-width: 142mm;
      color: #143F3B;
      font-size: 31px;
      font-weight: 900;
      line-height: 1.35;
      text-align: left;
    }
    .cover-meta {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      gap: 8px 15px;
      width: 90mm;
      margin-top: 24mm;
      padding: 14px 16px;
      background: rgba(255,255,255,.78);
      border-left: 4px solid #83C7BE;
    }
    .cover-meta span {
      color: #6B8E89;
      font-size: 11px;
      font-weight: 700;
    }
    .cover-meta strong {
      color: #143F3B;
      font-size: 13px;
      font-weight: 800;
    }
    .cover-symbol {
      position: absolute;
      right: 28mm;
      bottom: 36mm;
      z-index: 3;
      color: #2D756E;
      font-size: 76px;
      font-weight: 900;
      line-height: 1;
      opacity: .72;
    }
    svg text { font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif; }
  `;
}

const PROFILE_DOMAIN_COLORS = [
  { plot: "#F1F8FF", metric: "#B9DEF8", domain: "#8EC9EE" },
  { plot: "#F2FBF0", metric: "#C8E9B9", domain: "#A4D88B" },
  { plot: "#FFF8EC", metric: "#F8D8A8", domain: "#EDBF7B" },
  { plot: "#F7F0FF", metric: "#DCC1F5", domain: "#C89AE8" },
  { plot: "#FFF1F2", metric: "#F6BFC4", domain: "#EC989E" },
  { plot: "#EEF9F8", metric: "#B9E3DE", domain: "#8ACCC4" },
];

// Score-zone colors express the fixed norm interpretation across every module.
// Module palettes only style the surrounding page, card borders, and accents.
const SCORE_BAND_PALETTE = {
  potential: "#D9F0FF",
  normal: "#E6F4E9",
  advantage: "#FFF0D6",
  fillPotential: "#5A82B3",
  fillNormal: "#4A9471",
  fillAdvantage: "#E0A022",
  track: "#EEF2F4",
};

const DOMAIN_PALETTES = {
  "创新": {
    primary: "#7C3AED",
    primaryDark: "#4C1D95",
    accent: "#8B5CF6",
    topBand: "#6D28D9",
    soft: "#F3E8FF",
    soft2: "#FAF5FF",
    line: "#DDD6FE",
    plot: "#F5F0FF",
    metric: "#DDD6FE",
    domain: "#C4B5FD",
  },
  "好奇": {
    primary: "#0F9F9A",
    primaryDark: "#115E59",
    accent: "#14B8A6",
    topBand: "#0F766E",
    soft: "#E6FFFA",
    soft2: "#F0FDFA",
    line: "#99F6E4",
    plot: "#ECFEFF",
    metric: "#B2F5EA",
    domain: "#5EEAD4",
  },
  "思维": {
    primary: "#2563EB",
    primaryDark: "#1E3A8A",
    accent: "#3B82F6",
    topBand: "#1D4ED8",
    soft: "#EFF6FF",
    soft2: "#F8FBFF",
    line: "#BFDBFE",
    plot: "#EFF6FF",
    metric: "#BFDBFE",
    domain: "#93C5FD",
  },
  "认知": {
    primary: "#EA7A16",
    primaryDark: "#9A3412",
    accent: "#F59E0B",
    topBand: "#C85D0E",
    soft: "#FFF7ED",
    soft2: "#FFFBEB",
    line: "#FED7AA",
    plot: "#FFF7ED",
    metric: "#FED7AA",
    domain: "#FDBA74",
  },
  "情绪": {
    primary: "#E63B62",
    primaryDark: "#9F1239",
    accent: "#F43F5E",
    topBand: "#BE123C",
    soft: "#FFF1F2",
    soft2: "#FFF7F8",
    line: "#FECDD3",
    plot: "#FFF1F2",
    metric: "#FECDD3",
    domain: "#FDA4AF",
  },
};

function domainPalette(domainName) {
  const name = String(domainName || "");
  return Object.entries(DOMAIN_PALETTES).find(([key]) => name.includes(key))?.[1] || null;
}

function themeForDomain(theme, domainName) {
  const palette = domainPalette(domainName);
  return palette ? { ...theme, ...palette } : theme;
}

function styleVarsForTheme(theme) {
  return [
    `--page-primary:${theme.primary}`,
    `--page-primary-dark:${theme.primaryDark}`,
    `--page-accent:${theme.accent}`,
    `--page-top-band:${theme.topBand}`,
    `--page-soft:${theme.soft}`,
    `--page-soft2:${theme.soft2}`,
    `--page-line:${theme.line}`,
  ].join(";");
}

function displayMetricName(name) {
  return String(name || "")
    .replace(/NogoAccuracy/gi, "Nogo")
    .replace(/goAccuracy/g, "go")
    .replace(/[（(]\s*([^）)]*?)\s*[）)]/g, "$1")
    .replace(/\s+/g, "")
    .trim();
}

function contiguousDomainGroups(scores) {
  const groups = [];
  scores.forEach((score, index) => {
    const domain = String(score.domain || "其他指标").trim() || "其他指标";
    const previous = groups[groups.length - 1];
    if (previous && previous.domain === domain) {
      previous.end = index;
      return;
    }
    groups.push({ domain, start: index, end: index });
  });
  return groups;
}

function profileChart(scores, theme, referenceLines = []) {
  const data = scores.length ? scores : [];
  if (!data.length) return "<p>暂无可绘制的指标数据。</p>";
  const usesNormBands = data.every(hasNormBoundary);

  // One grouped overview keeps all supplied indicators comparable on a single page.
  const width = 940;
  const left = 52;
  const right = 18;
  const top = 24;
  const plotH = 245;
  const plotBottom = top + plotH;
  // Give dense vertical labels enough breathing room without shrinking the plot.
  const metricH = 124;
  const domainH = 32;
  const height = plotBottom + metricH + domainH + 12;
  const plotW = width - left - right;
  const slotW = plotW / data.length;
  const y = (score) => top + (100 - Math.max(0, Math.min(100, score))) * plotH / 100;
  const x = (index) => left + (index + .5) * slotW;
  const groups = contiguousDomainGroups(data);
  const pathD = data.map((item, index) => `${index ? "L" : "M"}${x(index)},${y(usesNormBands ? normBandPosition(item) : item.score)}`).join(" ");
  const gridValues = usesNormBands ? [0, 20, 80, 100] : [...new Set([0, 25, 50, 75, 100, ...referenceLines])].sort((a, b) => a - b);

  const groupBlocks = groups.map((group, index) => {
    const palette = domainPalette(group.domain);
    const color = palette
      ? { plot: palette.plot, metric: palette.metric, domain: palette.domain }
      : PROFILE_DOMAIN_COLORS[index % PROFILE_DOMAIN_COLORS.length];
    const groupX = left + group.start * slotW;
    const groupW = (group.end - group.start + 1) * slotW;
    const labelSize = Math.max(9, Math.min(13, groupW / Math.max(3, group.domain.length) * 0.72));
    return `
      <rect x="${groupX}" y="${top}" width="${groupW}" height="${plotH}" fill="${color.plot}"/>
      <rect x="${groupX}" y="${plotBottom}" width="${groupW}" height="${metricH}" fill="${color.metric}"/>
      <rect x="${groupX}" y="${plotBottom + metricH}" width="${groupW}" height="${domainH}" fill="${color.domain}"/>
      <line x1="${groupX}" y1="${top}" x2="${groupX}" y2="${plotBottom + metricH + domainH}" stroke="#fff" stroke-width="2"/>
      <text x="${groupX + groupW / 2}" y="${plotBottom + metricH + 21}" text-anchor="middle" font-size="${Math.min(Math.max(labelSize, 12), 13)}" font-weight="900" fill="${theme.primaryDark}">${esc(group.domain)}</text>
    `;
  }).join("");
  const grid = gridValues.map((value) => {
    const isReferenceLine = usesNormBands ? value === 20 || value === 80 : referenceLines.includes(value);
    const label = usesNormBands
      ? ({ 0: "", 20: "P20", 80: "P80", 100: "" }[value] || "")
      : value;
    return `
      <line x1="${left}" y1="${y(value)}" x2="${left + plotW}" y2="${y(value)}" stroke="${isReferenceLine ? theme.ink : theme.line}" stroke-width="${isReferenceLine ? 1.1 : 1}" opacity="${isReferenceLine ? .52 : 1}"/>
      <text x="${left - 9}" y="${y(value) + 4}" text-anchor="end" font-size="11.5" font-weight="700" fill="${theme.muted}">${label}</text>
    `;
  }).join("");
  const metricColumnGuides = data.slice(1).map((_, index) => {
    const guideX = left + (index + 1) * slotW;
    return `<line x1="${guideX}" y1="${plotBottom + 4}" x2="${guideX}" y2="${plotBottom + metricH - 4}" stroke="#fff" stroke-width="1" opacity=".72"/>`;
  }).join("");
  const labelsAndPoints = data.map((item, index) => `
    <circle cx="${x(index)}" cy="${y(usesNormBands ? normBandPosition(item) : item.score)}" r="5" fill="${theme.accent}" stroke="#fff" stroke-width="1.7"/>
    <text x="${x(index)}" y="${plotBottom + metricH / 2}" text-anchor="middle" dominant-baseline="middle" font-size="${data.length > 20 ? 12.2 : 13}" font-weight="900" fill="#073b63" style="writing-mode:vertical-rl;text-orientation:upright;letter-spacing:.8px;paint-order:stroke;stroke:rgba(255,255,255,.32);stroke-width:.35px">${esc(displayMetricName(item.name))}</text>
  `).join("");
  const finalBoundary = `<line x1="${left + plotW}" y1="${top}" x2="${left + plotW}" y2="${plotBottom + metricH + domainH}" stroke="#fff" stroke-width="2"/>`;

  const axisLabel = `<text x="17" y="${top + plotH / 2}" text-anchor="middle" font-size="11.5" font-weight="800" fill="${theme.muted}" transform="rotate(-90 17 ${top + plotH / 2})">${usesNormBands ? "常模区间" : "分数"}</text>`;
  return `<div class="profile-chart"><svg viewBox="0 0 ${width} ${height}" width="100%" height="auto" role="img" aria-label="全部指标的分领域成长画像折线图" style="text-rendering:geometricPrecision">${groupBlocks}${grid}${metricColumnGuides}${axisLabel}<path d="${pathD}" fill="none" stroke="${theme.accent}" stroke-width="4.1" stroke-linejoin="round" stroke-linecap="round"/>${labelsAndPoints}${finalBoundary}</svg></div>`;
}

function barChart(scores, theme, referenceLines = []) {
  const data = scores.slice().sort((a, b) => b.score - a.score);
  const width = 780;
  const rowH = 28;
  const height = 30 + data.length * rowH + 8;
  const left = 104;
  const axisW = 540;
  const rows = data.map((d, i) => {
    const y = 28 + i * rowH;
    const w = axisW * Math.max(0, Math.min(100, d.score)) / 100;
    return `
      <text x="${left - 10}" y="${y + 12}" text-anchor="end" font-size="11" fill="${theme.ink}">${esc(d.name)}</text>
      <rect x="${left}" y="${y}" width="${axisW}" height="11" rx="5.5" fill="${theme.line}" opacity=".72"/>
      <rect x="${left}" y="${y}" width="${w}" height="11" rx="5.5" fill="${bandClass(d, theme)}"/>
      <text x="${left + axisW + 12}" y="${y + 11}" font-size="11" fill="${theme.ink}">${Math.round(d.score)} · ${esc(band(d.score, d.level, d.percentile))}</text>
    `;
  }).join("");
  const thresholds = referenceLines.map((v) => `
    <line x1="${left + axisW * v / 100}" y1="19" x2="${left + axisW * v / 100}" y2="${height - 8}" stroke="${theme.ink}" stroke-dasharray="3 4" opacity=".35"/>
    <text x="${left + axisW * v / 100}" y="13" text-anchor="middle" font-size="10" fill="${theme.muted}">${v}</text>
  `).join("");
  return `<svg viewBox="0 0 ${width} ${height}" width="100%" height="auto">${thresholds}${rows}</svg>`;
}

function scoreCards(scores, theme) {
  return `<div class="grid-3">${scores.slice(0, 9).map((d) => `
    <div class="score-card" style="background:${bandClass(d, theme)}">
      <b>${esc(d.name)}</b>
      <strong>${Math.round(d.score)}</strong>
      <span>${esc(band(d.score, d.level, d.percentile))}</span>
    </div>
  `).join("")}</div>`;
}

function moduleDashboardChart(scores, theme, title = "模块指标", referenceLines = []) {
  if (scores.length && scores.every(hasNormBoundary)) {
    return normSegmentChart(scores, theme, title);
  }
  return levelSegmentChart(scores, theme, title);
}

function levelSegmentChart(scores, theme, title = "模块指标") {
  const data = scores;
  const width = 780;
  const rowH = 30;
  const height = Math.max(148, 72 + data.length * rowH);
  const labelX = 184;
  const left = 198;
  const axisW = 420;
  const top = 62;
  const { fillPotential, fillNormal, fillAdvantage, track } = SCORE_BAND_PALETTE;
  const fillFor = (item) => {
    const level = String(item.level || "");
    if (level.includes("潜力")) return fillPotential;
    if (level.includes("优势")) return fillAdvantage;
    return fillNormal;
  };
  const rows = data.map((d, i) => {
    const y = top + i * rowH;
    const progress = Math.max(0, Math.min(100, Number(d.score) || 0));
    const progressW = axisW * progress / 100;
    return `
      <text x="${labelX}" y="${y + 14}" text-anchor="end" font-size="10.8" fill="${theme.ink}">${esc(displayMetricName(d.name))}</text>
      <rect x="${left}" y="${y}" width="${axisW}" height="14" rx="7" fill="${track}"/>
      <rect x="${left}" y="${y}" width="${progressW}" height="14" rx="7" fill="${fillFor(d)}"/>
      <line x1="${left + axisW * .2}" y1="${y + 2}" x2="${left + axisW * .2}" y2="${y + 12}" stroke="#fff" stroke-width="1.4"/>
      <line x1="${left + axisW * .8}" y1="${y + 2}" x2="${left + axisW * .8}" y2="${y + 12}" stroke="#fff" stroke-width="1.4"/>
      <text x="${left + axisW + 14}" y="${y + 14}" font-size="11.5" fill="${theme.ink}">${esc(band(d.score, d.level, d.percentile))}</text>
    `;
  }).join("");
  return `
    <svg viewBox="0 0 ${width} ${height}" width="100%" height="auto">
      <text x="18" y="28" font-size="15" font-weight="800" fill="${theme.primaryDark}">${esc(title)}</text>
      <text x="18" y="48" font-size="10.5" fill="${theme.muted}">量度条依据本次报告等级显示</text>
      ${rows}
    </svg>
  `;
}

function normSegmentChart(scores, theme, title = "模块指标") {
  const data = scores;
  const width = 780;
  const rowH = 30;
  const height = Math.max(148, 72 + data.length * rowH);
  const labelX = 184;
  const left = 198;
  const axisW = 420;
  const top = 62;
  const { fillPotential, fillNormal, fillAdvantage, track } = SCORE_BAND_PALETTE;
  const fillFor = (item) => {
    const level = String(item.level || "");
    if (level.includes("潜力")) return fillPotential;
    if (level.includes("优势")) return fillAdvantage;
    return fillNormal;
  };
  const rows = data.map((d, i) => {
    const y = top + i * rowH;
    const progress = normBandPosition(d);
    const progressW = axisW * progress / 100;
    return `
      <text x="${labelX}" y="${y + 15}" text-anchor="end" font-size="10.6" fill="${theme.ink}">${esc(displayMetricName(d.name))}</text>
      <rect x="${left}" y="${y}" width="${axisW}" height="14" rx="7" fill="${track}"/>
      <rect x="${left}" y="${y}" width="${progressW}" height="14" rx="7" fill="${fillFor(d)}"/>
      <line x1="${left + axisW * .2}" y1="${y + 2}" x2="${left + axisW * .2}" y2="${y + 12}" stroke="#fff" stroke-width="1.4"/>
      <line x1="${left + axisW * .8}" y1="${y + 2}" x2="${left + axisW * .8}" y2="${y + 12}" stroke="#fff" stroke-width="1.4"/>
      <text x="${left + axisW + 14}" y="${y + 14}" font-size="11.5" fill="${theme.ink}">${esc(band(d.score, d.level, d.percentile))}</text>
    `;
  }).join("");
  return `
    <svg viewBox="0 0 ${width} ${height}" width="100%" height="auto">
      <text x="18" y="28" font-size="15" font-weight="800" fill="${theme.primaryDark}">${esc(title)}</text>
      <text x="18" y="48" font-size="10.5" fill="${theme.muted}">量度条依据同龄常模区间定位</text>
      ${rows}
    </svg>
  `;
}

function domainSummary(scores) {
  const groups = new Map();
  scores.forEach((item) => {
    if (!groups.has(item.domain)) groups.set(item.domain, []);
    groups.get(item.domain).push(item);
  });
  return [...groups.entries()].map(([name, items]) => ({
    name,
    count: items.length,
  }));
}

function groupScoresByDomain(scores) {
  const groups = new Map();
  scores.forEach((item) => {
    if (!groups.has(item.domain)) groups.set(item.domain, []);
    groups.get(item.domain).push(item);
  });
  return [...groups.entries()].map(([name, items]) => ({ name, items }));
}

function normalizeName(value) {
  return String(value || "").replace(/[【】\s]/g, "").toLowerCase();
}

function detailMatchesScore(detail, score) {
  const detailName = normalizeName(detail.title);
  const scoreName = normalizeName(score.name);
  return detailName === scoreName || detailName.includes(scoreName) || scoreName.includes(detailName);
}

function detailsForScores(details, scores, usedDetails) {
  const matched = [];
  scores.forEach((score) => {
    const detail = details.find((item) => !usedDetails.has(item) && detailMatchesScore(item, score));
    if (detail) {
      usedDetails.add(detail);
      matched.push(detail);
    }
  });
  return matched;
}

function renderMainChart(scores, theme, referenceLines = []) {
  if (theme.chart === "profile") return profileChart(scores, theme, referenceLines);
  if (theme.chart === "cards") return scoreCards(scores, theme);
  return barChart(scores, theme, referenceLines);
}

function resolveReportStage(sample) {
  const profile = sample.respondent_profile || {};
  const explicitFields = [
    sample.report_stage,
    sample.school_stage,
    sample.education_stage,
    sample.age_group,
    sample.report_variant,
    sample.writing_variant,
    profile.report_stage,
    profile.school_stage,
    profile.education_stage,
    profile.age_group,
    profile.report_variant,
    profile.writing_variant,
  ];
  const normalized = explicitFields.map((value) => String(value || "").toLowerCase()).join(" ");
  if (/senior_high|high_school|高中/.test(normalized)) return "senior_high";
  if (/junior_high|初中/.test(normalized)) return "junior_high";
  if (/middle_school|secondary|中学|青少年/.test(normalized)) return "secondary";
  if (/elementary|primary_school|小学/.test(normalized)) return "elementary";
  const reportType = String(sample.report_type || sample.scale_name || "").toLowerCase();
  if (/高中|senior_high|high_school/.test(reportType)) return "senior_high";
  if (/初中|junior_high/.test(reportType)) return "junior_high";
  if (/青少年|中学|middle_school|secondary/.test(reportType)) return "secondary";
  return "elementary";
}

function isSecondaryReport(sample) {
  return resolveReportStage(sample) !== "elementary";
}

function reportReaderLabels(sample) {
  if (isSecondaryReport(sample)) {
    return {
      action: "你可以这样做",
      collaboration: "需要支持时，可以这样表达",
      firstStep: "这周先试一步",
      supportIntro: "下面的建议由你来选择和尝试；家长与老师负责提供必要的时间、信息、反馈和支持。",
    };
  }
  return {
    action: "",
    collaboration: "家长可以这样说",
    firstStep: "迈出第一步",
    supportIntro: "以下建议用于帮助家长把测评结果转化为日常支持动作。",
  };
}

function reportSubjectLabel(sample) {
  const profile = sample.respondent_profile || {};
  const explicitLabel = profile.report_subject_label || profile.display_name || profile.child_display_name;
  if (explicitLabel) return String(explicitLabel);
  const grade = profile.grade || profile.age_group;
  if (isSecondaryReport(sample)) {
    return grade ? `${grade} · 青少年成长发展报告` : "青少年成长发展报告";
  }
  return grade ? `${grade} · 儿童成长发展报告` : "儿童成长发展报告";
}

function sourceStudentId(sample) {
  const metadata = sample.assessment_metadata || {};
  const raw = metadata.source_student_id ?? sample.source_student_id ?? "";
  return String(raw).trim();
}

function studentNumberLabel(sample) {
  const raw = sourceStudentId(sample);
  if (/^\d+$/.test(raw)) return `${raw}号`;
  if (/^\d+\s*号$/.test(raw)) return raw.replace(/\s+/g, "");
  return "";
}

function reportIndexLabel(sample, samplePath) {
  const baseLabel = sample.profile_label || reportSubjectLabel(sample) || sampleTitle(samplePath);
  const numberLabel = studentNumberLabel(sample);
  return numberLabel ? `${numberLabel} · ${baseLabel}` : baseLabel;
}

function mainReportTitle(sample) {
  let name = String(sample.scale_name || "").trim();
  if (isSecondaryReport(sample)) name = name.replace(/儿童/g, "青少年");
  if (name.includes("报告")) return name;
  if (name) return `${name}报告`;
  return isSecondaryReport(sample)
    ? "青少年创新潜能与综合素质评估报告"
    : "儿童创新潜能与综合素质评估报告";
}

function reportCoverTitle(sample) {
  return isSecondaryReport(sample)
    ? "青少年创新潜能与综合素质测评"
    : "儿童创新潜能与综合素质测评";
}

function reportDateLabel(sample) {
  const profile = sample.respondent_profile || {};
  const metadata = sample.assessment_metadata || {};
  const raw = [
    sample.assessment_date,
    sample.report_date,
    sample.test_date,
    metadata.assessment_date,
    metadata.report_date,
    metadata.test_date,
    profile.assessment_date,
    profile.report_date,
  ].find(Boolean);
  if (raw) {
    const text = String(raw).trim();
    const match = text.match(/^(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})/);
    if (match) return `${match[1]}年${Number(match[2])}月${Number(match[3])}日`;
    return text;
  }
  const now = new Date();
  return `${now.getFullYear()}年${now.getMonth() + 1}月${now.getDate()}日`;
}

function renderCoverPage(sample, theme) {
  const numberLabel = studentNumberLabel(sample);
  return `
    <section class="page cover-page" style="${styleVarsForTheme(theme)}">
      <div class="cover-bars" aria-hidden="true">
        <span class="cover-bar-1"></span>
        <span class="cover-bar-2"></span>
        <span class="cover-bar-3"></span>
      </div>
      <main class="cover-inner">
        <div class="cover-eyebrow">INNOVATION POTENTIAL ASSESSMENT</div>
        <div class="cover-english">INNOVATION<br/>POTENTIAL &amp;<br/>COMPREHENSIVE<br/>QUALITY</div>
        <div class="cover-rule"></div>
        <h1 class="cover-title">${esc(reportCoverTitle(sample))}</h1>
        <div class="cover-meta">
          <span>姓名</span><strong>${esc(reportSubjectLabel(sample))}</strong>
          ${numberLabel ? `<span>编号</span><strong>${esc(numberLabel)}</strong>` : ""}
          <span>测评日期</span><strong>${esc(reportDateLabel(sample))}</strong>
        </div>
      </main>
      <div class="cover-symbol">+</div>
    </section>
  `;
}

function parentGreeting(sample) {
  const profile = sample.respondent_profile || {};
  const label = profile.report_subject_label || profile.display_name || profile.child_display_name || "孩子";
  if (isSecondaryReport(sample)) {
    const studentLabel = String(label).endsWith("同学") ? String(label) : `${label}同学`;
    return `${studentLabel}，你好：`;
  }
  return `Hi，${label}的家长您好：`;
}

function studentMetaLine(sample) {
  const profile = sample.respondent_profile || {};
  const subjectLabel = profile.report_subject_label || profile.display_name || profile.child_display_name;
  const numberLabel = studentNumberLabel(sample);
  const items = numberLabel
    ? [subjectLabel, numberLabel].filter(Boolean)
    : [
        subjectLabel,
        profile.school,
        profile.grade || profile.age_group,
        profile.class_name || profile.class,
      ].filter(Boolean);
  return items.length > 1 ? items.join(" · ") : "";
}

function cleanPrefaceForFirstPage(text) {
  return cleanText(text)
    .replace(/^Hi[，,、\s]*[^：:\n]{0,30}[：:]\s*/i, "")
    .replace(/^尊敬的[^：:\n]{0,30}[：:]\s*/, "")
    .trim();
}

function firstPageParentIntro(sample) {
  if (isSecondaryReport(sample)) {
    return "这份报告帮助你定位当前的发展阶段，认识可以继续运用的资源，也看见值得练习的方向。阅读时，可以从中选出一种方法，在真实任务中试一试，并用结果判断下一步如何调整。";
  }
  return "这份报告帮助您了解孩子当前的发展位置，认识可以继续支持的资源，也看见值得温和练习的方向。阅读后，可以选择一个贴近日常的支持动作，并通过孩子后续的表现观察效果。";
}

function closingPreface(text, sample) {
  if (isSecondaryReport(sample)) {
    return "这份报告记录你现阶段在评估任务中的表现，不对能力和未来作固定结论。请选出一两种适合自己的方法，在学习和生活中试一试，再根据实际效果调整。";
  }
  return cleanPrefaceForFirstPage(text)
    || "感谢您对本次儿童创新潜能与综合素质评估的信任。本报告基于孩子在评估中的表现，概要呈现他当前的发展特点。孩子的成长是动态的，日常观察与亲子互动依然是了解他最宝贵的方式。";
}

function pageShell(theme, sample, title, subtitle, pageNo, content, options = {}) {
  const child = sample.respondent_profile || {};
  const pageClass = options.pageClass ? ` ${options.pageClass}` : "";
  const showKicker = options.showKicker !== false;
  const showSubtitle = options.showSubtitle !== false && subtitle;
  const pageTheme = options.pageTheme || theme;
  const pageStyle = styleVarsForTheme(pageTheme);
  const kicker = options.kicker || mainReportTitle(sample);
  return `
    <section class="page${pageClass}" style="${pageStyle}">
      <div class="top-band"></div>
      <main class="inner">
        ${showKicker ? `<div class="kicker">${esc(kicker)}</div>` : ""}
        <h1>${esc(title)}</h1>
        ${showSubtitle ? `<h2>${esc(subtitle)}</h2>` : ""}
        ${content}
      </main>
      <footer class="footer">
        <span>${esc(mainReportTitle(sample))} · ${esc(child.grade || child.age_group || "")}</span>
        <span>${String(pageNo).padStart(2, "0")}</span>
      </footer>
    </section>
  `;
}

function renderReport(sample, report, theme, meta) {
  if (theme.layout === "hybrid_expert_dashboard") {
    return renderHybridReport(sample, report, theme, meta);
  }

  const scores = getScores(sample);
  assertFixedNormChartContract(sample, scores);
  const core = section(report, "core_growth_portrait");
  const detail = section(report, "detailed_indicator_analysis");
  const support = section(report, "growth_support_suggestions");
  const boundary = section(report, "boundary_note");
  const details = splitDetailed(detail.body);
  const suggestions = report.parent_suggestions;
  const requiredSuggestionFields = [
    "category",
    "scene",
    "data_basis",
    "action",
    "parent_wording",
    "first_step",
  ];
  if (!Array.isArray(suggestions) || suggestions.length !== 3) {
    const count = Array.isArray(suggestions) ? suggestions.length : "非数组";
    throw new Error(
      `成长支持建议结构不完整：parent_suggestions 必须恰好为 3 条，当前为 ${count}。`,
    );
  }
  suggestions.forEach((item, index) => {
    const missing = requiredSuggestionFields.filter((field) => !String(item?.[field] || "").trim());
    if (missing.length) {
      throw new Error(
        `成长支持建议结构不完整：parent_suggestions[${index}] 缺少 ${missing.join(", ")}。`,
      );
    }
  });
  const readerLabels = reportReaderLabels(sample);
  const referenceLines = scoreReferenceLines(sample);
  const domains = domainSummary(scores);
  const strengths = scores.filter((s) => scoreRole(s) === "strength").slice(0, 4);
  const growth = scores.filter((s) => scoreRole(s) === "support").slice(0, 4);

  const pages = [];
  let pageNo = 1;

  pages.push(renderCoverPage(sample, theme));

  pages.push(pageShell(theme, sample, mainReportTitle(sample), reportSubjectLabel(sample), pageNo++, `
    <div class="lead">
      <p><strong>${esc(core.title || "核心成长画像")}：</strong>${esc(core.body)}</p>
    </div>
    <div class="chart-box">${renderMainChart(scores, theme, referenceLines)}</div>
    <div class="grid-2" style="margin-top:12px">
      <div class="card">
        <h3>主要优势</h3>
        ${strengths.length ? strengths.map((s) => `<span class="pill">${esc(s.name)} ${Math.round(s.score)}</span>`).join("") : "<p>整体较为均衡，暂无突出高分项。</p>"}
      </div>
      <div class="card">
        <h3>支持重点</h3>
        ${growth.length ? growth.map((s) => `<span class="pill">${esc(s.name)} ${Math.round(s.score)}</span>`).join("") : "<p>暂无明显潜力区，可从兴趣和日常坚持中继续巩固。</p>"}
      </div>
    </div>
  `));

  pages.push(pageShell(
    theme,
    sample,
    "分数概览",
    isSecondaryReport(sample) ? "先看见你当前的整体分布" : "用图表先看见孩子当前的整体分布",
    pageNo++,
    `
    <div class="chart-box">${barChart(scores, theme, referenceLines)}</div>
    <div class="grid-2" style="margin-top:12px">
      ${domains.slice(0, 6).map((d) => `
        <div class="plain-card">
          <h4>${esc(d.name)}</h4>
          <p>本模块包含 <strong>${d.count}</strong> 个相关指标，各指标分别保留原始分数位置。</p>
        </div>
      `).join("")}
    </div>
  `));

  const detailChunks = chunkDetailItems(details, theme);
  detailChunks.forEach((chunk, index) => {
    const detailHtml = chunk.map((item) => `
      <div class="plain-card detail-card">
        <h4>${esc(item.title)}</h4>
        ${paraHtml(item.body)}
      </div>
    `).join("");
    pages.push(pageShell(
      theme,
      sample,
      index === 0 ? (detail.title || "详细指标分析") : `${detail.title || "详细指标分析"}（续）`,
      isSecondaryReport(sample)
        ? "把分数翻译成你在学习和生活中可能遇到的真实任务"
        : "把分数翻译成家长能观察到的学习和生活表现",
      pageNo++,
      `<div class="detail-list">${detailHtml}</div>`,
    ));
  });

  let suggestionIndex = 0;
  groupSuggestionsByCategory(suggestions, sample).forEach((group, groupIndex) => {
    const suggestionChunks = chunkArray(group.items, 2);
    suggestionChunks.forEach((chunk, chunkIndex) => {
      const chunkStartIndex = suggestionIndex;
      const suggestionHtml = chunk.map((item, index) => {
        const globalIndex = chunkStartIndex + index;
      return `
        <section class="suggestion">
          <div class="suggestion-num">${globalIndex + 1}</div>
          <div class="plain-card">
            <h4>${esc(item.scene || `建议 ${globalIndex + 1}`)}</h4>
            ${readerLabels.action ? `<div class="mini-label">${esc(readerLabels.action)}</div>` : ""}
            <p>${esc(item.action || "")}</p>
            <div class="mini-label">数据依据</div>
            <p>${esc(item.data_basis || "")}</p>
            <div class="mini-label">${esc(readerLabels.collaboration)}</div>
            <p>${esc(item.parent_wording || "")}</p>
            <div class="mini-label">${esc(readerLabels.firstStep)}</div>
            <p>${esc(item.first_step || "")}</p>
          </div>
        </section>
      `;
      }).join("");
      suggestionIndex += chunk.length;
      pages.push(pageShell(
        theme,
        sample,
        `${support.title || "成长支持建议"} · ${group.category}${chunkIndex ? "（续）" : ""}`,
        `教育场景：${group.category}`,
        pageNo++,
        `
          <div class="scene-band"><span>适用场景</span><strong>${esc(group.category)}</strong></div>
          ${groupIndex === 0 && chunkIndex === 0 && support.body ? `<div class="module-note">${esc(support.body)}</div>` : ""}
          ${suggestionHtml}
        `,
      ));
    });
  });

  const appendixChunks = chunkArray(scores, 14);
  appendixChunks.forEach((chunk, index) => {
    pages.push(pageShell(
      theme,
      sample,
      index === 0 ? "分数依据与报告说明" : "分数依据与报告说明（续）",
      "保留可追溯信息，方便复核",
      pageNo++,
      `
        ${appendixTable(chunk)}
        ${index === appendixChunks.length - 1 ? `<div class="lead" style="margin-top:12px">${paraHtml(boundary.body)}</div>` : ""}
      `,
    ));
  });

  return `<!doctype html>
  <html lang="zh-CN">
  <head><meta charset="utf-8"/><title>${esc(reportSubjectLabel(sample))} - ${esc(mainReportTitle(sample))}</title><style>${baseCss(theme)}</style></head>
  <body>${pages.join("")}</body>
  </html>`;
}

function renderHybridReport(sample, report, theme, meta = {}) {
  const scores = getScores(sample);
  assertFixedNormChartContract(sample, scores);
  const core = section(report, "core_growth_portrait");
  const preface = section(report, "preface");
  const detail = section(report, "detailed_indicator_analysis");
  const support = section(report, "growth_support_suggestions");
  const boundary = section(report, "boundary_note");
  const details = splitDetailed(detail.body);
  const suggestions = report.parent_suggestions || [];
  const supportLayoutMode = meta.supportLayoutMode || "auto";
  let resolvedSupportLayoutMode = supportLayoutMode;
  const readerLabels = reportReaderLabels(sample);
  const referenceLines = scoreReferenceLines(sample);
  const domains = groupScoresByDomain(scores);
  const growth = scores.filter((s) => scoreRole(s) === "support").slice(0, 4);
  const supportScores = (growth.length ? growth : scores.slice().sort((a, b) => a.score - b.score).slice(0, 4));
  const usedDetails = new Set();

  const pages = [];
  let pageNo = 1;

  pages.push(renderCoverPage(sample, theme));

  const greeting = parentGreeting(sample);
  const metaLine = studentMetaLine(sample);
  const firstPagePreface = firstPageParentIntro(sample);
  const finalClosingText = closingPreface(preface.body, sample);
  const introBlock = `
    ${metaLine ? `<div class="student-line">${esc(metaLine)}</div>` : ""}
    <div class="first-page-intro">
      <p><strong>${esc(greeting)}</strong>${firstPagePreface ? ` ${esc(firstPagePreface)}` : ""}</p>
    </div>
  `;
  const overviewBlock = `
    <div class="chart-box">
      ${profileChart(scores, theme, referenceLines)}
    </div>
  `;
  const coreBlock = `
    <div class="lead">
      <h3>${esc((core.title || "综合画像").replace("核心成长画像", "综合画像"))}</h3>
      ${paraHtml(core.body)}
    </div>
  `;

  pages.push(pageShell(
    theme,
    sample,
    mainReportTitle(sample),
    "",
    pageNo++,
    `${introBlock}${overviewBlock}${coreBlock}`,
    { pageClass: "first-page", showKicker: false, showSubtitle: false },
  ));

  domains.forEach((domain) => {
    const matchedDetails = detailsForScores(details, domain.items, usedDetails);
    const domainBlocks = [{ type: "module-start", domain, title: `${domain.name}模块解读` }];
    if (matchedDetails.length) {
      matchedDetails.forEach((item) => domainBlocks.push({ type: "detail-card", domain, item }));
    } else {
      domainBlocks.push({
        type: "detail-card",
        domain,
        item: {
          title: `${domain.name}模块`,
          body: "该模块本页先展示数据位置。后续可以继续补充更细的行为解释。",
        },
      });
    }
    const pageTheme = themeForDomain(theme, domain.name);
    packModulePages(domainBlocks, theme, { fillBlankWithIllustration: true }).forEach((packedPage) => {
      const html = packedPage.blocks.map((block, index) => renderModuleFlowBlock(
        block,
        pageTheme,
        referenceLines,
        sample,
        index === 0,
      )).join("");
      pages.push(pageShell(
        theme,
        sample,
        packedPage.title,
        "",
        pageNo++,
        html,
        { pageTheme },
      ));
    });
  });

  const suggestionCategories = [...new Set(suggestions.map((item) => item.category).filter(Boolean))];
  const buildSupportBlocks = (hideSupportWording) => {
    if (!suggestions.length && !support.body) return [];
    return [
      {
        type: "support-start",
        title: support.title || "成长支持建议",
        subtitle: suggestionCategories.length
          ? suggestionCategories.join(" · ")
          : (isSecondaryReport(sample) ? "给自己的行动建议" : "给家长的日常行动建议"),
        body: support.body || preface.body || readerLabels.supportIntro,
      },
      ...suggestions.map((item, index) => ({
        type: "suggestion-card",
        item,
        index,
        hideSupportWording,
      })),
      {
        type: "support-closing-note",
        title: "报告结束语",
        body: finalClosingText,
      },
    ];
  };
  const splitSupportPages = (blocks) => [
    {
      title: support.title || "成长支持建议",
      blocks: blocks.slice(0, 3),
    },
    {
      title: `${support.title || "成长支持建议"}（续）`,
      blocks: blocks.slice(3),
    },
  ];
  let supportBlocks = buildSupportBlocks(supportLayoutMode !== "two-plus-one");
  if (supportBlocks.length) {
    let packedSupportPages;
    if (supportLayoutMode === "two-plus-one" && suggestions.length === 3) {
      packedSupportPages = splitSupportPages(supportBlocks);
    } else {
      packedSupportPages = packModulePages(supportBlocks, theme);
      if (supportLayoutMode === "auto") {
        if (packedSupportPages.length === 1) {
          resolvedSupportLayoutMode = "no-support-wording";
        } else if (suggestions.length === 3) {
          supportBlocks = buildSupportBlocks(false);
          packedSupportPages = splitSupportPages(supportBlocks);
          resolvedSupportLayoutMode = "two-plus-one";
        } else {
          resolvedSupportLayoutMode = "auto-multipage";
        }
      }
    }
    packedSupportPages.forEach((packedPage) => {
      const html = packedPage.blocks.map((block, index) => renderModuleFlowBlock(
        block,
        theme,
        referenceLines,
        sample,
        index === 0,
      )).join("");
    pages.push(pageShell(
      theme,
      sample,
      packedPage.title,
      "",
      pageNo++,
      html,
      { pageClass: "support-page" },
    ));
    });
  }

  const leftoverDetails = details.filter((item) => !usedDetails.has(item));
  const leftoverChunks = chunkDetailItems(leftoverDetails, { ...theme, density: "balanced" });
  leftoverChunks.forEach((chunk, index) => {
    if (!chunk.length) return;
    pages.push(pageShell(
      theme,
      sample,
      index === 0 ? "补充指标解读" : "补充指标解读（续）",
      "未能自动归入模块的文字，仍保持先图后文的阅读顺序",
      pageNo++,
      `
        <div class="chart-box">
          ${barChart(scores, theme, referenceLines)}
          <div class="figure-caption">补充页保留完整分数分布，便于核对文字解释与数据是否一致。</div>
        </div>
        <div class="detail-list" style="margin-top:12px">
          ${chunk.map((item) => `
            <div class="plain-card detail-card">
              <h4>${esc(item.title)}</h4>
              ${paraHtml(item.body)}
            </div>
          `).join("")}
        </div>
      `,
    ));
  });

  return `<!doctype html>
  <html lang="zh-CN">
  <head><meta charset="utf-8"/><title>${esc(reportSubjectLabel(sample))} - ${esc(mainReportTitle(sample))}</title><style>${baseCss(theme)}</style></head>
  <body data-support-layout="${esc(resolvedSupportLayoutMode)}">${pages.join("")}</body>
  </html>`;
}

function renderScoreAppendixReport(sample, report, theme) {
  const scores = getScores(sample);
  assertFixedNormChartContract(sample, scores);
  const boundary = section(report, "boundary_note");
  const pages = [];
  let pageNo = 1;

  chunkArray(scores, 14).forEach((chunk, index, chunks) => {
    const isLast = index === chunks.length - 1;
    pages.push(pageShell(
      theme,
      sample,
      index === 0 ? "分数依据与报告说明" : "分数依据与报告说明（续）",
      index === 0 ? "独立附件 · 保留可追溯信息，方便专业复核" : "",
      pageNo++,
      `
        ${appendixTable(chunk)}
        ${isLast && boundary.body ? `<div class="lead" style="margin-top:12px">${paraHtml(boundary.body)}</div>` : ""}
      `,
    ));
  });

  return `<!doctype html>
  <html lang="zh-CN">
  <head><meta charset="utf-8"/><title>${esc(reportSubjectLabel(sample))} - 分数依据附件</title><style>${baseCss(theme)}</style></head>
  <body>${pages.join("")}</body>
  </html>`;
}

// Keep a conservative content budget so a card never reaches the footer.
// A continuation page is preferable to clipped report content.
const MODULE_PAGE_BUDGET = 860;
const MODULE_ILLUSTRATION_MIN_SPACE = 280;

function modulePageTitleFor(block, continuation = false) {
  if (block.type === "support-start") return block.title || "成长支持建议";
  if (block.type === "suggestion-card") return `成长支持建议${continuation ? "（续）" : ""}`;
  if (block.type === "support-closing-note") return `成长支持建议${continuation ? "（续）" : ""}`;
  if (block.type === "appendix-table") return block.title || `分数依据与报告说明${continuation ? "（续）" : ""}`;
  if (block.type === "closing-note") return block.title || "报告结束语";
  const domainName = block.domain?.name || "指标";
  if (block.type === "module-start") return `${domainName}模块解读`;
  return `${domainName}模块解读${continuation ? "（续）" : ""}`;
}

function estimateModuleBlockHeight(block, isFirstOnPage) {
  if (block.type === "module-start") {
    const count = block.domain?.items?.length || 1;
    const chartHeight = Math.max(200, 126 + count * 22);
    return chartHeight + (isFirstOnPage ? 0 : 58);
  }
  if (block.type === "support-start") {
    return 74 + (isFirstOnPage ? 0 : 58) + Math.ceil(String(block.body || "").length / 62) * 15;
  }
  if (block.type === "suggestion-card") {
    const item = block.item || {};
    const length = [
      item.category,
      item.scene,
      item.action,
      item.data_basis,
      block.hideSupportWording ? "" : item.parent_wording,
      item.first_step,
    ].join("").length;
    return 126 + Math.ceil(length / 55) * 15;
  }
  if (block.type === "appendix-table") {
    const rows = block.rows || [];
    const heading = block.subtitle || block.title ? (isFirstOnPage ? 0 : 48) : 0;
    return heading + 70 + rows.length * 43;
  }
  if (block.type === "closing-note") {
    return 132 + Math.ceil(String(block.body || "").length / 58) * 17;
  }
  if (block.type === "support-closing-note") {
    return 82 + Math.ceil(String(block.body || "").length / 74) * 14;
  }
  if (block.type === "illustration") {
    return Number.isFinite(block.height) ? block.height : 320;
  }
  const bodyLength = String(block.item?.body || "").length;
  const titleLength = String(block.item?.title || "").length;
  return 68 + Math.ceil((bodyLength + titleLength * 1.4) / 38) * 17;
}

function packModulePages(blocks, theme, options = {}) {
  const pages = [];
  let current = [];
  let currentHeight = 0;
  let currentTitle = "";

  const flush = () => {
    if (!current.length) return;
    const firstDomain = current.find((block) => block.domain)?.domain;
    const hasIllustration = current.some((block) => block.type === "illustration");
    const availableHeight = MODULE_PAGE_BUDGET - currentHeight;
    const canFill = options.fillBlankWithIllustration
      && firstDomain
      && !hasIllustration
      && availableHeight >= MODULE_ILLUSTRATION_MIN_SPACE;
    if (canFill) {
      const detailCount = current.filter((block) => block.type === "detail-card").length;
      const heightCeiling = detailCount <= 1 ? 420 : detailCount === 2 ? 330 : 280;
      current.push({
        type: "illustration",
        domain: firstDomain,
        height: Math.max(272, Math.min(heightCeiling, availableHeight - 28)),
      });
    }
    pages.push({ title: currentTitle || modulePageTitleFor(current[0], false), blocks: current });
    current = [];
    currentHeight = 0;
    currentTitle = "";
  };

  blocks.forEach((block) => {
    const blockHeight = estimateModuleBlockHeight(block, current.length === 0);
    if (current.length && currentHeight + blockHeight > MODULE_PAGE_BUDGET) {
      flush();
    }
    if (!current.length) {
      currentTitle = modulePageTitleFor(block, block.type !== "module-start");
    }
    current.push(block);
    currentHeight += estimateModuleBlockHeight(block, current.length === 1);
  });
  flush();
  return pages;
}

function renderModuleFlowBlock(block, theme, referenceLines, sample, isFirstOnPage) {
  const readerLabels = reportReaderLabels(sample);
  if (block.type === "module-start") {
    const heading = isFirstOnPage ? "" : `<div class="flow-module-heading">${esc(block.title)}</div>`;
    return `
      ${heading}
      <div class="chart-box">
        ${moduleDashboardChart(block.domain.items, theme, block.domain.name, referenceLines)}
      </div>
    `;
  }
  if (block.type === "illustration") {
    return moduleIllustration(block.domain, theme, block.height, sample);
  }
  if (block.type === "support-start") {
    const heading = isFirstOnPage ? "" : `<div class="flow-module-heading">${esc(block.title || "成长支持建议")}</div>`;
    return `
      ${heading}
      <div class="module-note">${esc(block.body || readerLabels.supportIntro)}</div>
    `;
  }
  if (block.type === "suggestion-card") {
    const item = block.item || {};
    const title = [item.category, item.scene].filter(Boolean).join(" · ") || `建议 ${block.index + 1}`;
    const supportWordingHtml = block.hideSupportWording
      ? ""
      : `
        <div class="mini-label">${esc(readerLabels.collaboration)}</div>
        <p>${esc(item.parent_wording || "")}</p>
      `;
    return `
      <div class="compact-suggestion">
        <section class="suggestion">
          <div class="suggestion-num">${block.index + 1}</div>
          <div class="plain-card">
            <h4>${esc(title)}</h4>
            ${readerLabels.action ? `<div class="mini-label">${esc(readerLabels.action)}</div>` : ""}
            <p>${esc(item.action || "")}</p>
            <div class="mini-label">数据依据</div>
            <p>${esc(item.data_basis || "")}</p>
            ${supportWordingHtml}
            <div class="mini-label">${esc(readerLabels.firstStep)}</div>
            <p>${esc(item.first_step || "")}</p>
          </div>
        </section>
      </div>
    `;
  }
  if (block.type === "appendix-table") {
    const heading = isFirstOnPage ? "" : `<div class="flow-appendix-heading">${esc(block.title || "分数依据与报告说明")}</div>`;
    const subtitle = block.subtitle && !isFirstOnPage ? `<h3>${esc(block.subtitle)}</h3>` : "";
    return `
      ${heading}
      ${subtitle}
      ${appendixTable(block.rows || [])}
    `;
  }
  if (block.type === "closing-note") {
    const heading = isFirstOnPage ? "" : `<div class="flow-appendix-heading">${esc(block.title || "报告结束语")}</div>`;
    return `
      ${heading}
      <div class="lead" style="margin-top:12px">${paraHtml(block.body)}</div>
    `;
  }
  if (block.type === "support-closing-note") {
    return `
      <div class="support-closing-note">
        <strong>${esc(block.title || "报告结束语")}</strong>
        ${paraHtml(block.body)}
      </div>
    `;
  }
  return metricDetailCard(block.item, theme);
}

function splitMetricBody(body) {
  const text = cleanText(body);
  const markers = [
    "本项得分",
    "按本次评估",
    "按本次测评",
    "结合本次评估",
    "结合本项",
    "从本次评估",
    "本次结果",
    "孩子当前",
    "你当前",
  ];
  const positions = markers
    .map((marker) => text.indexOf(marker))
    .filter((position) => position > 0);
  const splitAt = positions.length ? Math.min(...positions) : -1;
  if (splitAt > 0) {
    return {
      definition: text.slice(0, splitAt).trim(),
      analysis: text.slice(splitAt).trim(),
    };
  }

  const firstSentenceEnd = text.indexOf("。") + 1;
  return {
    definition: firstSentenceEnd > 0 ? text.slice(0, firstSentenceEnd).trim() : text,
    analysis: firstSentenceEnd > 0 ? text.slice(firstSentenceEnd).trim() : "",
  };
}

function metricIconKind(title) {
  const name = displayMetricName(title);
  const rules = [
    [/Nogo/i, "stop"],
    [/抑制控制go|go$/i, "play"],
    [/表演/, "drama"],
    [/文学/, "book"],
    [/设计/, "blocks"],
    [/科学/, "flask"],
    [/社会/, "users"],
    [/兴趣好奇心/, "search"],
    [/问题好奇心/, "question"],
    [/思维流畅/, "wind"],
    [/思维灵活/, "shuffle"],
    [/思维独创/, "sparkles"],
    [/思维聚合/, "funnel"],
    [/认知灵活/, "repeat"],
    [/规则抽象/, "grid"],
    [/学习速度/, "zap"],
    [/注意稳定/, "target"],
    [/整体执行/, "checklist"],
    [/逻辑推理/, "network"],
    [/学习乐趣/, "smile"],
    [/学校归属/, "school"],
    [/学习意义/, "compass"],
    [/学习自信/, "shield"],
    [/积极情绪/, "sun"],
    [/负性情绪/, "cloud"],
    [/情感平衡/, "balance"],
  ];
  return rules.find(([pattern]) => pattern.test(name))?.[1] || "circle";
}

function metricIconSvg(title) {
  const drawings = {
    drama: '<path d="M4 6h16v9a8 8 0 0 1-16 0z"/><path d="M8 10h.01M16 10h.01M8.5 15c2 2 5 2 7 0"/>',
    book: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H11v16H6.5A2.5 2.5 0 0 0 4 21.5z"/><path d="M20 5.5A2.5 2.5 0 0 0 17.5 3H13v16h4.5a2.5 2.5 0 0 1 2.5 2.5z"/>',
    blocks: '<path d="M4 14h6v6H4zM14 14h6v6h-6zM9 4h6v6H9z"/>',
    flask: '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.7 3h10.6a2 2 0 0 0 1.7-3l-5-9V3"/><path d="M7.5 15h9"/>',
    users: '<circle cx="9" cy="8" r="3"/><circle cx="17" cy="9" r="2"/><path d="M3 20c0-4 2.5-6 6-6s6 2 6 6M15 15c3 0 5 1.5 5 4"/>',
    search: '<circle cx="10" cy="10" r="6"/><path d="m14.5 14.5 5 5M10 7v6M7 10h6"/>',
    question: '<path d="M9.5 9a3 3 0 1 1 4.5 2.6c-1.3.7-2 1.2-2 2.4M12 18h.01"/><circle cx="12" cy="12" r="9"/>',
    wind: '<path d="M3 8h11a3 3 0 1 0-3-3M3 12h16M3 16h11a3 3 0 1 1-3 3"/>',
    shuffle: '<path d="M16 3h5v5M4 20 21 3M21 16v5h-5M4 4l5 5M15 15l6 6"/>',
    sparkles: '<path d="m12 3 1.4 3.6L17 8l-3.6 1.4L12 13l-1.4-3.6L7 8l3.6-1.4zM5 14l.8 2.2L8 17l-2.2.8L5 20l-.8-2.2L2 17l2.2-.8zM19 14l.7 1.8 1.8.7-1.8.7L19 19l-.7-1.8-1.8-.7 1.8-.7z"/>',
    funnel: '<path d="M3 5h18l-7 8v6l-4 2v-8z"/>',
    repeat: '<path d="m17 2 4 4-4 4M3 11V9a3 3 0 0 1 3-3h15M7 22l-4-4 4-4M21 13v2a3 3 0 0 1-3 3H3"/>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 17.5h7M17.5 14v7"/>',
    zap: '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
    target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
    checklist: '<path d="m4 6 2 2 3-4M11 6h9M4 13l2 2 3-4M11 13h9M4 20l2 2 3-4M11 20h9"/>',
    stop: '<path d="M8 3h8l5 5v8l-5 5H8l-5-5V8z"/><path d="M8 12h8"/>',
    play: '<circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4z"/>',
    network: '<circle cx="5" cy="6" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="12" cy="18" r="2"/><path d="m7 7 4 9M17 7l-4 9M7 6h10"/>',
    smile: '<circle cx="12" cy="12" r="9"/><path d="M8 10h.01M16 10h.01M8 15c2 2 6 2 8 0"/>',
    school: '<path d="M3 21h18M5 21V9l7-5 7 5v12M9 21v-6h6v6M8 10h.01M16 10h.01"/>',
    compass: '<circle cx="12" cy="12" r="9"/><path d="m15 9-2 4-4 2 2-4z"/>',
    shield: '<path d="M12 3 5 6v5c0 5 3 8 7 10 4-2 7-5 7-10V6z"/><path d="m9 12 2 2 4-4"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    cloud: '<path d="M6 18h11a4 4 0 0 0 .5-8 6 6 0 0 0-11.4 2A3 3 0 0 0 6 18z"/><path d="m9 20-1 2M14 20l-1 2"/>',
    balance: '<path d="M12 3v18M5 6h14M7 6l-4 8h8zM17 6l-4 8h8zM8 21h8"/>',
    circle: '<circle cx="12" cy="12" r="9"/><path d="M8 12h8M12 8v8"/>',
  };
  return `<svg viewBox="0 0 24 24" aria-hidden="true">${drawings[metricIconKind(title)] || drawings.circle}</svg>`;
}

function metricDetailCard(item, theme) {
  const { definition, analysis } = splitMetricBody(item.body);
  return `
    <div class="plain-card detail-card metric-card">
      <div class="metric-card-top">
        <div class="metric-card-title">
          <span class="metric-card-logo">${metricIconSvg(item.title)}</span>
          <span class="metric-card-name">${esc(displayMetricName(item.title))}</span>
        </div>
        <div class="metric-card-definition">
          <p>${esc(definition)}</p>
        </div>
      </div>
      <div class="metric-card-analysis">
        <span class="metric-card-label">结果分析</span>
        ${analysis ? paraHtml(analysis) : "<p>本项结果可结合上方图表与日常观察综合理解。</p>"}
      </div>
    </div>
  `;
}

function reportIllustrationDataUrl(domainName, sample = {}) {
  const stageKey = isSecondaryReport(sample) ? "secondary" : "elementary";
  const stageFiles = REPORT_ILLUSTRATION_FILES[stageKey];
  const key = Object.keys(stageFiles).find((name) => String(domainName || "").includes(name));
  if (!key) return "";
  const cacheKey = `${stageKey}:${key}`;
  if (illustrationDataUrlCache.has(cacheKey)) return illustrationDataUrlCache.get(cacheKey);
  const imagePath = path.join(REPORT_ILLUSTRATION_DIR, stageFiles[key]);
  if (!fs.existsSync(imagePath)) return "";
  const dataUrl = `data:image/png;base64,${fs.readFileSync(imagePath).toString("base64")}`;
  illustrationDataUrlCache.set(cacheKey, dataUrl);
  return dataUrl;
}

function moduleIllustration(domain, theme, height = 320, sample = {}) {
  const name = String(domain?.name || "成长");
  const text = domainIllustrationText(name, sample);
  const imageDataUrl = reportIllustrationDataUrl(name, sample);
  const art = imageDataUrl
    ? `<img src="${imageDataUrl}" alt="${esc(name)}模块主题插图"/>`
    : domainIllustrationSvg(name, theme);
  return `
    <div class="illustration-card" style="--illustration-height:${Math.max(280, Math.min(440, Number(height) || 320))}px">
      <div class="illustration-art">${art}</div>
      <div class="illustration-copy" style="background:${theme.soft};border-left-color:${theme.line}">
        <strong>${esc(text.title)}</strong>
        <p>${esc(text.body)}</p>
      </div>
    </div>
  `;
}

function domainIllustrationText(domainName, sample = {}) {
  if (isSecondaryReport(sample)) {
    if (domainName.includes("创新")) {
      return { title: "把想法变成一次真实尝试", body: "这一模块帮助你看见自己在表达、设计、科学探究和协作解决问题时，怎样把想法推进为方案与作品。" };
    }
    if (domainName.includes("好奇")) {
      return { title: "从感兴趣走向继续追问", body: "这一模块关注你面对新信息时的敏感度、提问意愿，以及能否把一个问题继续查下去。" };
    }
    if (domainName.includes("思维")) {
      return { title: "比较线索，再形成自己的判断", body: "这一模块关注你产生想法、转换角度、提出新方案并把多条线索组织成答案的方式。" };
    }
    if (domainName.includes("认知")) {
      return { title: "找到适合自己的任务推进方法", body: "这一模块关注你在学习任务中维持注意、理解规则、启动行动、检查步骤和调整节奏的能力。" };
    }
    if (domainName.includes("情绪")) {
      return { title: "在压力和波动中恢复状态", body: "这一模块关注你的学习感受、积极体验、压力调节，以及在受挫后重新投入任务的能力。" };
    }
    return { title: "把结果变成可尝试的方法", body: "图表提供阶段性位置，文字帮助你理解这些表现可能怎样出现在学习、探索和自我管理中。" };
  }
  if (domainName.includes("创新")) {
    return { title: "把想法变成可见作品", body: "这一模块关注孩子在表达、设计、科学探究和社会问题解决中的创造性资源。" };
  }
  if (domainName.includes("好奇")) {
    return { title: "保持提问和探索的入口", body: "这一模块关注孩子面对新信息时的敏感度、追问意愿和主动探索习惯。" };
  }
  if (domainName.includes("思维")) {
    return { title: "从多个角度组织答案", body: "这一模块关注孩子产生想法、转换思路、提出新颖答案和聚合线索的方式。" };
  }
  if (domainName.includes("认知")) {
    return { title: "让注意、规则和执行形成配合", body: "这一模块关注孩子在任务中保持专注、理解规则、调节行为和推进步骤的能力。" };
  }
  if (domainName.includes("情绪")) {
    return { title: "在学习压力中保留恢复力", body: "这一模块关注孩子的学习感受、积极体验、压力调节和情绪平衡状态。" };
  }
  return { title: "把测评结果放回日常情境", body: "图表提供位置，文字帮助家长理解孩子在真实学习和生活中的表现。" };
}

function domainIllustrationSvg(domainName, theme) {
  const primary = theme.primary;
  const soft = theme.soft;
  const dark = theme.primaryDark;
  const icon = domainName.includes("创新")
    ? `<path d="M78 84c18-18 48-18 66 0M86 112h50M96 140h30" fill="none" stroke="${primary}" stroke-width="8" stroke-linecap="round"/><circle cx="112" cy="58" r="24" fill="${soft}" stroke="${primary}" stroke-width="7"/>`
    : domainName.includes("好奇")
      ? `<circle cx="102" cy="92" r="34" fill="${soft}" stroke="${primary}" stroke-width="8"/><path d="M128 118l30 30M96 83c8-14 28-12 32 4 4 17-15 20-15 34" fill="none" stroke="${primary}" stroke-width="8" stroke-linecap="round"/><circle cx="113" cy="138" r="4" fill="${primary}"/>`
      : domainName.includes("思维")
        ? `<path d="M64 134c22-50 74-74 114-34M70 92c34-20 72-18 104 8M92 60c28 6 52 22 70 48" fill="none" stroke="${primary}" stroke-width="8" stroke-linecap="round"/><circle cx="70" cy="134" r="8" fill="${dark}"/><circle cx="174" cy="102" r="8" fill="${dark}"/>`
        : domainName.includes("认知")
          ? `<rect x="58" y="58" width="116" height="96" rx="18" fill="${soft}" stroke="${primary}" stroke-width="8"/><path d="M84 88h62M84 112h62M84 136h38" stroke="${primary}" stroke-width="8" stroke-linecap="round"/><path d="M154 132l12 12 26-30" fill="none" stroke="${dark}" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>`
          : `<path d="M116 158c-42-30-62-55-62-80 0-22 16-38 36-38 12 0 21 6 26 15 5-9 14-15 26-15 20 0 36 16 36 38 0 25-20 50-62 80z" fill="${soft}" stroke="${primary}" stroke-width="8"/><path d="M82 98h22l10-18 18 44 10-26h24" fill="none" stroke="${dark}" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>`;
  return `
    <svg viewBox="0 0 220 190" aria-hidden="true">
      <rect x="16" y="16" width="188" height="158" rx="24" fill="#fff" stroke="${theme.line}" stroke-width="3"/>
      ${icon}
    </svg>
  `;
}

function chunkArray(items, size) {
  const chunks = [];
  for (let index = 0; index < items.length; index += size) {
    chunks.push(items.slice(index, index + size));
  }
  return chunks.length ? chunks : [[]];
}

const ELEMENTARY_SUGGESTION_CATEGORY_ORDER = [
  "学习与日常",
  "课外与探索",
  "亲子互动与沟通",
];

const SECONDARY_SUGGESTION_CATEGORY_ORDER = [
  "自我成长与学习规划",
  "兴趣探索与项目实践",
  "生涯启发与发展规划",
];

function groupSuggestionsByCategory(suggestions, sample = {}) {
  const categoryOrder = isSecondaryReport(sample)
    ? SECONDARY_SUGGESTION_CATEGORY_ORDER
    : ELEMENTARY_SUGGESTION_CATEGORY_ORDER;
  const groups = new Map(categoryOrder.map((category) => [category, []]));
  const fallback = [];
  suggestions.forEach((item) => {
    const category = String(item.category || "").trim();
    if (groups.has(category)) {
      groups.get(category).push(item);
    } else {
      fallback.push(item);
    }
  });
  const result = categoryOrder
    .map((category) => ({ category, items: groups.get(category) }))
    .filter((group) => group.items.length);
  if (fallback.length) result.push({ category: "场景分类待修订", items: fallback });
  return result;
}

function chunkDetailItems(items, theme) {
  const maxChars = theme.density === "airy" ? 700 : theme.density === "compact" ? 900 : 860;
  const maxItems = theme.density === "airy" ? 4 : theme.density === "compact" ? 5 : 4;
  const chunks = [];
  let current = [];
  let currentChars = 0;

  items.forEach((item) => {
    const length = item.title.length + item.body.length;
    if (current.length && (current.length >= maxItems || currentChars + length > maxChars)) {
      chunks.push(current);
      current = [];
      currentChars = 0;
    }
    current.push(item);
    currentChars += length;
  });

  if (current.length) chunks.push(current);
  if (chunks.length > 1 && chunks[chunks.length - 1].length === 1) {
    const previous = chunks[chunks.length - 2];
    if (previous.length > 2) {
      chunks[chunks.length - 1].unshift(previous.pop());
    }
  }
  return chunks.length ? chunks : [[]];
}

function appendixTable(scores) {
  const rows = scores.map((s) => `
    <tr>
      <td>${esc(s.name)}</td>
      <td>${esc(s.domain)}</td>
      <td>${Math.round(s.score)}</td>
      <td>${esc(band(s.score, s.level, s.percentile))}</td>
      <td>${esc(peerRankLabel(s))}</td>
      <td>${esc(cleanText(s.interpretation))}</td>
    </tr>
  `).join("");
  return `
    <table class="appendix-table">
      <thead><tr><th>指标</th><th>领域</th><th>分数</th><th>水平</th><th>同伴位置</th><th>解释</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

async function renderOne(browser, htmlPath, pdfPath, pngPath, html, options = {}) {
  writeText(htmlPath, html);
  const page = await browser.newPage({ viewport: { width: 1240, height: 1754 }, deviceScaleFactor: 1 });
  await page.goto(`file://${htmlPath}`);
  const reportPages = page.locator(".page");
  const pageCount = await reportPages.count();
  const supportLayout = await page.locator("body").getAttribute("data-support-layout");
  const supportOverflow = await page.locator(".support-page").evaluateAll((supportPages) => supportPages.some((supportPage) => {
    const inner = supportPage.querySelector(".inner");
    if (!inner) return false;
    return inner.scrollHeight > inner.clientHeight + 2;
  }));
  await page.pdf({
    path: pdfPath,
    format: "A4",
    printBackground: true,
    margin: { top: "0", right: "0", bottom: "0", left: "0" },
  });
  const firstPage = reportPages.first();
  await firstPage.screenshot({ path: pngPath });
  const pageCheckDir = path.join(path.dirname(pngPath), options.pageCheckDirName || "page_checks");
  fs.mkdirSync(pageCheckDir, { recursive: true });
  const pageCheckPaths = [];
  for (let index = 0; index < pageCount; index += 1) {
    const pageCheckPath = path.join(pageCheckDir, `page_${String(index + 1).padStart(2, "0")}.png`);
    await reportPages.nth(index).screenshot({ path: pageCheckPath });
    pageCheckPaths.push(pageCheckPath);
  }
  await page.close();
  return { pageCount, pageCheckPaths, supportLayout, supportOverflow };
}

function makeIndex(outputs) {
  const themeCount = new Set(outputs.map((item) => item.theme)).size;
  const sampleCount = new Set(outputs.map((item) => item.sample)).size;
  const cards = outputs.map((item) => `
    <a class="item" href="${esc(path.relative(path.dirname(item.indexPath), item.pdfPath).replace(/\\/g, "/"))}">
      <img src="${esc(path.relative(path.dirname(item.indexPath), item.pngPath).replace(/\\/g, "/"))}" />
      <div><strong>${esc(item.sampleLabel)}</strong><span>${esc(item.themeLabel)}</span></div>
    </a>
  `).join("");
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"/><title>Report Design Variants</title>
  <style>
    body{font-family:"Microsoft YaHei",Arial,sans-serif;margin:0;background:#f3f4f6;color:#1f2933}
    header{padding:28px 34px;background:#1f2933;color:white}
    h1{margin:0;font-size:26px}p{margin:8px 0 0;color:#d6dde5}
    main{padding:26px 34px;display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:18px}
    .item{display:block;background:white;border:1px solid #dfe4ea;border-radius:8px;overflow:hidden;text-decoration:none;color:#1f2933}
    img{width:100%;display:block;background:#ddd}
    .item div{padding:12px 14px}.item strong{display:block;font-size:14px}.item span{display:block;color:#667085;font-size:12px;margin-top:4px}
  </style></head><body><header><h1>儿童报告 PDF 设计原型对比</h1><p>共 ${sampleCount} 个样本、${themeCount} 套主题，生成 ${outputs.length} 份完整 PDF。点击卡片打开 PDF。</p></header><main>${cards}</main></body></html>`;
}

function listTxtSamples(textDir) {
  return fs.readdirSync(textDir)
    .filter((name) => /^sample_.*\.txt$/.test(name))
    .sort()
    .map((name) => path.join(textDir, name));
}

async function main() {
  const textDir = path.resolve(process.argv[2] || DEFAULT_TEXT_DIR);
  const sampleDir = path.resolve(process.argv[3] || DEFAULT_SAMPLE_DIR);
  const outputDir = path.resolve(process.argv[4] || DEFAULT_OUTPUT_DIR);
  const requestedThemes = process.argv[5]
    ? new Set(process.argv[5].split(",").map((name) => name.trim()).filter(Boolean))
    : null;
  const supportLayoutMode = process.argv[6] || "auto";
  const supportedLayoutModes = new Set(["auto", "two-plus-one", "no-support-wording"]);
  if (!supportedLayoutModes.has(supportLayoutMode)) {
    throw new Error(
      `Unsupported support layout mode: ${supportLayoutMode}. `
      + `Available modes: ${[...supportedLayoutModes].join(", ")}`,
    );
  }
  const selectedThemes = Object.entries(THEMES).filter(([themeName]) => !requestedThemes || requestedThemes.has(themeName));
  if (!selectedThemes.length) {
    throw new Error(`No matching themes. Available themes: ${Object.keys(THEMES).join(", ")}`);
  }
  fs.mkdirSync(outputDir, { recursive: true });

  const txtPaths = listTxtSamples(textDir);
  if (!txtPaths.length) {
    throw new Error(`No sample txt files found: ${textDir}`);
  }

  const browser = await chromium.launch({ headless: true });
  const outputs = [];

  for (const txtPath of txtPaths) {
    const stem = path.basename(txtPath, ".txt");
    const samplePath = path.join(sampleDir, `${stem}.json`);
    if (!fs.existsSync(samplePath)) {
      console.warn(`Missing sample json for ${stem}, skipping.`);
      continue;
    }
    const sample = readJson(samplePath);
    const report = parseFinalReport(txtPath);
    const sampleOutDir = path.join(outputDir, stem);
    fs.mkdirSync(sampleOutDir, { recursive: true });

    for (const [themeName, theme] of selectedThemes) {
      const reportMeta = {
        sampleName: stem,
        sampleLabel: reportIndexLabel(sample, samplePath),
        supportLayoutMode,
      };
      let html = renderReport(sample, report, theme, reportMeta);
      const htmlPath = path.join(sampleOutDir, `${themeName}.html`);
      const pdfPath = path.join(sampleOutDir, `${themeName}.pdf`);
      const pngPath = path.join(sampleOutDir, `${themeName}.png`);
      let renderResult = await renderOne(browser, htmlPath, pdfPath, pngPath, html);
      if (
        supportLayoutMode === "auto"
        && renderResult.supportLayout === "no-support-wording"
        && renderResult.supportOverflow
        && theme.layout === "hybrid_expert_dashboard"
      ) {
        html = renderReport(sample, report, theme, {
          ...reportMeta,
          supportLayoutMode: "two-plus-one",
        });
        renderResult = await renderOne(browser, htmlPath, pdfPath, pngPath, html);
      }
      if (supportLayoutMode === "auto" && renderResult.supportOverflow) {
        throw new Error(
          `Support pages still overflow after automatic fallback: ${stem}/${themeName}`,
        );
      }
      outputs.push({
        sample: stem,
        sampleLabel: reportIndexLabel(sample, samplePath),
        theme: themeName,
        themeLabel: theme.label,
        documentType: "report",
        htmlPath,
        pdfPath,
        pngPath,
        pageCount: renderResult.pageCount,
        pageCheckPaths: renderResult.pageCheckPaths,
        supportLayout: renderResult.supportLayout,
      });

      if (theme.layout === "hybrid_expert_dashboard") {
        const appendixStem = `${themeName}_score_appendix`;
        const appendixHtmlPath = path.join(sampleOutDir, `${appendixStem}.html`);
        const appendixPdfPath = path.join(sampleOutDir, `${appendixStem}.pdf`);
        const appendixPngPath = path.join(sampleOutDir, `${appendixStem}.png`);
        const appendixHtml = renderScoreAppendixReport(sample, report, theme);
        const appendixRenderResult = await renderOne(
          browser,
          appendixHtmlPath,
          appendixPdfPath,
          appendixPngPath,
          appendixHtml,
          { pageCheckDirName: "score_appendix_page_checks" },
        );
        outputs.push({
          sample: stem,
          sampleLabel: `${reportIndexLabel(sample, samplePath)} · 分数依据附件`,
          theme: appendixStem,
          themeLabel: "分数依据与报告说明（独立附件）",
          documentType: "score_appendix",
          htmlPath: appendixHtmlPath,
          pdfPath: appendixPdfPath,
          pngPath: appendixPngPath,
          pageCount: appendixRenderResult.pageCount,
          pageCheckPaths: appendixRenderResult.pageCheckPaths,
        });
      }
    }
  }

  await browser.close();
  const indexPath = path.join(outputDir, "index.html");
  const outputsWithIndex = outputs.map((item) => ({ ...item, indexPath }));
  writeText(path.join(outputDir, "manifest.json"), JSON.stringify(outputs, null, 2));
  writeText(indexPath, makeIndex(outputsWithIndex));
  console.log(JSON.stringify({
    outputDir,
    indexPath,
    supportLayoutMode,
    count: outputs.length,
  }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
