from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

from report_app.feedback_store import FeedbackStore


ROOT_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = Path(__file__).resolve().parent / "web"
DEFAULT_OUTPUT_ROOT = ROOT_DIR / "output" / "report_app"
MAX_REQUEST_BYTES = 24 * 1024 * 1024
MAX_FILES_PER_JOB = 100
WEB_INDEX_ALIASES = {
    "/",
    "/index.html",
    "/report_app",
    "/report_app/",
    "/report_app/web",
    "/report_app/web/",
    "/report_app/web/index.html",
    "/web",
    "/web/",
    "/web/index.html",
}
STAGE_LABELS = {
    "elementary": "小学版",
    "junior_high": "初中版",
    "senior_high": "高中版",
    "secondary": "中学通用版",
}
STAGE_AGE_GROUPS = {
    "elementary": "小学阶段",
    "junior_high": "初中阶段",
    "senior_high": "高中阶段",
    "secondary": "中学阶段",
}


def resolve_web_asset(request_path: str) -> Path | None:
    if request_path in WEB_INDEX_ALIASES:
        return WEB_DIR / "index.html"
    static_map = {
        "/app.js": WEB_DIR / "app.js",
        "/styles.css": WEB_DIR / "styles.css",
        "/report_app/web/app.js": WEB_DIR / "app.js",
        "/report_app/web/styles.css": WEB_DIR / "styles.css",
        "/web/app.js": WEB_DIR / "app.js",
        "/web/styles.css": WEB_DIR / "styles.css",
    }
    return static_map.get(request_path)


def safe_stem(filename: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", stem).strip("._-")
    return stem[:80] or "assessment"


def student_number_label(assessment: dict[str, Any]) -> str:
    metadata = assessment.get("assessment_metadata")
    if not isinstance(metadata, dict):
        return ""
    raw = str(metadata.get("source_student_id") or "").strip()
    if re.fullmatch(r"\d+", raw):
        return f"{raw}号"
    if re.fullmatch(r"\d+\s*号", raw):
        return re.sub(r"\s+", "", raw)
    return ""


def sanitize_log(text: str, api_key: str = "") -> str:
    value = str(text or "")
    if api_key:
        value = value.replace(api_key, "[REDACTED_API_KEY]")
    return re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED_API_KEY]", value)


def apply_stage_override(payload: dict[str, Any], stage: str) -> dict[str, Any]:
    if stage not in STAGE_LABELS:
        raise ValueError(f"不支持的报告版本：{stage}")
    result = deepcopy(payload)
    profile = result.get("respondent_profile")
    if not isinstance(profile, dict):
        profile = {}
        result["respondent_profile"] = profile
    result["school_stage"] = stage
    result["writing_variant"] = STAGE_LABELS[stage]
    result["audience"] = "parents" if stage == "elementary" else "student"
    profile["age_group"] = STAGE_AGE_GROUPS[stage]
    profile["audience"] = result["audience"]
    return result


def load_json_text(filename: str, content: str) -> dict[str, Any]:
    if not filename.lower().endswith(".json"):
        raise ValueError(f"{filename} 不是 JSON 文件")
    try:
        value = json.loads(content.lstrip("\ufeff"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{filename} JSON 格式错误：第 {exc.lineno} 行，第 {exc.colno} 列"
        ) from exc
    if not isinstance(value, dict):
        raise ValueError(f"{filename} 顶层必须是 JSON object")
    if not isinstance(value.get("scores"), dict) or not value.get("scores"):
        raise ValueError(f"{filename} 缺少非空 scores 对象")
    return value


@dataclass
class JobItem:
    item_id: str
    filename: str
    student_number: str = ""
    status: str = "queued"
    message: str = "等待生成"
    output_dir: str = ""
    pdfs: list[dict[str, str]] = field(default_factory=list)
    check_url: str = ""
    quality_review_url: str = ""
    report_url: str = ""
    review_summary: dict[str, Any] = field(default_factory=dict)
    feedback_summary: dict[str, Any] = field(default_factory=dict)
    log_tail: str = ""
    started_at: float | None = None
    finished_at: float | None = None

    def public(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "filename": self.filename,
            "student_number": self.student_number,
            "status": self.status,
            "message": self.message,
            "output_dir": self.output_dir,
            "pdfs": self.pdfs,
            "check_url": self.check_url,
            "quality_review_url": self.quality_review_url,
            "report_url": self.report_url,
            "review_summary": self.review_summary,
            "feedback_summary": self.feedback_summary,
            "log_tail": self.log_tail,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass
class BatchJob:
    job_id: str
    stage: str
    created_at: float
    root_dir: Path
    items: list[JobItem]
    status: str = "queued"

    def public(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for item in self.items:
            counts[item.status] = counts.get(item.status, 0) + 1
        return {
            "job_id": self.job_id,
            "stage": self.stage,
            "stage_label": STAGE_LABELS[self.stage],
            "created_at": self.created_at,
            "status": self.status,
            "counts": counts,
            "items": [item.public() for item in self.items],
        }


class JobManager:
    def __init__(self, output_root: Path = DEFAULT_OUTPUT_ROOT) -> None:
        self.output_root = output_root.resolve()
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, BatchJob] = {}
        self._lock = threading.RLock()

    def submit(self, request: dict[str, Any]) -> dict[str, Any]:
        api_key = str(request.get("api_key") or "").strip()
        if len(api_key) < 8:
            raise ValueError("请填写有效的 DeepSeek API Key")
        stage = str(request.get("stage") or "elementary").strip()
        if stage not in STAGE_LABELS:
            raise ValueError("报告版本无效")
        files = request.get("files")
        if not isinstance(files, list) or not files:
            raise ValueError("请至少选择一个 JSON 文件")
        if len(files) > MAX_FILES_PER_JOB:
            raise ValueError(f"单批最多处理 {MAX_FILES_PER_JOB} 份报告")

        max_rounds = min(5, max(1, int(request.get("max_rounds", 3))))
        quality_target = min(100, max(60, int(request.get("quality_target_score", 90))))
        render_review = bool(request.get("render_review_draft", True))
        theme = str(request.get("theme") or "hybrid_expert_dashboard").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]+", theme):
            raise ValueError("PDF 主题名称无效")

        job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        job_root = self.output_root / job_id
        input_dir = job_root / "inputs"
        input_dir.mkdir(parents=True, exist_ok=True)
        items: list[JobItem] = []
        prepared: list[tuple[JobItem, Path]] = []
        used_names: set[str] = set()

        for index, file_entry in enumerate(files, start=1):
            if not isinstance(file_entry, dict):
                raise ValueError(f"第 {index} 个文件记录无效")
            filename = Path(str(file_entry.get("name") or f"assessment_{index}.json")).name
            content = str(file_entry.get("content") or "")
            assessment = apply_stage_override(load_json_text(filename, content), stage)
            stem = safe_stem(filename)
            unique_stem = stem
            suffix = 2
            while unique_stem.lower() in used_names:
                unique_stem = f"{stem}_{suffix}"
                suffix += 1
            used_names.add(unique_stem.lower())
            input_path = input_dir / f"{unique_stem}.json"
            input_path.write_text(
                json.dumps(assessment, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            item = JobItem(
                item_id=f"item-{index:03d}",
                filename=filename,
                student_number=student_number_label(assessment),
            )
            items.append(item)
            prepared.append((item, input_path))

        job = BatchJob(
            job_id=job_id,
            stage=stage,
            created_at=time.time(),
            root_dir=job_root,
            items=items,
        )
        with self._lock:
            self.jobs[job_id] = job

        worker = threading.Thread(
            target=self._run_batch,
            args=(
                job,
                prepared,
                api_key,
                max_rounds,
                quality_target,
                render_review,
                theme,
            ),
            daemon=True,
            name=f"report-job-{job_id}",
        )
        worker.start()
        return job.public()

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self.jobs.get(job_id)
            return job.public() if job else None

    def submit_feedback(
        self,
        job_id: str,
        item_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise KeyError("任务不存在")
            item = next((value for value in job.items if value.item_id == item_id), None)
            if item is None:
                raise KeyError("报告项目不存在")
            issues = item.review_summary.get("issues", [])
            issues = issues if isinstance(issues, list) else []
            issue_map = {
                str(issue.get("issue_id")): issue
                for issue in issues
                if isinstance(issue, dict) and str(issue.get("issue_id") or "").strip()
            }
            reviews = payload.get("reviews")
            if not isinstance(reviews, list) or not reviews:
                raise ValueError("请至少提交一条复核意见")
            reviewer = str(payload.get("reviewer") or "").strip()
            store = FeedbackStore(job.root_dir)
            saved = []
            for index, review in enumerate(reviews, start=1):
                if not isinstance(review, dict):
                    raise ValueError(f"第 {index} 条复核意见格式无效")
                issue_id = str(review.get("issue_id") or "").strip()
                issue = issue_map.get(issue_id)
                if issue is None:
                    raise ValueError(f"复核问题不存在或已过期：{issue_id}")
                saved.append(
                    store.append(
                        job_id=job.job_id,
                        item_id=item.item_id,
                        filename=item.filename,
                        stage=job.stage,
                        issue=issue,
                        decision=str(review.get("decision") or ""),
                        note=str(review.get("note") or ""),
                        replacement_text=str(review.get("replacement_text") or ""),
                        reviewer=reviewer,
                    )
                )
            item.feedback_summary = store.summary(
                item_id=item.item_id,
                issue_ids=list(issue_map),
            )
            return {
                "ok": True,
                "saved_count": len(saved),
                "feedback_summary": item.feedback_summary,
                "item": item.public(),
            }

    def _run_batch(
        self,
        job: BatchJob,
        prepared: list[tuple[JobItem, Path]],
        api_key: str,
        max_rounds: int,
        quality_target: int,
        render_review: bool,
        theme: str,
    ) -> None:
        job.status = "running"
        try:
            for item, input_path in prepared:
                self._run_item(
                    job,
                    item,
                    input_path,
                    api_key,
                    max_rounds,
                    quality_target,
                    render_review,
                    theme,
                )
        finally:
            statuses = {item.status for item in job.items}
            if statuses <= {"approved"}:
                job.status = "approved"
            elif "running" in statuses or "queued" in statuses:
                job.status = "running"
            elif "failed" in statuses:
                job.status = "completed_with_errors"
            else:
                job.status = "needs_review"
            api_key = ""

    def _run_item(
        self,
        job: BatchJob,
        item: JobItem,
        input_path: Path,
        api_key: str,
        max_rounds: int,
        quality_target: int,
        render_review: bool,
        theme: str,
    ) -> None:
        item.status = "running"
        item.message = "正在调用 TextAgent 与 CheckerAgent"
        item.started_at = time.time()
        output_dir = job.root_dir / "reports" / safe_stem(input_path.name)
        item.output_dir = str(output_dir)
        command = [
            sys.executable,
            str(ROOT_DIR / "scripts" / "generate_full_pdf_report.py"),
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--theme",
            theme,
            "--max-rounds",
            str(max_rounds),
            "--quality-target-score",
            str(quality_target),
        ]
        if render_review:
            command.append("--render-review-draft")

        env = os.environ.copy()
        env.update(
            {
                "DEEPSEEK_API_KEY": api_key,
                "DEEPSEEK_MODEL": env.get("DEEPSEEK_MODEL", "deepseek-chat"),
                "DEEPSEEK_BASE_URL": env.get(
                    "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
                ),
                "DEEPSEEK_STREAM": env.get("DEEPSEEK_STREAM", "0"),
                "DEEPSEEK_MAX_RETRIES": env.get("DEEPSEEK_MAX_RETRIES", "8"),
                "DEEPSEEK_MAX_OUTPUT_TOKENS": env.get(
                    "DEEPSEEK_MAX_OUTPUT_TOKENS", "16000"
                ),
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
            }
        )
        try:
            result = subprocess.run(
                command,
                cwd=ROOT_DIR,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60 * 45,
                check=False,
            )
            combined = sanitize_log(
                "\n".join(part for part in (result.stdout, result.stderr) if part),
                api_key,
            )
            item.log_tail = combined[-5000:]
            summary_path = output_dir / "run_summary.json"
            summary: dict[str, Any] = {}
            if summary_path.exists():
                try:
                    summary = json.loads(summary_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    summary = {}

            item.pdfs = [
                {
                    "name": path.name,
                    "url": self._artifact_url(job.job_id, path),
                }
                for path in sorted(output_dir.rglob("*.pdf"))
            ]
            final_check = output_dir / "final_check.json"
            quality_review_json = output_dir / "quality_review.json"
            quality_review_html = output_dir / "quality_review.html"
            final_report = output_dir / "final_report.json"
            if final_check.exists():
                item.check_url = self._artifact_url(job.job_id, final_check)
            if quality_review_html.exists():
                item.quality_review_url = self._artifact_url(
                    job.job_id,
                    quality_review_html,
                )
            if quality_review_json.exists():
                try:
                    quality_review = json.loads(
                        quality_review_json.read_text(encoding="utf-8")
                    )
                except (OSError, json.JSONDecodeError):
                    quality_review = {}
                if isinstance(quality_review, dict):
                    groups = quality_review.get("problem_groups", [])
                    issues = quality_review.get("issues", [])
                    next_actions = quality_review.get("next_actions", [])
                    problem_preview: list[str] = []
                    if isinstance(groups, list):
                        for group in groups:
                            if not isinstance(group, dict):
                                continue
                            for problem in group.get("items", []):
                                text = str(problem).strip()
                                if text and text not in problem_preview:
                                    problem_preview.append(text)
                                if len(problem_preview) >= 4:
                                    break
                            if len(problem_preview) >= 4:
                                break
                    item.review_summary = {
                        "headline": str(quality_review.get("headline") or ""),
                        "summary": str(quality_review.get("summary") or ""),
                        "score": int(quality_review.get("score", 0) or 0),
                        "target_score": int(
                            quality_review.get("target_score", quality_target) or 0
                        ),
                        "requires_human_review": bool(
                            quality_review.get("requires_human_review")
                        ),
                        "problem_preview": problem_preview,
                        "issues": [
                            issue
                            for issue in (issues if isinstance(issues, list) else [])
                            if isinstance(issue, dict)
                        ],
                        "next_actions": [
                            str(value)
                            for value in (
                                next_actions[:3]
                                if isinstance(next_actions, list)
                                else []
                            )
                        ]
                    }
            if final_report.exists():
                item.report_url = self._artifact_url(job.job_id, final_report)

            reported_status = str(summary.get("status") or "")
            if result.returncode != 0:
                item.status = "failed"
                item.message = "生成失败，请展开日志查看原因"
            elif reported_status == "approved":
                item.status = "approved"
                item.message = (
                    str(item.review_summary.get("headline"))
                    or "已通过质量检查"
                )
            elif item.pdfs:
                item.status = "review"
                item.message = (
                    str(item.review_summary.get("headline"))
                    or "已生成审核稿，需要人工复核"
                )
            else:
                item.status = "review"
                item.message = (
                    str(item.review_summary.get("headline"))
                    or "文字结果需要复核，未生成 PDF"
                )
        except subprocess.TimeoutExpired as exc:
            item.status = "failed"
            item.message = "单份报告运行超过45分钟，已停止"
            item.log_tail = sanitize_log(str(exc), api_key)
        except Exception as exc:
            item.status = "failed"
            item.message = f"运行异常：{type(exc).__name__}"
            item.log_tail = sanitize_log(str(exc), api_key)
        finally:
            item.finished_at = time.time()

    def _artifact_url(self, job_id: str, path: Path) -> str:
        relative = path.resolve().relative_to((self.output_root / job_id).resolve())
        return f"/artifacts/{quote(job_id)}/{quote(relative.as_posix())}"

    def artifact_path(self, job_id: str, relative: str) -> Path | None:
        job_root = (self.output_root / job_id).resolve()
        try:
            candidate = (job_root / unquote(relative)).resolve()
            candidate.relative_to(job_root)
        except (ValueError, OSError):
            return None
        return candidate if candidate.is_file() else None


class ReportAppHandler(BaseHTTPRequestHandler):
    manager: JobManager

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/health":
            self._json(
                {
                    "ok": True,
                    "service": "psych-report-console",
                    "project_root": str(ROOT_DIR),
                }
            )
            return
        if path.startswith("/api/jobs/"):
            job_id = unquote(path.removeprefix("/api/jobs/")).strip("/")
            job = self.manager.get(job_id)
            if job is None:
                self._json({"error": "任务不存在"}, HTTPStatus.NOT_FOUND)
            else:
                self._json(job)
            return
        if path.startswith("/artifacts/"):
            remainder = path.removeprefix("/artifacts/")
            job_id, separator, relative = remainder.partition("/")
            if not separator:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            artifact = self.manager.artifact_path(unquote(job_id), relative)
            if artifact is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._file(artifact)
            return

        target = resolve_web_asset(path)
        if target and target.is_file():
            self._file(target)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            self._json(
                {"error": "请求为空或文件总量超过24MB"},
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
            return
        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("请求顶层必须是 JSON object")
            if path == "/api/jobs":
                result = self.manager.submit(payload)
                status = HTTPStatus.ACCEPTED
            else:
                match = re.fullmatch(
                    r"/api/jobs/([^/]+)/items/([^/]+)/feedback",
                    path,
                )
                if match is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                result = self.manager.submit_feedback(
                    unquote(match.group(1)),
                    unquote(match.group(2)),
                    payload,
                )
                status = HTTPStatus.OK
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._json({"error": f"请求 JSON 无效：{exc}"}, HTTPStatus.BAD_REQUEST)
            return
        except (TypeError, ValueError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        except KeyError as exc:
            self._json({"error": str(exc.args[0])}, HTTPStatus.NOT_FOUND)
            return
        self._json(result, status)

    def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path) -> None:
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("[report-app] " + (format % args) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the local report operations console.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("为保护测评数据与 API Key，本地控制台只允许监听回环地址")
    manager = JobManager(args.output_root)
    handler = type("ConfiguredReportAppHandler", (ReportAppHandler,), {"manager": manager})
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Report console: http://{args.host}:{args.port}")
    print(f"Outputs: {manager.output_root}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping report console.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
