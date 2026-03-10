#!/usr/bin/env python3
"""
Google Sheets MCP Server
Cung cấp tools để tương tác với Google Sheets qua MCP protocol.
100% gọi thẳng lên Google Sheets API — không lưu dữ liệu cục bộ.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

def get_gspread_client() -> gspread.Client:
    sa_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH", "./config/google-service-account.json")
    sa_path = (ROOT / sa_path) if not Path(sa_path).is_absolute() else Path(sa_path)
    if not sa_path.exists():
        raise FileNotFoundError(f"Service account JSON không tìm thấy: {sa_path}")
    creds = Credentials.from_service_account_file(str(sa_path), scopes=SCOPES)
    return gspread.authorize(creds)

server = Server("google-sheets-mcp")

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="sheets_read_range",
            description="Đọc dữ liệu từ một vùng (range) trong Google Sheets.",
            inputSchema={
                "type": "object",
                "properties": {
                    "spreadsheetId": {"type": "string", "description": "ID của spreadsheet (lấy từ URL)"},
                    "range": {"type": "string", "description": "Range cần đọc, ví dụ: Sheet1!A1:E10"},
                },
                "required": ["spreadsheetId", "range"],
            },
        ),
        Tool(
            name="sheets_write_range",
            description="Ghi dữ liệu vào một vùng trong Google Sheets.",
            inputSchema={
                "type": "object",
                "properties": {
                    "spreadsheetId": {"type": "string"},
                    "range": {"type": "string", "description": "Range bắt đầu ghi, ví dụ: Sheet1!A1"},
                    "values": {
                        "type": "array",
                        "description": "Mảng 2D: [[row1col1, row1col2], [row2col1, ...]]",
                        "items": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "required": ["spreadsheetId", "range", "values"],
            },
        ),
        Tool(
            name="sheets_append_rows",
            description="Thêm các hàng mới vào cuối dữ liệu trong một sheet.",
            inputSchema={
                "type": "object",
                "properties": {
                    "spreadsheetId": {"type": "string"},
                    "sheetName": {"type": "string", "description": "Tên sheet, ví dụ: Sheet1"},
                    "values": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "required": ["spreadsheetId", "sheetName", "values"],
            },
        ),
        Tool(
            name="sheets_get_sheet_info",
            description="Lấy thông tin spreadsheet: tiêu đề, danh sách sheets, số hàng/cột.",
            inputSchema={
                "type": "object",
                "properties": {
                    "spreadsheetId": {"type": "string"},
                },
                "required": ["spreadsheetId"],
            },
        ),
        Tool(
            name="sheets_create_sheet",
            description="Tạo một sheet mới trong spreadsheet.",
            inputSchema={
                "type": "object",
                "properties": {
                    "spreadsheetId": {"type": "string"},
                    "sheetTitle": {"type": "string", "description": "Tên sheet mới"},
                },
                "required": ["spreadsheetId", "sheetTitle"],
            },
        ),
        Tool(
            name="sheets_clear_range",
            description="Xóa toàn bộ dữ liệu trong một vùng của Google Sheets.",
            inputSchema={
                "type": "object",
                "properties": {
                    "spreadsheetId": {"type": "string"},
                    "range": {"type": "string", "description": "Range cần xóa, ví dụ: Sheet1!A2:Z100"},
                },
                "required": ["spreadsheetId", "range"],
            },
        ),
        Tool(
            name="sheets_update_cell",
            description="Cập nhật giá trị của một ô cụ thể.",
            inputSchema={
                "type": "object",
                "properties": {
                    "spreadsheetId": {"type": "string"},
                    "cell": {"type": "string", "description": "Địa chỉ ô, ví dụ: Sheet1!B5"},
                    "value": {"type": "string"},
                },
                "required": ["spreadsheetId", "cell", "value"],
            },
        ),
        Tool(
            name="sheets_find_row",
            description="Tìm hàng trong Sheets theo giá trị của một cột.",
            inputSchema={
                "type": "object",
                "properties": {
                    "spreadsheetId": {"type": "string"},
                    "sheetName": {"type": "string", "description": "Tên sheet"},
                    "searchColumn": {"type": "integer", "description": "Index cột tìm kiếm (0-based)"},
                    "searchValue": {"type": "string", "description": "Giá trị cần tìm"},
                },
                "required": ["spreadsheetId", "sheetName", "searchColumn", "searchValue"],
            },
        ),
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    def ok(data: dict) -> list[TextContent]:
        return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False))]

    def err(msg: str) -> list[TextContent]:
        return [TextContent(type="text", text=json.dumps({"success": False, "error": msg}, ensure_ascii=False))]

    try:
        gc = get_gspread_client()

        if name == "sheets_read_range":
            sh = gc.open_by_key(arguments["spreadsheetId"])
            values = sh.values_get(arguments["range"]).get("values", [])
            return ok({
                "success": True,
                "range": arguments["range"],
                "rowCount": len(values),
                "columnCount": len(values[0]) if values else 0,
                "values": values,
            })

        elif name == "sheets_write_range":
            sh = gc.open_by_key(arguments["spreadsheetId"])
            result = sh.values_update(
                arguments["range"],
                params={"valueInputOption": "USER_ENTERED"},
                body={"values": arguments["values"]},
            )
            return ok({
                "success": True,
                "updatedRange": result.get("updatedRange"),
                "updatedRows": result.get("updatedRows"),
                "updatedCells": result.get("updatedCells"),
            })

        elif name == "sheets_append_rows":
            sh = gc.open_by_key(arguments["spreadsheetId"])
            ws = sh.worksheet(arguments["sheetName"])
            ws.append_rows(arguments["values"], value_input_option="USER_ENTERED")
            return ok({"success": True, "appendedRows": len(arguments["values"])})

        elif name == "sheets_get_sheet_info":
            sh = gc.open_by_key(arguments["spreadsheetId"])
            sheets_info = [
                {
                    "title": ws.title,
                    "sheetId": ws.id,
                    "rowCount": ws.row_count,
                    "columnCount": ws.col_count,
                }
                for ws in sh.worksheets()
            ]
            return ok({"success": True, "info": {"title": sh.title, "spreadsheetId": sh.id, "sheets": sheets_info}})

        elif name == "sheets_create_sheet":
            sh = gc.open_by_key(arguments["spreadsheetId"])
            sh.add_worksheet(title=arguments["sheetTitle"], rows=1000, cols=26)
            return ok({"success": True, "message": f"Sheet '{arguments['sheetTitle']}' đã được tạo"})

        elif name == "sheets_clear_range":
            sh = gc.open_by_key(arguments["spreadsheetId"])
            sh.values_clear(arguments["range"])
            return ok({"success": True, "message": f"Đã xóa dữ liệu trong range {arguments['range']}"})

        elif name == "sheets_update_cell":
            sh = gc.open_by_key(arguments["spreadsheetId"])
            sh.values_update(
                arguments["cell"],
                params={"valueInputOption": "USER_ENTERED"},
                body={"values": [[arguments["value"]]]},
            )
            return ok({"success": True, "message": f"Đã cập nhật {arguments['cell']} = '{arguments['value']}'"})

        elif name == "sheets_find_row":
            sh = gc.open_by_key(arguments["spreadsheetId"])
            ws = sh.worksheet(arguments["sheetName"])
            all_values = ws.get_all_values()
            col_idx = arguments["searchColumn"]
            search_val = arguments["searchValue"]
            found = [
                {"rowIndex": i + 1, "data": row}
                for i, row in enumerate(all_values)
                if len(row) > col_idx and row[col_idx] == search_val
            ]
            return ok({"success": True, "found": len(found) > 0, "count": len(found), "rows": found})

        else:
            return err(f"Tool không tồn tại: {name}")

    except Exception as e:
        return err(str(e))

async def main():
    print("Google Sheets MCP Server đang chạy...", file=sys.stderr)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
