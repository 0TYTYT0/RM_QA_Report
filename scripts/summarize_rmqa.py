import argparse
import hashlib
import json
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from openai import APIError, OpenAI

from diff_rmqa import compare, normalize_answer
from prepare_rmqa import ROOT, model_input_parts


BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def index_changes(changes):
    if not isinstance(changes, dict) or changes.keys() != compare({}, {}).keys():
        raise ValueError("changes.json 的变化分类不符合预期")
    indexed = {}
    for category, records in changes.items():
        if not isinstance(records, list):
            raise ValueError(f"「{category}」应为列表")
        for record in records:
            if not isinstance(record, dict):
                raise ValueError(f"「{category}」包含无效记录")
            record_id = record.get("id")
            if not isinstance(record_id, str) or not record_id.strip() or record_id in indexed:
                raise ValueError(f"「{category}」存在无效或重复编号")
            for field in ("competition", "question", "answer"):
                if field not in record or (record[field] is not None and not isinstance(record[field], str)):
                    raise ValueError(f"编号 {record_id} 的 {field} 应为文本或 null")
            indexed[record_id] = (category, record)
    return indexed


def validate_response(response, expected):
    if not isinstance(response, dict) or not isinstance(response.get("items"), list):
        raise ValueError("模型响应缺少 items 列表")
    summaries = {}
    for item in response["items"]:
        if not isinstance(item, dict):
            raise ValueError("模型返回了无效条目")
        record_id = item.get("id")
        summary = item.get("summary")
        is_invalid = item.get("is_invalid")
        keywords = item.get("keywords")
        if (
            not isinstance(record_id, str)
            or record_id not in expected
            or record_id in summaries
            or item.get("category") != expected[record_id][0]
            or not isinstance(is_invalid, bool)
            or not isinstance(summary, str)
            or not summary.strip()
        ):
            raise ValueError("模型响应包含异常编号、分类、无效标记或摘要")
        if is_invalid and not normalize_answer(expected[record_id][1]["answer"]):
            raise ValueError(f"编号 {record_id} 反馈为空，不能标为无效答疑")
        if not isinstance(keywords, list) or not keywords or any(
            not isinstance(keyword, str) or not keyword.strip() for keyword in keywords
        ):
            raise ValueError(f"编号 {record_id} 的 keywords 应为非空字符串数组")
        summaries[record_id] = {
            "id": record_id,
            "category": item["category"],
            "is_invalid": is_invalid,
            "summary": summary.strip(),
            "keywords": list(dict.fromkeys(keyword.strip() for keyword in keywords)),
        }
    if summaries.keys() != expected.keys():
        raise ValueError("模型响应遗漏了答疑编号")
    return summaries


def request_batch(client, payload, expected):
    options = dict(payload)
    enable_thinking = options.pop("enable_thinking")
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                **options, extra_body={"enable_thinking": enable_thinking}
            )
            if not response.choices or response.choices[0].finish_reason != "stop":
                raise ValueError("模型输出未正常完成")
            content = response.choices[0].message.content or ""
            return validate_response(json.loads(content), expected)
        except APIError as exc:
            detail = getattr(exc, "status_code", None)
            label = f"HTTP {detail}" if detail else type(exc).__name__
            raise RuntimeError(f"阿里云百炼请求失败（{label}）") from exc
        except ValueError as exc:
            if attempt == 2:
                raise RuntimeError(f"DeepSeek 批次失败（{exc}）") from exc
            time.sleep(2 ** attempt)


def build_requests(indexed, args):
    pairs = list(indexed.items())
    for offset in range(0, len(pairs), args.batch_size):
        batch = dict(pairs[offset:offset + args.batch_size])
        grouped = {}
        for category, record in batch.values():
            grouped.setdefault(category, []).append(record)
        before, data, after = model_input_parts(grouped, args.template)
        payload = {
            "model": args.model,
            "messages": [
                {"role": "system", "content": (before + after).strip()},
                {"role": "user", "content": data},
            ],
            "response_format": {"type": "json_object"},
            "enable_thinking": False,
            "max_tokens": 4096,
        }
        yield batch, payload


def summarize(client, indexed, args):
    items = []
    for batch, payload in build_requests(indexed, args):
        cache_key = {"base_url": str(client.base_url), "payload": payload}
        digest = hashlib.sha256(json.dumps(cache_key, sort_keys=True).encode("utf-8")).hexdigest()
        cache = args.output_dir / "deepseek-cache" / f"{digest}.json"
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            summaries = validate_response(cached, batch)
        except (FileNotFoundError, ValueError):
            cached = None
            summaries = request_batch(client, payload, batch)

        batch_items = [summaries[record_id] for record_id in batch]
        if cached is None:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json_text({"items": batch_items}), encoding="utf-8")
        items.extend(batch_items)
        print(f"已校验 {len(items)}/{len(indexed)} 条摘要", flush=True)
    return items


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def fill_report_template(template, values):
    return re.sub(r"\{([^{}]+)\}", lambda match: values[match[1]], template)


def format_quoted_text(text):
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    quoted = [lines[0]]
    for previous, line in zip(lines, lines[1:]):
        if previous.strip() and line.strip():
            quoted[-1] += "  "
        quoted.append("> " + line if line.strip() else ">")
    return "\n".join(quoted)


def render_report(template, day, items, indexed):
    template = re.sub(r"^>\\$", ">", template, flags=re.MULTILINE)
    title, _, body = template.strip().partition("\n\n")
    valid, separator, invalid = body.partition("\n## 无效答疑汇总\n")
    category_heading, _, entry = valid.strip().partition("\n\n")
    if "YYYY-MM-DD" not in title or not separator or "{变化类型}" not in category_heading or not entry or not invalid.strip():
        raise ValueError("报告模板缺少日期标题、变化类型或无效答疑小节")
    invalid_entry = invalid.strip()

    groups = {}
    invalid_entries = []
    for item in items:
        record_id = item["id"]
        category, record = indexed[record_id]
        answer = record["answer"]
        if not normalize_answer(answer):
            answer = "本次快照中的反馈为空" if category == "反馈清空" else "待官方反馈"
        values = {
            "答疑编号": record_id,
            "赛事类型": record["competition"] or "未标注赛事",
            "一个或多个关键词": "、".join(item["keywords"]),
            "摘要正文": item["summary"],
            "提问原文": format_quoted_text(record["question"] or "（原始提问为空）"),
            "答复原文": format_quoted_text(answer),
        }
        if item["is_invalid"]:
            invalid_entries.append(fill_report_template(invalid_entry, values))
        else:
            groups.setdefault(category, []).append(fill_report_template(entry, values))

    sections = [title.replace("YYYY-MM-DD", day)]
    for category, entries in groups.items():
        sections.extend([category_heading.replace("{变化类型}", category), *entries])
    if invalid_entries:
        sections.extend(["## 无效答疑汇总", *invalid_entries])
    return "\n\n".join(sections) + "\n"


def main():
    parser = argparse.ArgumentParser(description="调用阿里云百炼 DeepSeek 并生成答疑摘要草稿")
    parser.add_argument("--changes", type=Path, default=ROOT / "out/changes.json")
    parser.add_argument("--template", type=Path, default=ROOT / "model_input_template.txt")
    parser.add_argument("--report-template", type=Path, default=ROOT / "reports/report_template.md")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "out")
    parser.add_argument("--model", default=os.getenv("DASHSCOPE_MODEL") or "deepseek-v4.1-flash")
    parser.add_argument("--batch-size", type=int, default=15)
    parser.add_argument("--export-requests", action="store_true", help="导出分批请求体，无需 API 密钥")
    parser.add_argument("--date", type=date.fromisoformat, default=datetime.now(timezone(timedelta(hours=8))).date())
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size 必须大于 0")

    try:
        changes = json.loads(args.changes.read_text(encoding="utf-8"))
        indexed = index_changes(changes)
        if changes["丢失答疑"]:
            parser.exit(2, "本次快照存在缺失答疑，请先核对 changes.json\n")
        inputs = {path.resolve() for path in (args.changes, args.template, args.report_template)}
        if args.export_requests:
            export_path = args.output_dir / "deepseek_requests.json"
            if export_path.resolve() in inputs:
                raise ValueError("输出文件与输入文件冲突")
            payloads = [payload for _, payload in build_requests(indexed, args)]
            args.output_dir.mkdir(parents=True, exist_ok=True)
            export_path.write_text(json_text(payloads), encoding="utf-8")
            print(f"已导出 {len(payloads)} 批请求到 {export_path}")
            return
        if not indexed:
            print("无变化，跳过模型调用")
            return

        api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        if not api_key:
            raise ValueError("请设置阿里云百炼 DASHSCOPE_API_KEY")
        base_url = os.getenv("DASHSCOPE_BASE_URL", "").strip() or BASE_URL
        template = args.report_template.read_text(encoding="utf-8")
        day = args.date.isoformat()
        report_path = args.output_dir / f"{day}.md"
        summary_path = args.output_dir / "summary.json"
        if inputs.intersection({report_path.resolve(), summary_path.resolve()}):
            raise ValueError("输出文件与输入文件冲突")

        with OpenAI(api_key=api_key, base_url=base_url, timeout=120, max_retries=2) as client:
            items = summarize(client, indexed, args)
        report = render_report(template, day, items, indexed)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
        summary_path.write_text(json_text({"items": items}), encoding="utf-8")
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        parser.exit(1, f"生成摘要失败：{exc}\n")
    print(f"已生成 {summary_path} 和 {report_path}")


if __name__ == "__main__":
    main()
