#!/usr/bin/env python3
"""
Entry point — chạy: python run.py
"""
import os
import sys
from pathlib import Path

# Thêm project root vào path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("PORT", 3000))
    print(f"\n🚀 Gemini MCP Agent đang khởi động...")
    print(f"📡 Địa chỉ: http://localhost:{port}\n")
    uvicorn.run(
        "agent.main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
    )
