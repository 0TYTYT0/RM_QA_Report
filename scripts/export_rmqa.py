
import requests
import json
from pathlib import Path

BASE = "https://qingflow.com"
VIEW_ID = "g79clh9dkk02"
APP_ID = "g79clgn1kk02"

FIELDS = {
    "编号": "id",
    "学校名 University": "university",
    "战队名 Team": "team",
    "请选择赛事类型 Competition": "competition",
    "请描述你的问题 Please describe your problem": "question",
    "反馈 Answer": "answer",
}

def simplify_record(record):
    result = dict.fromkeys(FIELDS.values())

    for field in record["answers"]:
        title = (field.get("queTitle") or "").strip()
        key = FIELDS.get(title)
        if key is None:
            continue

        parts = []
        for item in field.get("values") or []:
            value = item.get("dataValue")
            if value is None:
                value = item.get("value")
            if value is not None and str(value).strip():
                parts.append(str(value))

        if parts:
            result[key] = "\n".join(parts)

    return result

session = requests.Session()
session.headers.update({
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": BASE,
    "Referer": BASE + "/",
    "User-Agent": "Mozilla/5.0",
    "wsid": "57467",
})

# 初始化共享视图
init_paths = [
    f"/api/ws/workspaceAndMemberInfo?type=FORM&key={APP_ID}",
    f"/api/view/{VIEW_ID}/apply/baseInfo",
    f"/api/view/{VIEW_ID}/viewConfig/baseInfo",
]

for path in init_paths:
    r = session.get(BASE + path, timeout=20)
    r.raise_for_status()
    if r.json().get("code") != 0:
        raise RuntimeError(f"初始化失败: {path}")

print("初始化完成")

# 分页获取
all_records = []
page = 1
page_size = 50

while True:
    payload = {
        "filter": {
            "pageSize": page_size,
            "pageNum": page,
            "type": 8,
            "sorts": [{
                "queId": 0,
                "isAscend": False,
                "queType": 8,
                "sortType": "customFieldSort",
            }],
            "queries": [],
            "queryKey": None,
        }
    }

    r = session.post(
        f"{BASE}/api/view/{VIEW_ID}/apply/filter",
        json=payload,
        timeout=20
    )
    r.raise_for_status()

    result = r.json()
    if result.get("code") != 0:
        raise RuntimeError(result.get("message"))

    data = result["data"]
    records = data.get("list", [])
    total = int(data.get("total", 0))

    if not records:
        if len(all_records) < total:
            raise RuntimeError("数据未全部获取，分页提前结束")
        break

    all_records.extend(simplify_record(record) for record in records)

    print(f"第 {page} 页: {len(records)} 条，"
          f"累计 {len(all_records)}/{total}")

    if len(all_records) >= total:
        break

    page += 1

# 保存
Path("./out/rmqa_2027_clean.json").write_text(
    json.dumps(all_records, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print(f"完成，共获取 {len(all_records)} 条答疑")
