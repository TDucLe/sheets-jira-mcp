#!/usr/bin/env python3
"""
Jira MCP Server
Cung cấp tools để tương tác với Jira qua MCP protocol.
Tất cả gọi thẳng lên Jira REST API — không lưu dữ liệu cục bộ.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

def get_jira_client() -> httpx.AsyncClient:
    import base64
    email = os.getenv("JIRA_EMAIL", "")
    token = os.getenv("JIRA_API_TOKEN", "")
    base_url = os.getenv("JIRA_BASE_URL", "").rstrip("/")
    creds = base64.b64encode(f"{email}:{token}".encode()).decode()
    return httpx.AsyncClient(
        base_url=f"{base_url}/rest/api/3",
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=30.0,
    )

async def jira_request(method: str, endpoint: str, body: dict = None) -> dict:
    async with get_jira_client() as client:
        response = await client.request(method, endpoint, json=body)
        if response.status_code == 204:
            return {"success": True}
        if not response.is_success:
            raise Exception(f"Jira API lỗi {response.status_code}: {response.text}")
        return response.json()

def make_description_doc(text: str) -> dict:
    return {
        "type": "doc", "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }

server = Server("jira-mcp")

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="jira_get_issue",
            description="Lấy thông tin chi tiết của một Jira issue theo key (ví dụ: PROJ-123).",
            inputSchema={
                "type": "object",
                "properties": {"issueKey": {"type": "string", "description": "Key của issue, ví dụ: PROJ-123"}},
                "required": ["issueKey"],
            },
        ),
        Tool(
            name="jira_search_issues",
            description="Tìm kiếm Jira issues bằng JQL query.",
            inputSchema={
                "type": "object",
                "properties": {
                    "jql": {"type": "string", "description": "JQL query, ví dụ: project = MYPROJ AND status = 'In Progress'"},
                    "maxResults": {"type": "integer", "description": "Số kết quả tối đa (mặc định 50)"},
                },
                "required": ["jql"],
            },
        ),
        Tool(
            name="jira_create_issue",
            description="Tạo một Jira issue mới.",
            inputSchema={
                "type": "object",
                "properties": {
                    "projectKey": {"type": "string", "description": "Key của project, ví dụ: MYPROJ"},
                    "summary": {"type": "string", "description": "Tiêu đề issue"},
                    "description": {"type": "string", "description": "Mô tả chi tiết"},
                    "issueType": {"type": "string", "description": "Task, Bug, Story, Epic (mặc định: Task)"},
                    "priority": {"type": "string", "description": "Highest, High, Medium, Low, Lowest"},
                    "labels": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["projectKey", "summary"],
            },
        ),
        Tool(
            name="jira_update_issue",
            description="Cập nhật thông tin của một Jira issue.",
            inputSchema={
                "type": "object",
                "properties": {
                    "issueKey": {"type": "string"},
                    "summary": {"type": "string"},
                    "description": {"type": "string"},
                    "priority": {"type": "string"},
                    "labels": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["issueKey"],
            },
        ),
        Tool(
            name="jira_transition_issue",
            description="Chuyển trạng thái issue (ví dụ: Todo → In Progress → Done).",
            inputSchema={
                "type": "object",
                "properties": {
                    "issueKey": {"type": "string"},
                    "transitionName": {"type": "string", "description": "Tên transition: 'In Progress', 'Done', 'To Do'..."},
                },
                "required": ["issueKey", "transitionName"],
            },
        ),
        Tool(
            name="jira_add_comment",
            description="Thêm bình luận vào một issue.",
            inputSchema={
                "type": "object",
                "properties": {
                    "issueKey": {"type": "string"},
                    "comment": {"type": "string", "description": "Nội dung bình luận"},
                },
                "required": ["issueKey", "comment"],
            },
        ),
        Tool(
            name="jira_list_projects",
            description="Liệt kê tất cả Jira projects bạn có quyền truy cập.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="jira_get_transitions",
            description="Lấy danh sách các transitions có thể thực hiện trên một issue.",
            inputSchema={
                "type": "object",
                "properties": {"issueKey": {"type": "string"}},
                "required": ["issueKey"],
            },
        ),
        Tool(
            name="jira_bulk_create_issues",
            description="Tạo nhiều issues cùng lúc (dùng để đồng bộ từ Google Sheets).",
            inputSchema={
                "type": "object",
                "properties": {
                    "projectKey": {"type": "string"},
                    "issues": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "summary": {"type": "string"},
                                "description": {"type": "string"},
                                "issueType": {"type": "string"},
                                "priority": {"type": "string"},
                            },
                            "required": ["summary"],
                        },
                    },
                },
                "required": ["projectKey", "issues"],
            },
        ),
        Tool(
            name="jira_get_project_info",
            description="Lấy thông tin chi tiết về một Jira project.",
            inputSchema={
                "type": "object",
                "properties": {"projectKey": {"type": "string"}},
                "required": ["projectKey"],
            },
        ),
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    base_url = os.getenv("JIRA_BASE_URL", "").rstrip("/")

    def ok(data: dict) -> list[TextContent]:
        return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False))]

    def err(msg: str) -> list[TextContent]:
        return [TextContent(type="text", text=json.dumps({"success": False, "error": msg}, ensure_ascii=False))]

    try:
        if name == "jira_get_issue":
            data = await jira_request("GET", f"/issue/{arguments['issueKey']}")
            f = data["fields"]
            return ok({
                "success": True,
                "issue": {
                    "key": data["key"],
                    "summary": f.get("summary"),
                    "status": (f.get("status") or {}).get("name"),
                    "assignee": (f.get("assignee") or {}).get("displayName"),
                    "reporter": (f.get("reporter") or {}).get("displayName"),
                    "priority": (f.get("priority") or {}).get("name"),
                    "issueType": (f.get("issuetype") or {}).get("name"),
                    "created": f.get("created"),
                    "updated": f.get("updated"),
                    "labels": f.get("labels", []),
                    "url": f"{base_url}/browse/{data['key']}",
                },
            })

        elif name == "jira_search_issues":
            data = await jira_request("POST", "/search", {
                "jql": arguments["jql"],
                "maxResults": arguments.get("maxResults", 50),
                "fields": ["summary", "status", "assignee", "priority", "issuetype", "created", "updated", "labels"],
            })
            issues = [
                {
                    "key": i["key"],
                    "summary": i["fields"].get("summary"),
                    "status": (i["fields"].get("status") or {}).get("name"),
                    "assignee": (i["fields"].get("assignee") or {}).get("displayName"),
                    "priority": (i["fields"].get("priority") or {}).get("name"),
                    "issueType": (i["fields"].get("issuetype") or {}).get("name"),
                    "created": i["fields"].get("created"),
                    "url": f"{base_url}/browse/{i['key']}",
                }
                for i in data.get("issues", [])
            ]
            return ok({"success": True, "total": data.get("total"), "returned": len(issues), "issues": issues})

        elif name == "jira_create_issue":
            body: dict = {
                "fields": {
                    "project": {"key": arguments["projectKey"]},
                    "summary": arguments["summary"],
                    "issuetype": {"name": arguments.get("issueType", "Task")},
                }
            }
            if arguments.get("description"):
                body["fields"]["description"] = make_description_doc(arguments["description"])
            if arguments.get("priority"):
                body["fields"]["priority"] = {"name": arguments["priority"]}
            if arguments.get("labels"):
                body["fields"]["labels"] = arguments["labels"]
            data = await jira_request("POST", "/issue", body)
            return ok({
                "success": True,
                "issueKey": data["key"],
                "url": f"{base_url}/browse/{data['key']}",
                "message": f"Issue {data['key']} đã được tạo thành công",
            })

        elif name == "jira_update_issue":
            fields: dict = {}
            if arguments.get("summary"): fields["summary"] = arguments["summary"]
            if arguments.get("description"): fields["description"] = make_description_doc(arguments["description"])
            if arguments.get("priority"): fields["priority"] = {"name": arguments["priority"]}
            if arguments.get("labels"): fields["labels"] = arguments["labels"]
            await jira_request("PUT", f"/issue/{arguments['issueKey']}", {"fields": fields})
            return ok({"success": True, "message": f"Issue {arguments['issueKey']} đã được cập nhật"})

        elif name == "jira_transition_issue":
            trans_data = await jira_request("GET", f"/issue/{arguments['issueKey']}/transitions")
            transitions = trans_data.get("transitions", [])
            target = next(
                (t for t in transitions
                 if t["name"].lower() == arguments["transitionName"].lower()
                 or t["to"]["name"].lower() == arguments["transitionName"].lower()),
                None,
            )
            if not target:
                available = [t["name"] for t in transitions]
                raise Exception(f"Không tìm thấy transition '{arguments['transitionName']}'. Có sẵn: {', '.join(available)}")
            await jira_request("POST", f"/issue/{arguments['issueKey']}/transitions", {"transition": {"id": target["id"]}})
            return ok({"success": True, "message": f"Issue {arguments['issueKey']} → '{target['to']['name']}'"})

        elif name == "jira_add_comment":
            data = await jira_request("POST", f"/issue/{arguments['issueKey']}/comment", {
                "body": make_description_doc(arguments["comment"])
            })
            return ok({"success": True, "commentId": data.get("id"), "message": f"Đã thêm comment vào {arguments['issueKey']}"})

        elif name == "jira_list_projects":
            data = await jira_request("GET", "/project/search?maxResults=50")
            projects = [
                {"id": p["id"], "key": p["key"], "name": p["name"],
                 "type": p.get("projectTypeKey"), "url": f"{base_url}/projects/{p['key']}"}
                for p in data.get("values", [])
            ]
            return ok({"success": True, "total": len(projects), "projects": projects})

        elif name == "jira_get_transitions":
            data = await jira_request("GET", f"/issue/{arguments['issueKey']}/transitions")
            return ok({
                "success": True,
                "transitions": [{"id": t["id"], "name": t["name"], "to": t["to"]["name"]} for t in data.get("transitions", [])],
            })

        elif name == "jira_bulk_create_issues":
            results, errors = [], []
            for issue in arguments["issues"]:
                try:
                    body: dict = {
                        "fields": {
                            "project": {"key": arguments["projectKey"]},
                            "summary": issue["summary"],
                            "issuetype": {"name": issue.get("issueType", "Task")},
                        }
                    }
                    if issue.get("description"):
                        body["fields"]["description"] = make_description_doc(issue["description"])
                    if issue.get("priority"):
                        body["fields"]["priority"] = {"name": issue["priority"]}
                    data = await jira_request("POST", "/issue", body)
                    results.append({"summary": issue["summary"], "key": data["key"], "url": f"{base_url}/browse/{data['key']}"})
                except Exception as e:
                    errors.append({"summary": issue["summary"], "error": str(e)})
            return ok({"success": True, "created": len(results), "failed": len(errors), "results": results, "errors": errors})

        elif name == "jira_get_project_info":
            data = await jira_request("GET", f"/project/{arguments['projectKey']}")
            return ok({
                "success": True,
                "project": {
                    "id": data["id"], "key": data["key"], "name": data["name"],
                    "description": data.get("description"),
                    "lead": (data.get("lead") or {}).get("displayName"),
                    "issueTypes": [t["name"] for t in data.get("issueTypes", [])],
                    "url": f"{base_url}/projects/{data['key']}",
                },
            })

        else:
            return err(f"Tool không tồn tại: {name}")

    except Exception as e:
        return err(str(e))

async def main():
    print("Jira MCP Server đang chạy...", file=sys.stderr)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
