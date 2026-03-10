#!/usr/bin/env python3
"""
Setup wizard — hướng dẫn cấu hình từng bước.
Chạy: python setup.py
"""
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).parent
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
CONFIG_DIR = ROOT / "config"


def prompt(question: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"{question}{suffix}: ").strip()
    return val or default


def get_current(key: str, content: str) -> str:
    for line in content.splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


def set_value(key: str, value: str, content: str) -> str:
    if f"{key}=" in content:
        lines = []
        for line in content.splitlines():
            lines.append(f"{key}={value}" if line.startswith(f"{key}=") else line)
        return "\n".join(lines)
    return content + f"\n{key}={value}"


def main():
    print("""
╔══════════════════════════════════════════════╗
║    Gemini MCP Agent (Python) — Setup         ║
╚══════════════════════════════════════════════╝
""")

    # Đọc/tạo .env
    if ENV_FILE.exists():
        content = ENV_FILE.read_text()
        print("✅ File .env đã tồn tại\n")
    else:
        content = ENV_EXAMPLE.read_text()
        print("📝 Tạo .env từ .env.example\n")

    # ── Gemini ──
    print("── Gemini API ──")
    cur = get_current("GEMINI_API_KEY", content)
    if not cur or "your_gemini" in cur:
        key = prompt("🔑 Gemini API Key (https://aistudio.google.com/)")
        content = set_value("GEMINI_API_KEY", key, content)
    else:
        print(f"✅ GEMINI_API_KEY: {cur[:10]}...")

    # ── Jira ──
    print("\n── Jira ──")
    for env_key, label, hint in [
        ("JIRA_BASE_URL", "Jira URL", "https://mycompany.atlassian.net"),
        ("JIRA_EMAIL", "Email Jira", "your@email.com"),
        ("JIRA_API_TOKEN", "API Token (https://id.atlassian.com/manage-profile/security/api-tokens)", ""),
        ("JIRA_PROJECT_KEY", "Project Key mặc định", "MYPROJ"),
    ]:
        cur = get_current(env_key, content)
        placeholder_words = ["your", "atlassian.net", "YOUR"]
        if not cur or any(w in cur for w in placeholder_words):
            val = prompt(f"  {label} [{hint}]" if hint else f"  {label}")
            content = set_value(env_key, val.upper() if env_key == "JIRA_PROJECT_KEY" else val, content)
        else:
            display = cur[:10] + "..." if len(cur) > 10 else cur
            print(f"✅ {env_key}: {display}")

    # ── Google Sheets ──
    print("\n── Google Sheets ──")
    sa_path = CONFIG_DIR / "google-service-account.json"
    if sa_path.exists():
        print("✅ google-service-account.json đã có")
    else:
        print(f"""
⚠️  Chưa có Service Account credentials.

Hướng dẫn:
  1. Vào https://console.cloud.google.com/
  2. Tạo project → Enable "Google Sheets API" + "Google Drive API"
  3. IAM & Admin → Service Accounts → Create → Tạo JSON Key → Download
  4. Đổi tên thành google-service-account.json
  5. Đặt vào: {CONFIG_DIR}/
""")
    content = set_value("GOOGLE_SERVICE_ACCOUNT_PATH", "./config/google-service-account.json", content)

    # Lưu .env
    ENV_FILE.write_text(content)
    print("\n✅ .env đã được lưu!\n")
    print("""Bước tiếp theo:
  1. Đặt google-service-account.json vào ./config/ (nếu chưa có)
  2. Chia sẻ Spreadsheet với email của Service Account
  3. Chạy: python run.py
  4. Mở:  http://localhost:3000
""")


if __name__ == "__main__":
    main()
