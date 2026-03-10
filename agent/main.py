#!/usr/bin/env python3
"""
Gemini MCP Agent — Main Server (Python)
Kết nối Gemini AI với MCP servers qua subprocess stdio.
WebSocket + FastAPI để phục vụ Web UI.
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import google.generativeai as genai
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("agent")

# ── MCP Client Manager ────────────────────────────────────────────────────────

class MCPClientManager:
    """Quản lý kết nối stdio đến các MCP servers."""

    def __init__(self):
        self._sessions: dict[str, ClientSession] = {}
        self._tools: dict[str, dict] = {}   # tool_name → {session, server_name, schema}
        self._contexts: list = []            # context managers to keep alive

    async def connect_server(self, name: str, script_path: str):
        log.info(f"Đang kết nối MCP server: {name} ({script_path})")
        params = StdioServerParameters(
            command=sys.executable,
            args=[script_path],
            env=dict(os.environ),
        )
        ctx = stdio_client(params)
        streams = await ctx.__aenter__()
        self._contexts.append((ctx, streams))

        session = ClientSession(streams[0], streams[1])
        await session.__aenter__()
        await session.initialize()

        result = await session.list_tools()
        self._sessions[name] = session

        for tool in result.tools:
            self._tools[tool.name] = {
                "session": session,
                "server_name": name,
                "name": tool.name,
                "description": tool.description or "",
                "inputSchema": tool.inputSchema if isinstance(tool.inputSchema, dict) else (tool.inputSchema.model_dump() if hasattr(tool.inputSchema, "model_dump") else dict(tool.inputSchema)),
            }

        log.info(f"✅ {name}: {len(result.tools)} tools — {[t.name for t in result.tools]}")

    async def call_tool(self, tool_name: str, arguments: dict) -> Any:
        info = self._tools.get(tool_name)
        if not info:
            raise ValueError(f"Tool '{tool_name}' không tồn tại")
        log.info(f"🔧 MCP call: {tool_name} via {info['server_name']}")
        result = await info["session"].call_tool(tool_name, arguments)
        return result

    def get_gemini_tools(self) -> list:
        """Chuyển đổi MCP tools sang Gemini function declarations."""

        TYPE_MAP = {
            "string": genai.protos.Type.STRING,
            "number": genai.protos.Type.NUMBER,
            "integer": genai.protos.Type.INTEGER,
            "boolean": genai.protos.Type.BOOLEAN,
            "array": genai.protos.Type.ARRAY,
            "object": genai.protos.Type.OBJECT,
        }

        def build_schema(s: dict) -> genai.protos.Schema:
            proto_type = TYPE_MAP.get(s.get("type", "string"), genai.protos.Type.STRING)
            kwargs: dict = {"type_": proto_type}
            if s.get("description"):
                kwargs["description"] = s["description"]
            if proto_type == genai.protos.Type.OBJECT and s.get("properties"):
                kwargs["properties"] = {k: build_schema(v) for k, v in s["properties"].items()}
                if s.get("required"):
                    kwargs["required"] = s["required"]
            if proto_type == genai.protos.Type.ARRAY and s.get("items"):
                kwargs["items"] = build_schema(s["items"])
            return genai.protos.Schema(**kwargs)

        declarations = []
        for tool in self._tools.values():
            try:
                schema = tool.get("inputSchema") or {}
                declarations.append(
                    genai.protos.FunctionDeclaration(
                        name=tool["name"],
                        description=tool["description"],
                        parameters=build_schema(schema),
                    )
                )
            except Exception as e:
                import logging
                logging.getLogger("agent").warning(f"Bỏ qua tool {tool['name']}: {e}")
        return declarations

    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    async def shutdown(self):
        for session in self._sessions.values():
            try:
                await session.__aexit__(None, None, None)
            except Exception:
                pass
        for ctx, _ in self._contexts:
            try:
                await ctx.__aexit__(None, None, None)
            except Exception:
                pass


# ── Gemini Agent ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Bạn là một AI Agent thông minh chuyên quản lý Google Sheets và Jira thông qua MCP (Model Context Protocol).

Khả năng của bạn:
- 📊 Google Sheets: Đọc/ghi/cập nhật dữ liệu, tìm kiếm, tạo sheets mới
- 🎯 Jira: Tạo/cập nhật issues, chuyển trạng thái, thêm comments, tìm kiếm
- 🔄 Đồng bộ: Sync dữ liệu từ Sheets sang Jira và ngược lại

Nguyên tắc:
1. LUÔN dùng MCP tools để thực hiện tác vụ — không tự xử lý dữ liệu
2. Giải thích rõ từng bước bạn đang làm
3. Báo cáo kết quả chi tiết sau mỗi tác vụ
4. Trả lời bằng tiếng Việt (trừ khi được yêu cầu khác)
5. Dùng emoji để dễ đọc"""


class GeminiAgent:
    def __init__(self, mcp: MCPClientManager):
        self.mcp = mcp
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        self._histories: dict[str, list] = {}

    def _get_model(self):
        tool_declarations = self.mcp.get_gemini_tools()
        return genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            tools=[genai.protos.Tool(function_declarations=tool_declarations)],
            system_instruction=SYSTEM_PROMPT,
        )

    async def chat(self, session_id: str, user_message: str, on_progress=None):
        model = self._get_model()
        history = self._histories.get(session_id, [])

        chat_session = model.start_chat(history=history)

        if on_progress:
            await on_progress({"type": "thinking", "message": " Đang phân tích yêu cầu..."})

        response = await asyncio.to_thread(chat_session.send_message, user_message)

        # Vòng lặp xử lý function calls
        while True:
            candidate = response.candidates[0]
            # Kiểm tra có function call không
            fn_calls = [
                part.function_call
                for part in candidate.content.parts
                if part.function_call.name  # non-empty name = valid call
            ]
            if not fn_calls:
                break

            fn_responses = []
            for fn_call in fn_calls:
                tool_name = fn_call.name
                tool_args = dict(fn_call.args)

                if on_progress:
                    await on_progress({
                        "type": "tool_call",
                        "tool": tool_name,
                        "message": f"🔧 Đang gọi tool: **{tool_name}**",
                    })

                try:
                    result = await self.mcp.call_tool(tool_name, tool_args)
                    result_text = ""
                    if result.content:
                        result_text = "\n".join(
                            c.text for c in result.content if hasattr(c, "text")
                        )
                    is_error = getattr(result, "isError", False)

                    if on_progress:
                        await on_progress({
                            "type": "tool_result",
                            "tool": tool_name,
                            "success": not is_error,
                            "message": f"{'❌' if is_error else '✅'} Tool {tool_name} {'thất bại' if is_error else 'hoàn thành'}",
                        })

                    fn_responses.append(
                        genai.protos.Part(
                            function_response=genai.protos.FunctionResponse(
                                name=tool_name,
                                response={"result": result_text},
                            )
                        )
                    )
                except Exception as e:
                    if on_progress:
                        await on_progress({
                            "type": "tool_error",
                            "tool": tool_name,
                            "message": f"❌ Lỗi {tool_name}: {e}",
                        })
                    fn_responses.append(
                        genai.protos.Part(
                            function_response=genai.protos.FunctionResponse(
                                name=tool_name,
                                response={"error": str(e)},
                            )
                        )
                    )

            response = await asyncio.to_thread(chat_session.send_message, fn_responses)

        # Lấy text cuối cùng
        final_text = "".join(
            part.text for part in response.candidates[0].content.parts if hasattr(part, "text")
        )

        # Lưu history
        self._histories[session_id] = chat_session.history
        return final_text

    def clear_history(self, session_id: str):
        self._histories.pop(session_id, None)


# ── FastAPI + WebSocket ───────────────────────────────────────────────────────

app = FastAPI(title="Gemini MCP Agent")

mcp_manager: MCPClientManager = None
gemini_agent: GeminiAgent = None

PUBLIC_DIR = Path(__file__).parent / "public"
app.mount("/static", StaticFiles(directory=str(PUBLIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def root():
    index = PUBLIC_DIR / "index.html"
    return HTMLResponse(index.read_text(encoding="utf-8"))


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "tools": mcp_manager.tool_names() if mcp_manager else [],
    }


@app.get("/api/tools")
async def tools():
    if not mcp_manager:
        return {"tools": []}
    return {
        "tools": [
            {"name": n, "server": info["server_name"], "description": info["description"]}
            for n, info in mcp_manager._tools.items()
        ]
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session_id = os.urandom(5).hex()
    log.info(f"👤 WS connected: {session_id}")

    await ws.send_json({
        "type": "connected",
        "sessionId": session_id,
        "tools": mcp_manager.tool_names() if mcp_manager else [],
    })

    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)

            if data.get("action") == "clear_history":
                gemini_agent.clear_history(session_id)
                await ws.send_json({"type": "history_cleared", "message": "Đã xóa lịch sử hội thoại"})
                continue

            message = data.get("message", "").strip()
            if not message:
                continue

            async def send_progress(p):
                await ws.send_json({"type": "progress", **p})

            try:
                response = await gemini_agent.chat(session_id, message, on_progress=send_progress)
                await ws.send_json({"type": "response", "message": response})
            except Exception as e:
                log.error(f"Chat error: {e}", exc_info=True)
                await ws.send_json({"type": "error", "message": str(e)})

    except WebSocketDisconnect:
        log.info(f"👋 WS disconnected: {session_id}")


# ── Startup / Shutdown ────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    global mcp_manager, gemini_agent

    # Validate env
    required = ["GEMINI_API_KEY", "JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        log.error(f"Thiếu environment variables: {missing}")
        sys.exit(1)

    mcp_manager = MCPClientManager()

    sheets_script = str(ROOT / "mcp_servers" / "sheets_server.py")
    jira_script = str(ROOT / "mcp_servers" / "jira_server.py")

    try:
        await mcp_manager.connect_server("sheets", sheets_script)
    except Exception as e:
        log.warning(f"Sheets MCP không kết nối được: {e}")

    try:
        await mcp_manager.connect_server("jira", jira_script)
    except Exception as e:
        log.warning(f"Jira MCP không kết nối được: {e}")

    gemini_agent = GeminiAgent(mcp_manager)
    log.info(f"🚀 Agent sẵn sàng — {len(mcp_manager.tool_names())} tools")


@app.on_event("shutdown")
async def shutdown():
    if mcp_manager:
        await mcp_manager.shutdown()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 3000))
    log.info(f"Khởi động tại http://localhost:{port}")
    uvicorn.run("agent.main:app", host="0.0.0.0", port=port, reload=False)
