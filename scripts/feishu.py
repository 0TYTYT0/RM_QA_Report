import argparse
import json
import os
import re
from datetime import date
import requests
from pathlib import Path

BASE_URL = "https://open.feishu.cn/open-apis"

class Feishu:
    def __init__(self):
        self.token = self.get_token()

    # 检查 API 返回结果
    @staticmethod
    def check(response):
        try:
            result = response.json()
        except ValueError:
            response.raise_for_status()
            raise RuntimeError("飞书返回了非 JSON 响应") from None

        if not response.ok or result.get("code") != 0:
            raise RuntimeError(
                f"飞书 API 请求失败（HTTP {response.status_code}，"
                f"code={result.get('code')}，msg={result.get('msg')}，"
                f"request_id={response.headers.get('X-Request-Id', '-') }）"
            )

        return result

    def get_chats(self):
        result = self.request(
            "GET",
            "/im/v1/chats",
            params={"page_size": 100}
        )
        return result["data"]["items"]

    def grant_document_admin(self, doc_id, open_id):
        return self.request(
            "POST",
            f"/drive/v1/permissions/{doc_id}/members",
            params={"type": "docx", "need_notification": "false"},
            json={
                "member_type": "openid",
                "member_id": open_id,
                "perm": "full_access",
            },
        )
    
    # 获取应用访问令牌
    def get_token(self):
        response = requests.post(
            f"{BASE_URL}/auth/v3/tenant_access_token/internal",
            json={
                "app_id": os.environ["FEISHU_APP_ID"],
                "app_secret": os.environ["FEISHU_APP_SECRET"],
            },
            timeout=30
        )

        return self.check(response)["tenant_access_token"]

    # 封装 API 请求
    def request(self, method, path, **kwargs):
        response = requests.request(
            method,
            f"{BASE_URL}{path}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json; charset=utf-8"
            },
            timeout=30,
            **kwargs
        )

        return self.check(response)

    # 创建云文档
    def create_document(self, title, markdown):
        result = self.request(
            "POST",
            "/docx/v1/documents",
            json={
                "title": title,
                "folder_token": os.environ["FEISHU_FOLDER_TOKEN"],
            },
        )

        doc_id = result["data"]["document"]["document_id"]

        # 转换 Markdown
        result = self.request(
            "POST",
            "/docx/v1/documents/blocks/convert",
            json={
                "content_type": "markdown",
                "content": markdown
            }
        )

        blocks = result["data"]["blocks"]
        root_ids = result["data"]["first_level_block_ids"]

        # 移除表格只读属性
        for block in blocks:
            if "table" in block:
                block["table"].get("property", {}).pop(
                    "merge_info", None
                )

        # 写入文档块
        if blocks:
            self.request(
                "POST",
                f"/docx/v1/documents/{doc_id}/blocks/{doc_id}/descendant",
                json={
                    "children_id": root_ids,
                    "descendants": blocks,
                    "index": 0
                }
            )

        return doc_id

    # 授予群聊文档权限
    def grant_permission(self, doc_id, chat_id):
        return self.request(
            "POST",
            f"/drive/v1/permissions/{doc_id}/members",
            params={
                "type": "docx",
                "need_notification": "false"
            },
            json={
                "member_type": "openchat",
                "member_id": chat_id,
                "perm": "view"
            }
        )

    # 通用消息发送接口
    def send_message(self, chat_id, msg_type, content):
        return self.request(
            "POST",
            "/im/v1/messages",
            params={
                "receive_id_type": "chat_id"
            },
            json={
                "receive_id": chat_id,
                "msg_type": msg_type,
                "content": json.dumps(
                    content,
                    ensure_ascii=False
                )
            }
        )

    # 发送 Markdown 卡片
    def send_markdown(self, chat_id, title, markdown):
        return self.send_message(
            chat_id,
            "interactive",
            {
                "schema": "2.0",
                "header": {
                    "template": "blue",
                    "title": {
                        "tag": "plain_text",
                        "content": title
                    }
                },
                "body": {
                    "elements": [
                        {
                            "tag": "markdown",
                            "content": markdown
                        }
                    ]
                }
            }
        )

    # 发布报告
    def publish_report(self, chat_id, title, markdown):
        admin_open_id = os.environ["FEISHU_ADMIN_OPEN_ID"]
        doc_domain = os.environ["DOC_DOMAIN"]
        doc_id = self.create_document(title, markdown)

        self.grant_document_admin(doc_id, admin_open_id)
        self.grant_permission(doc_id, chat_id)

        url = f"{doc_domain}/docx/{doc_id}"
        question_ids = {
            int(value)
            for value in re.findall(
                r"^###[ \t]+#([0-9]+)(?=[ \t]|\r?$)", markdown, re.MULTILINE
            )
        }
        notification = "报告已发布。"
        if question_ids:
            first_id, last_id = min(question_ids), max(question_ids)
            id_range = f"#{first_id}"
            if first_id != last_id:
                id_range += f"–#{last_id}"
            notification += f"\n\n本次答疑编号范围：{id_range}（共 {len(question_ids)} 条）"

        self.send_markdown(
            chat_id,
            title,
            f"{notification}\n\n[查看完整报告]({url})"
        )

        return url

def main():
    parser = argparse.ArgumentParser(description="发布 Markdown 答疑报告到飞书")
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args()

    reports = []
    for path in args.reports:
        try:
            date.fromisoformat(path.stem[:10])
        except ValueError:
            print(f"跳过日期无效的报告：{path}")
            continue
        if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
            print(f"跳过非普通文件：{path}")
            continue
        markdown = path.read_text(encoding="utf-8-sig")
        if not markdown.strip():
            print(f"跳过空报告：{path}")
            continue
        reports.append((path.stem, markdown))

    if not reports:
        return

    chat_id = os.environ["FEISHU_CHAT_ID"]
    feishu = Feishu()
    for name, markdown in reports:
        url = feishu.publish_report(chat_id, f"RoboMaster 答疑报告 {name}", markdown)
        print(f"发布成功：{url}")


if __name__ == "__main__":
    main()
