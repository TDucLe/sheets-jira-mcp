# 🤖 Gemini MCP Agent (Python)

AI Agent sử dụng **Google Gemini** để kết nối **Google Sheets** và **Jira** thông qua **Model Context Protocol (MCP)**.

---

## 📋 Yêu cầu hệ thống

| Component | Yêu cầu |
|---|---|
| Python | >= 3.10 |
| Google Cloud | Service Account JSON |
| Jira | Cloud + API Token |
| Gemini | API Key |

---

## ⚡ Cài đặt nhanh
```bash
# 1. Tạo virtual environment
python -m venv venv
source venv/bin/activate      # Linux / Mac
venv\Scripts\activate         # Windows

# 2. Cài dependencies
pip install -r requirements.txt

# 3. Setup wizard
python setup.py

# 4. Thêm file credentials vào config/google-service-account.json

# 5. Chạy agent
python run.py

# 6. Mở trình duyệt: http://localhost:3000
```

---

## 🔑 Lấy Credentials

### Gemini API Key

1. Truy cập [Google AI Studio](https://aistudio.google.com)
2. Chọn **Get API Key** → **Create API Key**
3. Copy key vào `.env`

### Jira API Token

1. Truy cập [Atlassian API Tokens](https://id.atlassian.com/manage-profile/security/api-tokens)
2. Chọn **Create API token** → đặt tên → copy token

### Google Service Account

1. Truy cập [Google Cloud Console](https://console.cloud.google.com)
2. Tạo project mới
3. Vào **APIs & Services → Library**, enable:
   - `Google Sheets API`
   - `Google Drive API`
4. Vào **IAM & Admin → Service Accounts → Create Service Account**
5. Tạo **JSON Key** → download
6. Đổi tên thành `google-service-account.json`, đặt vào `config/`
7. Mở Google Spreadsheet → **Share** → paste `client_email` → chọn **Editor**

---

## ⚙️ Cấu hình `.env`
```env
GEMINI_API_KEY=your_gemini_api_key

GOOGLE_SERVICE_ACCOUNT_PATH=./config/google-service-account.json

JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your@email.com
JIRA_API_TOKEN=your_jira_api_token
JIRA_PROJECT_KEY=MYPROJ

PORT=3000
```

---

## 📁 Cấu trúc Project
```
gemini-mcp-agent-py/
├── run.py                           # Entry point
├── setup.py                         # Setup wizard
├── requirements.txt
├── .env.example
├── agent/
│   ├── main.py                      # FastAPI + WebSocket + Gemini
│   └── public/
│       └── index.html               # Web UI
├── mcp_servers/
│   ├── sheets_server.py             # Google Sheets MCP Server
│   └── jira_server.py               # Jira MCP Server
└── config/
    └── google-service-account.json  # Tự thêm, không commit
```

---

## 💬 Ví dụ lệnh
```
Đọc dữ liệu range Sheet1!A1:E20 trong spreadsheet [SPREADSHEET_ID]
```
```
Tạo Jira issue: "Fix login bug" trong project MYPROJ, loại Bug, priority High
```
```
Đọc sheet Tasks (A2:D50), tạo Jira issues trong project MYPROJ cho các hàng có cột D = "Todo"
```
```
Tìm tất cả issues In Progress trong MYPROJ rồi chuyển sang Done
```

---

## 🏗️ Kiến trúc
```
Browser ←WS→ FastAPI/main.py ←stdio MCP→ sheets_server.py → Google Sheets API
                             ←stdio MCP→ jira_server.py   → Jira REST API
                    ↕
              Gemini 2.5 Flash
```

| `WebSocket 403` | Sai route | Đảm bảo HTML kết nối đến `ws://localhost:3000/ws` |
| `call_tool() takes 1 positional argument` | Sai MCP SDK version | Cập nhật handler: `async def call_tool(name: str, arguments: dict)` |
