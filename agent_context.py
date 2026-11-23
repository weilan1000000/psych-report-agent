# -*- coding: utf-8 -*-
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
SKILLS_DIR = ROOT_DIR / "skills"
MEMORY_DIR = ROOT_DIR / "memory"


def load_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"找不到上下文文件：{path}")
    return path.read_text(encoding="utf-8").strip()


def load_named_docs(directory: Path, names: list[str]) -> str:
    sections = []
    for name in names:
        sections.append(load_named_doc(directory, name))
    return "\n\n".join(sections)


def load_named_doc(directory: Path, name: str) -> str:
    folder_path = directory / name
    if folder_path.is_dir():
        return load_folder_skill(folder_path, name)

    flat_path = directory / f"{name}.md"
    if flat_path.exists():
        return f"# {name}\n{load_text(flat_path)}"

    raise FileNotFoundError(
        f"找不到上下文文件或文件夹：{flat_path} / {folder_path}"
    )


def load_folder_skill(folder_path: Path, name: str) -> str:
    sections = []
    skill_path = folder_path / "SKILL.md"
    if skill_path.exists():
        sections.append(f"# {name}/SKILL.md\n{load_text(skill_path)}")

    for path in sorted(folder_path.rglob("*")):
        if not path.is_file():
            continue
        if path == skill_path:
            continue
        if any(part.startswith(".") for part in path.relative_to(folder_path).parts):
            continue
        if path.suffix.lower() not in {".md", ".json"}:
            continue

        relative_path = path.relative_to(folder_path).as_posix()
        sections.append(f"# {name}/{relative_path}\n{load_text(path)}")

    if not sections:
        raise FileNotFoundError(f"文件夹 skill 为空：{folder_path}")

    return "\n\n".join(sections)


def build_agent_context(skill_names: list[str], memory_names: list[str]) -> str:
    skill_context = load_named_docs(SKILLS_DIR, skill_names)
    memory_context = load_named_docs(MEMORY_DIR, memory_names)

    return f"""
以下是本次任务需要遵守的 Agent Skills 和长期记忆。它们是生成报告时的高优先级参考。

<skills>
{skill_context}
</skills>

<memory>
{memory_context}
</memory>
""".strip()
