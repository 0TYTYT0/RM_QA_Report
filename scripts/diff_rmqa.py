import argparse
import json
from pathlib import Path


def load_snapshot(path, *, allow_empty=False):
    content = path.read_text(encoding="utf-8")
    if allow_empty and not content.strip():
        return {}

    records = json.loads(content)
    if not isinstance(records, list) or (not records and not allow_empty):
        raise ValueError(f"{path} 应为非空 JSON 列表")

    indexed = {}
    for position, record in enumerate(records, start=1):
        if not isinstance(record, dict) or "answer" not in record:
            raise ValueError(f"{path} 第 {position} 条缺少反馈字段")

        record_id = record.get("id")
        if not isinstance(record_id, str) or not record_id.strip():
            raise ValueError(f"{path} 第 {position} 条缺少有效编号")

        record_id = record_id.strip()
        if record_id in indexed:
            raise ValueError(f"{path} 存在重复编号 {record_id}")

        answer = record["answer"]
        if answer is not None and not isinstance(answer, str):
            raise ValueError(f"{path} 编号 {record_id} 的反馈应为文本或 null")

        indexed[record_id] = record

    return indexed


def normalize_answer(answer):
    return (answer or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def compare(old, new):
    changes = {
        "新增答疑": [],
        "原有答疑新增反馈": [],
        "官方反馈修订": [],
        "反馈清空": [],
        "丢失答疑":[],
    }

    for record_id, current in new.items():
        previous = old.get(record_id)
        if previous is None:
            changes["新增答疑"].append(current)
            continue

        before = normalize_answer(previous["answer"])
        after = normalize_answer(current["answer"])
        if before == after:
            continue

        if not before:
            category = "原有答疑新增反馈"
        elif not after:
            category = "反馈清空"
        else:
            category = "官方反馈修订"

        changes[category].append({
            **current,
            "previous_answer": previous["answer"],
        })
    
    changes["丢失答疑"] = [
        record for record_id, record in old.items() if record_id not in new
    ]
    return changes


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("old", type=Path)
    parser.add_argument("new", type=Path)
    args = parser.parse_args()

    try:
        changes = compare(load_snapshot(args.old), load_snapshot(args.new))
    except (OSError, ValueError) as exc:
        parser.exit(1, f"比对失败：{exc}\n")

    print(json.dumps(changes, ensure_ascii=False, indent=2))
