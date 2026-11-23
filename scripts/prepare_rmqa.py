import argparse
import json
from pathlib import Path

from diff_rmqa import compare, load_snapshot


ROOT = Path(__file__).resolve().parents[1]
MODEL_FIELDS = ("id", "competition", "question", "answer", "previous_answer")
SNAPSHOT_FIELDS = {"id", "university", "team", "competition", "question", "answer"}
PLACEHOLDER = "<在这里插入实际的 changes.json>"


def load_export(path, *, allow_empty=False):
    snapshot = load_snapshot(path, allow_empty=allow_empty)
    for record_id, record in snapshot.items():
        if record.keys() != SNAPSHOT_FIELDS:
            raise ValueError(f"{path} 编号 {record_id} 的字段与导出格式不符")
        for field in SNAPSHOT_FIELDS:
            value = record[field]
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{path} 编号 {record_id} 的 {field} 应为文本或 null")
    return snapshot


def render_model_input(changes, template_path):
    template = template_path.read_text(encoding="utf-8")
    if template.count(PLACEHOLDER) != 1:
        raise ValueError(f"{template_path} 必须包含一个变更数据占位符")

    model_data = {
        category: [
            {field: record[field] for field in MODEL_FIELDS if field in record}
            for record in records
        ]
        for category, records in changes.items()
        if records
    }
    return template.replace(PLACEHOLDER, json.dumps(model_data, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="校验两次答疑快照并生成模型输入")
    parser.add_argument("--current", type=Path, default=ROOT / "out/rmqa_2027_clean.json")
    parser.add_argument("--published", type=Path, default=ROOT / "data/rmqa_2027_published.json")
    parser.add_argument("--template", type=Path, default=ROOT / "model_input_template.txt")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "out")
    args = parser.parse_args()

    changes_path = args.output_dir / "changes.json"
    model_path = args.output_dir / "model_input.txt"
    inputs = {path.resolve() for path in (args.current, args.published, args.template)}
    if inputs.intersection({changes_path.resolve(), model_path.resolve()}):
        parser.exit(1, "准备失败：输出文件与输入文件冲突\n")

    try:
        current = load_export(args.current)
        published = load_export(args.published, allow_empty=True)
        changes = compare(published, current)

        missing = changes["丢失答疑"]
        model_input = ""
        if not missing and any(changes.values()):
            model_input = render_model_input(changes, args.template)

        args.output_dir.mkdir(parents=True, exist_ok=True)
        model_path.write_text(model_input, encoding="utf-8")
        changes_path.write_text(
            json.dumps(changes, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError) as exc:
        parser.exit(1, f"准备失败：{exc}\n")

    if missing:
        parser.exit(2, f"本次快照缺少 {len(missing)} 条答疑，详情见 {changes_path}\n")

    print("模型输入已生成" if model_input else "无变化，跳过模型调用")


if __name__ == "__main__":
    main()
