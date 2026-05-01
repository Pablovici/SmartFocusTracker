# SmartFocusTracker

Indoor/outdoor weather monitoring system with work session tracking,
built with M5Stack IoT devices and Google Cloud.

## Team
- **Amir** — Device UI (M5Stack A & B) + Streamlit Dashboard
- **Pablo** — Flask Middleware + BigQuery

## Project Structure
- `device_a/` — MicroPython code for M5Stack A (main device)
- `device_b/` — MicroPython code for M5Stack B (satellite)
- `middleware/` — Flask API deployed on Google Cloud Run
- `dashboard/` — Streamlit web dashboard

## Setup
1. Clone this repository
2. Copy `.env.example` to `.env` and fill in your values
3. Add your `gcp_service_account.json` to the root (never commit this)
4. See each folder for specific deployment instructions

## Video
<!-- TODO: add YouTube link when available -->