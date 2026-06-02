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
