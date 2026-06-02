Markdown
# ARC Trading Terminal & Journal

A professional-grade, real-time options tracking terminal and execution journal built with Streamlit. The system features automated data streaming via the Dhan API, persistent data storage via Google Sheets, and an intelligent NLP engine for instant Telegram/X signal parsing.

## Key Features

* **Institutional Interface:** Clean, high-contrast user interface styled with custom Champagne Gold branding accents.
* **Dual-Engine Architecture:** Complete separation of the frontend display presentation layer (`app.py`) from the backend structural logic layer (`backend.py`).
* **Automated Market Streaming:** A background daemon thread manages continuous live price updates every 5 minutes during Indian market hours (9:00 AM - 3:30 PM, Weekdays).
* **NLP Intelligence Input:** Instant parsing for multi-format trading alerts (including space-agnostic structures like `370CE` or `SL AT 9`).
* **Advanced Portfolio Filtering:** Dynamic sorting matrices covering multi-select sources, execution tracking tabs, performance indicators, and dedicated custom stock notes.

---

## Architecture Overview

```text
├── .streamlit/
│   └── config.toml       # Streamlit theme and canvas settings
├── app.py                # UI Layout, page views, and trade entry modal forms
├── backend.py            # Core engine, API calls, database connectors, and background schedulers
├── requirements.txt      # Python runtime dependency manifest
Prerequisites & Setup
1. Database Configuration (Google Sheets)
The terminal uses Google Sheets as a persistent relational database.

Create a Google Spreadsheet named Comprehensive Trading Tracker 2026.

Generate a Service Account key via the Google Cloud Console and share your spreadsheet with the service account email address.

The system will automatically create the primary Sheet1 schema headers (Live Price, Exit Price, Notes), an automated tracking sheet (Scanners), and an encrypted internal state sheet (Settings) on its initial initialization boot sequence.

2. Streamlit Cloud Secrets Configuration
To deploy the application securely, populate your Streamlit Cloud Dashboard Secret variables (Secrets) using the following structural layout:

Ini, TOML
[gcp_service_account]
type = "service_account"
project_id = "YOUR_PROJECT_ID"
private_key_id = "YOUR_KEY_ID"
private_key = "-----BEGIN PRIVATE KEY-----\nYOUR_KEY\n-----END PRIVATE KEY-----\n"
client_email = "YOUR_SERVICE_ACCOUNT_EMAIL"
client_id = "YOUR_CLIENT_ID"
auth_uri = "[https://accounts.google.com/o/oauth2/auth](https://accounts.google.com/o/oauth2/auth)"
token_uri = "[https://oauth2.googleapis.com/v2/token](https://oauth2.googleapis.com/v2/token)"
auth_provider_x509_cert_url = "[https://www.googleapis.com/oauth2/v1/certs](https://www.googleapis.com/oauth2/v1/certs)"
client_x509_cert_url = "[https://www.googleapis.com/robot/v1/metadata/x509/](https://www.googleapis.com/robot/v1/metadata/x509/)..."

[dhan]
dhan_client_id = "YOUR_DHAN_CLIENT_ID"
Local Development Deployment
To execute and verify the architecture locally on your development workstation:

Clone the repository manifest:

Bash
   git clone [https://github.com/your-username/your-repo-name.git](https://github.com/your-username/your-repo-name.git)
   cd your-repo-name
Initialize dependencies inside your environment wrapper:

Bash
   pip install -r requirements.txt
Launch the terminal layout:

Bash
   streamlit run app.py
Operational Guide
Daily API Initialization: Every morning, generate your 24-hour token block within the Dhan API Console, expand the Daily API Setup drawer in the sidebar panel, paste the key string, and click Save.

Logging Active Setup Positions: Click the primary Log New Trade action button to open the center popup window. You can drop raw text segments directly into the Quick Parse field to autofill contract technics.

Reviewing Performance Logs: Check the inline Inspect box on any active row layout inside your tables to open the technical review module and input psychological trade notes.
