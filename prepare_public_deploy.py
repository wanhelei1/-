"""Create a minimal public deployment bundle without restricted knowledge-base files."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KB_NAME = "华为PC全板块深度知识库_v7"
RESTRICTED_DIRS = {"P4-价格政策库（机密）", "90-待审核", "99-历史归档", "09-来源研究底稿"}
ROOT_FILES = (
    ".dockerignore",
    "Dockerfile",
    "README.md",
    "app.py",
    "index.html",
    "follow_up_module.py",
    "marketing_content_module.py",
    "pricing_module.py",
    "prepare_public_deploy.py",
    "store_growth_workflow.py",
)
MODULE_FILES = {
    "3号(1)": ("mock_retriever.py", "recommendation_engine.py", "retrieval_adapter.py"),
    "BLOCK-07": ("block07_compliance.py",),
    "customer_insight_agent": ("kb_agent.py",),
}


def _ignore_restricted(directory: str, names: list[str]) -> set[str]:
    base = Path(directory)
    ignored = set()
    for name in names:
        candidate = base / name
        if candidate.is_dir() and name in RESTRICTED_DIRS:
            ignored.add(name)
    return ignored


def create_bundle(output: Path) -> tuple[int, int]:
    output = output.resolve()
    if output == ROOT or ROOT not in output.parents:
        raise ValueError("Output must be a new directory inside the project root")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {output}")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()
    copied = []
    for relative in ROOT_FILES:
        source = ROOT / relative
        if not source.is_file():
            raise FileNotFoundError(source)
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(relative)

    for directory, filenames in MODULE_FILES.items():
        for filename in filenames:
            relative = Path(directory) / filename
            source = ROOT / relative
            if not source.is_file():
                raise FileNotFoundError(source)
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied.append(relative.as_posix())

    test_source = ROOT / "tests"
    if not test_source.is_dir():
        raise FileNotFoundError(test_source)
    shutil.copytree(test_source, output / "tests", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    copied.extend(path.relative_to(output).as_posix() for path in (output / "tests").rglob("*.py"))

    knowledge_base = ROOT / "knowledge-base" / KB_NAME
    if not knowledge_base.is_dir():
        raise FileNotFoundError(knowledge_base)
    target_kb = output / "knowledge-base" / KB_NAME
    shutil.copytree(knowledge_base, target_kb, ignore=_ignore_restricted)
    knowledge_files = sorted(
        path.relative_to(output).as_posix()
        for path in target_kb.rglob("*")
        if path.is_file()
    )
    copied.extend(knowledge_files)

    manifest = {
        "bundle": "public-store-growth-mvp",
        "restricted_directories_excluded": sorted(RESTRICTED_DIRS),
        "files": sorted(copied),
    }
    (output / "bundle-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return len(copied) + 1, len(knowledge_files)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a filtered public deployment bundle")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist" / "public-deploy",
        help="New output directory inside the project root (must not already exist)",
    )
    args = parser.parse_args()
    total, knowledge_files = create_bundle(args.output)
    print(f"Created {args.output.resolve()} ({total} files; {knowledge_files} knowledge-base files)")
    print("Excluded restricted price policy, pending-review, and historical archive directories.")


if __name__ == "__main__":
    main()
