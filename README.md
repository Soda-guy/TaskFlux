⚡ TaskFlux
A smarter Task Manager with security instincts
Clean. Fast. Free. Open‑source.

TaskFlux is a lightweight system monitor built with Python + PySide6.
It blends real‑time performance monitoring with intelligent process analysis, threat detection, and a clean, modern UI.

If you’ve ever wished Windows Task Manager had a brain — this is it.

✨ Features
🖥 Dashboard
Live CPU, RAM, GPU, and temperature monitoring

Per‑core usage

Disk & network activity

System Health Score

“Top Issues” panel for quick diagnostics

🔍 Process Intelligence
Suspicion scoring (healthy → dangerous)

Filters: High CPU, High RAM, User/System, Suspicious, Recently Spawned

Search, sort, freeze view

Inspector panel with detailed metadata

Kill / Kill Tree

Open file location

🛡 Threats View
Auto‑filtered risky/dangerous processes

Color‑coded severity

Real‑time updates

🚀 Startup Manager
Clean list of startup entries

File location shortcuts

⚙ Services Viewer
Search + filter by status/start type

Clean, readable table layout

📜 Logs
Process events

Threat alerts

System actions

Timestamped

Filterable

Auto‑scroll

🔧 Settings
Adjustable refresh rates

Splash screen toggle

Show/hide system processes

Auto‑sort mode

Settings saved to JSON

🚀 Installation
1. Install Python 3.10+
Download from:
https://www.python.org/downloads/

Make sure “Add Python to PATH” is checked.

2. Install dependencies
Inside the TaskFlux folder:

Code
pip install -r requirements.txt
3. Run TaskFlux
Code
python app.py
TaskFlux will launch with the splash screen and load the full dashboard UI.

🏗 Building a Windows EXE (Optional)
Yes — you can post TaskFlux as an .exe on GitHub.

Here’s how to build it:

Code
pyinstaller --noconsole --onefile --icon=taskflux_logo.png app.py
Your executable will appear in:

Code
dist/TaskFlux.exe
You can upload that .exe to your GitHub Releases page so users can download it without installing Python.

📦 Project Structure
Code
TaskFlux/
│
├── app.py
├── core.py
├── taskflux_logo.png
│
├── README.md
├── LICENSE
├── requirements.txt
├── .gitignore
│
└── screenshots/
📄 License
TaskFlux is released under the MIT License.

A small optional request is included:
If you use or build on TaskFlux, a simple credit to Drew is appreciated — but not required.

❤️ Credits
Created by: Drew
AI‑assisted development: Microsoft Copilot

🆕 What’s New in TaskFlux v2
Full UI overhaul

Hybrid cinematic splash screen

Process filters + freeze mode

Threats page with severity scoring

Startup & Services pages redesigned

Settings with JSON persistence

Log filtering + autoscroll

Performance optimizations

PID 0/4 spam removed

Cleaner, smoother, more stable
