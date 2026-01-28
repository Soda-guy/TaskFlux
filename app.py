import sys
import os
import time
import json
import subprocess
from collections import deque
from datetime import datetime

import psutil

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QIcon, QColor, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QStackedWidget, QTableWidget,
    QTableWidgetItem, QFileDialog, QTextEdit, QGroupBox, QProgressBar,
    QSplitter, QFrame, QLineEdit, QComboBox, QCheckBox
)

from core import (
    get_cpu_overview,
    get_ram_overview,
    get_gpu_overview,
    get_disk_net_overview,
    get_temps_overview,
    get_process_snapshot,
    export_snapshot_to_json,
    list_startup_entries,
    list_services_summary,
    load_plugins,
)


SETTINGS_PATH = "taskflux_settings.json"


def make_progress_bar():
    bar = QProgressBar()
    bar.setMinimum(0)
    bar.setMaximum(100)
    bar.setTextVisible(True)
    bar.setFixedHeight(18)
    return bar


def load_settings():
    default = {
        "refresh_rate_ms": 1500,      # slightly slower = smoother
        "proc_refresh_ms": 5000,      # less frequent heavy process scan
        "show_splash": True,
        "show_system_processes": False,
        "auto_sort_processes": "CPU",
        "theme": "neon",
    }
    if not os.path.isfile(SETTINGS_PATH):
        return default
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        default.update(data)
    except Exception:
        pass
    return default


def save_settings(settings):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except Exception:
        pass


class SplashScreen(QWidget):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.resize(520, 260)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(24, 24, 24, 24)
        container_layout.setSpacing(12)

        # Logo
        logo = QLabel()
        pix = QPixmap("taskflux_logo.png")
        if not pix.isNull():
            logo.setPixmap(pix)
        logo.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        container_layout.addWidget(logo)

        # Tagline
        subtitle = QLabel("System Performance & Process Intelligence")
        subtitle.setStyleSheet("font-size: 13px; color: #9CA3AF;")
        container_layout.addWidget(subtitle)

        # Status text
        self.status = QLabel("Initializing TaskFlux...")
        self.status.setStyleSheet("font-size: 12px; color: #9CA3AF;")
        container_layout.addWidget(self.status)

        # Scan bar
        self.scan_bar = QProgressBar()
        self.scan_bar.setRange(0, 0)  # indeterminate
        self.scan_bar.setFixedHeight(6)
        self.scan_bar.setTextVisible(False)
        self.scan_bar.setStyleSheet("""
            QProgressBar {
                background-color: #020617;
                border-radius: 3px;
                border: 1px solid #1F2933;
            }
            QProgressBar::chunk {
                background-color: #00C6FF;
            }
        """)
        container_layout.addWidget(self.scan_bar)

        container_layout.addStretch(1)

        frame = QFrame()
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.addWidget(container)

        frame.setStyleSheet("""
            QFrame {
                background-color: #020617;
                border-radius: 12px;
                border: 1px solid #1F2933;
            }
        """)

        layout.addStretch(1)
        layout.addWidget(frame, alignment=Qt.AlignCenter)
        layout.addStretch(1)

    def set_status(self, text: str):
        self.status.setText(text)


class TaskFluxWindow(QMainWindow):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings

        self.setWindowTitle("TaskFlux — System Performance & Process Intelligence")
        self.resize(1360, 800)

        self.prev_disk = None
        self.prev_net = None
        self.last_tick = time.time()

        self.known_pids = set()
        self.net_history = deque(maxlen=60)
        self.disk_history = deque(maxlen=60)

        self.current_proc_filter = "All"
        self.current_proc_search = ""
        self.proc_frozen = False

        self.current_log_filter = "All"

        self._build_ui()
        self._apply_theme()
        self._setup_timers()
        self._load_plugins()

    # ---------- UI BUILD ----------

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)

        # Sidebar
        self.sidebar = QListWidget()
        self.sidebar.addItem("Dashboard")
        self.sidebar.addItem("Processes")
        self.sidebar.addItem("Threats")
        self.sidebar.addItem("Startup")
        self.sidebar.addItem("Services")
        self.sidebar.addItem("Logs")
        self.sidebar.addItem("Export")
        self.sidebar.addItem("Settings")
        self.sidebar.currentRowChanged.connect(self._change_page)
        self.sidebar.setFixedWidth(210)
        self.sidebar.setObjectName("Sidebar")

        # Pages
        self.pages = QStackedWidget()
        self.pages.setObjectName("Pages")

        self.page_dashboard = self._build_dashboard_page()
        self.page_processes = self._build_process_page()
        self.page_threats = self._build_threats_page()
        self.page_startup = self._build_startup_page()
        self.page_services = self._build_services_page()
        self.page_logs = self._build_logs_page()
        self.page_export = self._build_export_page()
        self.page_settings = self._build_settings_page()

        self.pages.addWidget(self.page_dashboard)
        self.pages.addWidget(self.page_processes)
        self.pages.addWidget(self.page_threats)
        self.pages.addWidget(self.page_startup)
        self.pages.addWidget(self.page_services)
        self.pages.addWidget(self.page_logs)
        self.pages.addWidget(self.page_export)
        self.pages.addWidget(self.page_settings)

        layout.addWidget(self.sidebar)
        layout.addWidget(self.pages, 1)

        self.sidebar.setCurrentRow(0)

    def _apply_theme(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #020617;
            }
            #Sidebar {
                background-color: #020617;
                border-right: 1px solid #1E2933;
                color: #E5E9F0;
            }
            QListWidget::item {
                padding: 10px 12px;
            }
            QListWidget::item:selected {
                background-color: #0EA5E9;
                color: #020617;
            }
            QStackedWidget#Pages {
                background-color: #020617;
            }
            QGroupBox {
                border: 1px solid #1F2933;
                border-radius: 8px;
                margin-top: 18px;
                background-color: #020617;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
                color: #7DD3FC;
                background-color: #020617;
            }
            QLabel {
                color: #E5E9F0;
            }
            QTextEdit {
                background-color: #020617;
                color: #E5E9F0;
                border: 1px solid #1F2933;
                border-radius: 4px;
            }
            QPushButton {
                background-color: #0EA5E9;
                color: #020617;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #38BDF8;
            }
            QPushButton:pressed {
                background-color: #0284C7;
            }
            QTableWidget {
                background-color: #020617;
                color: #E5E9F0;
                gridline-color: #1F2933;
                border: 1px solid #1F2933;
                border-radius: 4px;
            }
            QHeaderView::section {
                background-color: #020617;
                color: #9CA3AF;
                border: 0px;
                border-bottom: 1px solid #1F2933;
                padding: 4px;
            }
            QProgressBar {
                background-color: #020617;
                border: 1px solid #1F2933;
                border-radius: 4px;
                text-align: center;
                color: #E5E9F0;
                font-size: 11px;
            }
            QProgressBar::chunk {
                background-color: #0EA5E9;
                border-radius: 4px;
            }
            QLineEdit {
                background-color: #020617;
                border: 1px solid #1F2933;
                border-radius: 4px;
                color: #E5E9F0;
                padding: 4px 6px;
            }
            QComboBox {
                background-color: #020617;
                border: 1px solid #1F2933;
                border-radius: 4px;
                color: #E5E9F0;
                padding: 2px 6px;
            }
            QCheckBox {
                color: #E5E9F0;
            }
        """)

    # ---------- DASHBOARD PAGE ----------

    def _build_dashboard_page(self):
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        # Header
        header_row = QHBoxLayout()
        title = QLabel("TaskFlux — System Dashboard")
        title.setStyleSheet("font-size: 20px; font-weight: 800; color: #7DD3FC;")
        self.lbl_health = QLabel("System Health: --")
        self.lbl_health.setStyleSheet("font-size: 14px; color: #A5B4FC;")
        header_row.addWidget(title)
        header_row.addStretch(1)
        header_row.addWidget(self.lbl_health)
        outer.addLayout(header_row)

        # Top Issues card
        issues_group = QGroupBox("Top Issues Right Now")
        issues_layout = QVBoxLayout(issues_group)
        self.lbl_issues = QLabel("No major performance issues detected.")
        self.lbl_issues.setStyleSheet("font-size: 12px; color: #9CA3AF;")
        self.lbl_issues.setWordWrap(True)
        issues_layout.addWidget(self.lbl_issues)
        outer.addWidget(issues_group)

        # Top row: CPU / RAM / GPU
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        # CPU card
        cpu_group = QGroupBox("CPU & CORES")
        cpu_layout = QVBoxLayout(cpu_group)
        self.cpu_bar = make_progress_bar()
        self.lbl_cpu_text = QLabel("CPU: -- %")
        self.lbl_cpu_text.setStyleSheet("font-size: 12px; color: #9CA3AF;")
        cpu_layout.addWidget(self.cpu_bar)
        cpu_layout.addWidget(self.lbl_cpu_text)

        self.per_core_container = QVBoxLayout()
        cpu_layout.addLayout(self.per_core_container)
        self.per_core_labels = []

        # RAM card
        ram_group = QGroupBox("MEMORY & TEMPS")
        ram_layout = QVBoxLayout(ram_group)
        self.ram_bar = make_progress_bar()
        self.lbl_ram_text = QLabel("RAM: -- %")
        self.lbl_ram_text.setStyleSheet("font-size: 12px; color: #9CA3AF;")
        self.lbl_temps = QLabel("Temps: --")
        self.lbl_temps.setStyleSheet("font-size: 12px; color: #9CA3AF;")
        ram_layout.addWidget(self.ram_bar)
        ram_layout.addWidget(self.lbl_ram_text)
        ram_layout.addWidget(self.lbl_temps)

        # GPU card
        gpu_group = QGroupBox("GPU")
        gpu_layout = QVBoxLayout(gpu_group)
        self.gpu_bar = make_progress_bar()
        self.lbl_gpu_text = QLabel("GPU: --")
        self.lbl_gpu_text.setStyleSheet("font-size: 12px; color: #9CA3AF;")
        gpu_layout.addWidget(self.gpu_bar)
        gpu_layout.addWidget(self.lbl_gpu_text)

        top_row.addWidget(cpu_group)
        top_row.addWidget(ram_group)
        top_row.addWidget(gpu_group)
        outer.addLayout(top_row)

        # Bottom row: NET / DISK
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)

        net_group = QGroupBox("NETWORK")
        net_layout = QVBoxLayout(net_group)
        self.lbl_net = QLabel("NET: --")
        self.lbl_net.setStyleSheet("font-size: 12px; color: #9CA3AF;")
        self.lbl_net_graph = QLabel("")
        self.lbl_net_graph.setStyleSheet("font-family: Consolas, monospace; color: #22C55E;")
        net_layout.addWidget(self.lbl_net)
        net_layout.addWidget(self.lbl_net_graph)

        disk_group = QGroupBox("DISK")
        disk_layout = QVBoxLayout(disk_group)
        self.lbl_disk = QLabel("DISK: --")
        self.lbl_disk.setStyleSheet("font-size: 12px; color: #9CA3AF;")
        self.lbl_disk_graph = QLabel("")
        self.lbl_disk_graph.setStyleSheet("font-family: Consolas, monospace; color: #F97316;")
        disk_layout.addWidget(self.lbl_disk)
        disk_layout.addWidget(self.lbl_disk_graph)

        bottom_row.addWidget(net_group)
        bottom_row.addWidget(disk_group)
        outer.addLayout(bottom_row)

        outer.addStretch(1)
        return w

    # ---------- PROCESSES PAGE ----------

    def _build_process_page(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        header = QLabel("Processes")
        header.setStyleSheet("font-size: 18px; font-weight: 700; color: #7DD3FC;")
        header_row.addWidget(header)
        header_row.addStretch(1)
        layout.addLayout(header_row)

        # Filter bar
        filter_row = QHBoxLayout()
        self.proc_search = QLineEdit()
        self.proc_search.setPlaceholderText("Search by name...")
        self.proc_search.textChanged.connect(self._on_proc_filter_changed)

        self.proc_filter_combo = QComboBox()
        self.proc_filter_combo.addItems([
            "All", "User processes", "System processes",
            "High CPU", "High RAM", "Suspicious only", "Recently spawned"
        ])
        self.proc_filter_combo.currentIndexChanged.connect(self._on_proc_filter_changed)

        self.proc_sort_combo = QComboBox()
        self.proc_sort_combo.addItems(["CPU", "RAM", "Intel", "Name", "PID"])
        self.proc_sort_combo.currentIndexChanged.connect(self._on_proc_filter_changed)

        self.chk_proc_active_only = QCheckBox("Active only (CPU > 0.1%)")
        self.chk_proc_active_only.stateChanged.connect(self._on_proc_filter_changed)

        self.btn_proc_freeze = QPushButton("Freeze View")
        self.btn_proc_freeze.setCheckable(True)
        self.btn_proc_freeze.toggled.connect(self._on_proc_freeze_toggled)

        filter_row.addWidget(self.proc_search)
        filter_row.addWidget(self.proc_filter_combo)
        filter_row.addWidget(self.proc_sort_combo)
        filter_row.addWidget(self.chk_proc_active_only)
        filter_row.addWidget(self.btn_proc_freeze)

        layout.addLayout(filter_row)

        splitter = QSplitter()
        splitter.setOrientation(Qt.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setSpacing(8)

        self.tbl_procs = QTableWidget()
        self.tbl_procs.setColumnCount(5)
        self.tbl_procs.setHorizontalHeaderLabels(["PID", "Name", "CPU%", "RAM MB", "Intel"])
        self.tbl_procs.horizontalHeader().setStretchLastSection(True)
        self.tbl_procs.setSortingEnabled(True)
        self.tbl_procs.verticalHeader().setVisible(False)
        self.tbl_procs.itemSelectionChanged.connect(self._update_process_inspector)

        left_layout.addWidget(self.tbl_procs)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setSpacing(8)

        inspector_title = QLabel("Process Inspector")
        inspector_title.setStyleSheet("font-size: 16px; font-weight: 600; color: #7DD3FC;")
        right_layout.addWidget(inspector_title)

        self.inspector_text = QTextEdit()
        self.inspector_text.setReadOnly(True)
        self.inspector_text.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        right_layout.addWidget(self.inspector_text)

        btn_row = QHBoxLayout()
        self.btn_kill = QPushButton("Terminate")
        self.btn_kill.clicked.connect(self._kill_selected_process)
        self.btn_kill_tree = QPushButton("Kill Tree")
        self.btn_kill_tree.clicked.connect(self._kill_selected_tree)
        self.btn_open_loc = QPushButton("Open File Location")
        self.btn_open_loc.clicked.connect(self._open_selected_location)
        btn_row.addWidget(self.btn_kill)
        btn_row.addWidget(self.btn_kill_tree)
        btn_row.addWidget(self.btn_open_loc)
        right_layout.addLayout(btn_row)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([900, 400])

        layout.addWidget(splitter)
        return w

    # ---------- THREATS PAGE ----------

    def _build_threats_page(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(8)

        header = QLabel("Threats & Suspicious Activity")
        header.setStyleSheet("font-size: 18px; font-weight: 700; color: #F97316;")
        v.addWidget(header)

        desc = QLabel("Processes flagged as risky or dangerous based on location, behavior, and resource usage.")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        v.addWidget(desc)

        self.lbl_threat_summary = QLabel("No active threats detected.")
        self.lbl_threat_summary.setStyleSheet("color: #F97316; font-size: 12px;")
        v.addWidget(self.lbl_threat_summary)

        self.tbl_threats = QTableWidget()
        self.tbl_threats.setColumnCount(5)
        self.tbl_threats.setHorizontalHeaderLabels(["PID", "Name", "CPU%", "RAM MB", "Intel"])
        self.tbl_threats.horizontalHeader().setStretchLastSection(True)
        self.tbl_threats.setSortingEnabled(True)
        self.tbl_threats.verticalHeader().setVisible(False)

        v.addWidget(self.tbl_threats)
        return w

    # ---------- STARTUP / SERVICES / LOGS / EXPORT / SETTINGS ----------

    def _build_startup_page(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(8)

        header = QLabel("Startup Overview")
        header.setStyleSheet("font-size: 18px; font-weight: 700; color: #7DD3FC;")
        v.addWidget(header)

        self.tbl_startup = QTableWidget()
        self.tbl_startup.setColumnCount(3)
        self.tbl_startup.setHorizontalHeaderLabels(["Name", "Path", "Source"])
        self.tbl_startup.horizontalHeader().setStretchLastSection(True)
        self.tbl_startup.verticalHeader().setVisible(False)

        btn_row = QHBoxLayout()
        btn_refresh = QPushButton("Refresh Startup Entries")
        btn_refresh.clicked.connect(self._refresh_startup)
        btn_open = QPushButton("Open File Location")
        btn_open.clicked.connect(self._open_startup_location)
        btn_row.addWidget(btn_refresh)
        btn_row.addWidget(btn_open)
        btn_row.addStretch(1)

        v.addLayout(btn_row)
        v.addWidget(self.tbl_startup)
        return w

    def _build_services_page(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(8)

        header = QLabel("Services Overview")
        header.setStyleSheet("font-size: 18px; font-weight: 700; color: #7DD3FC;")
        v.addWidget(header)

        filter_row = QHBoxLayout()
        self.svc_search = QLineEdit()
        self.svc_search.setPlaceholderText("Search services...")
        self.svc_search.textChanged.connect(self._filter_services)

        self.svc_status_filter = QComboBox()
        self.svc_status_filter.addItems(["All", "running", "stopped"])
        self.svc_status_filter.currentIndexChanged.connect(self._filter_services)

        self.svc_start_filter = QComboBox()
        self.svc_start_filter.addItems(["All", "auto", "manual", "disabled"])
        self.svc_start_filter.currentIndexChanged.connect(self._filter_services)

        filter_row.addWidget(self.svc_search)
        filter_row.addWidget(self.svc_status_filter)
        filter_row.addWidget(self.svc_start_filter)
        v.addLayout(filter_row)

        self.tbl_services = QTableWidget()
        self.tbl_services.setColumnCount(4)
        self.tbl_services.setHorizontalHeaderLabels(["Name", "Display Name", "Status", "Start Type"])
        self.tbl_services.horizontalHeader().setStretchLastSection(True)
        self.tbl_services.verticalHeader().setVisible(False)

        btn_row = QHBoxLayout()
        self.btn_svc_refresh = QPushButton("Refresh Services")
        self.btn_svc_refresh.clicked.connect(self._refresh_services)
        btn_row.addWidget(self.btn_svc_refresh)
        btn_row.addStretch(1)

        v.addLayout(btn_row)
        v.addWidget(self.tbl_services)
        return w

    def _build_logs_page(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(8)

        header = QLabel("Live Events / Alert Log")
        header.setStyleSheet("font-size: 18px; font-weight: 700; color: #7DD3FC;")
        v.addWidget(header)

        filter_row = QHBoxLayout()
        self.log_filter_combo = QComboBox()
        self.log_filter_combo.addItems(["All", "Process", "Threat", "System", "Action"])
        self.log_filter_combo.currentIndexChanged.connect(self._on_log_filter_changed)

        self.chk_log_autoscroll = QCheckBox("Auto-scroll")
        self.chk_log_autoscroll.setChecked(True)

        filter_row.addWidget(self.log_filter_combo)
        filter_row.addWidget(self.chk_log_autoscroll)
        filter_row.addStretch(1)
        v.addLayout(filter_row)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")

        v.addWidget(self.log_view)
        return w

    def _build_export_page(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(8)

        header = QLabel("Export System Snapshot")
        header.setStyleSheet("font-size: 18px; font-weight: 700; color: #7DD3FC;")
        v.addWidget(header)

        desc = QLabel("Generate a full JSON snapshot of your current system state (CPU, RAM, GPU, processes, disk, net).")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #9CA3AF;")
        v.addWidget(desc)

        btn = QPushButton("Export Snapshot to JSON")
        btn.clicked.connect(self._export_snapshot)

        v.addWidget(btn)
        v.addStretch(1)
        return w

    def _build_settings_page(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(8)

        header = QLabel("Settings")
        header.setStyleSheet("font-size: 18px; font-weight: 700; color: #7DD3FC;")
        v.addWidget(header)

        desc = QLabel("TaskFlux preferences. These are saved to taskflux_settings.json.")
        desc.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        v.addWidget(desc)

        # Refresh rate
        row_refresh = QHBoxLayout()
        lbl_refresh = QLabel("Dashboard refresh rate:")
        self.cmb_refresh = QComboBox()
        self.cmb_refresh.addItems(["1000 ms", "1500 ms", "2000 ms", "3000 ms"])
        ms = self.settings.get("refresh_rate_ms", 1500)
        if ms <= 1000:
            self.cmb_refresh.setCurrentIndex(0)
        elif ms <= 1500:
            self.cmb_refresh.setCurrentIndex(1)
        elif ms <= 2000:
            self.cmb_refresh.setCurrentIndex(2)
        else:
            self.cmb_refresh.setCurrentIndex(3)
        row_refresh.addWidget(lbl_refresh)
        row_refresh.addWidget(self.cmb_refresh)
        row_refresh.addStretch(1)
        v.addLayout(row_refresh)

        # Process refresh
        row_proc_refresh = QHBoxLayout()
        lbl_proc_refresh = QLabel("Process list refresh:")
        self.cmb_proc_refresh = QComboBox()
        self.cmb_proc_refresh.addItems(["3000 ms", "5000 ms", "8000 ms", "10000 ms"])
        pms = self.settings.get("proc_refresh_ms", 5000)
        if pms <= 3000:
            self.cmb_proc_refresh.setCurrentIndex(0)
        elif pms <= 5000:
            self.cmb_proc_refresh.setCurrentIndex(1)
        elif pms <= 8000:
            self.cmb_proc_refresh.setCurrentIndex(2)
        else:
            self.cmb_proc_refresh.setCurrentIndex(3)
        row_proc_refresh.addWidget(lbl_proc_refresh)
        row_proc_refresh.addWidget(self.cmb_proc_refresh)
        row_proc_refresh.addStretch(1)
        v.addLayout(row_proc_refresh)

        # Toggles
        self.chk_show_splash = QCheckBox("Show splash screen on startup")
        self.chk_show_splash.setChecked(self.settings.get("show_splash", True))

        self.chk_show_system = QCheckBox("Show system processes by default")
        self.chk_show_system.setChecked(self.settings.get("show_system_processes", False))

        v.addWidget(self.chk_show_splash)
        v.addWidget(self.chk_show_system)

        # Auto sort
        row_sort = QHBoxLayout()
        lbl_sort = QLabel("Auto-sort processes by:")
        self.cmb_auto_sort = QComboBox()
        self.cmb_auto_sort.addItems(["CPU", "RAM", "Intel", "Name", "PID"])
        current_sort = self.settings.get("auto_sort_processes", "CPU")
        idx = self.cmb_auto_sort.findText(current_sort)
        if idx >= 0:
            self.cmb_auto_sort.setCurrentIndex(idx)
        row_sort.addWidget(lbl_sort)
        row_sort.addWidget(self.cmb_auto_sort)
        row_sort.addStretch(1)
        v.addLayout(row_sort)

        # Buttons
        btn_row = QHBoxLayout()
        btn_save = QPushButton("Save Settings")
        btn_save.clicked.connect(self._save_settings_clicked)
        btn_reset = QPushButton("Reset to Defaults")
        btn_reset.clicked.connect(self._reset_settings_clicked)
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_reset)
        btn_row.addStretch(1)
        v.addLayout(btn_row)

        v.addStretch(1)
        return w

    # ---------- TIMERS / PLUGINS ----------

    def _setup_timers(self):
        self.timer = QTimer(self)
        self.timer.setInterval(self.settings.get("refresh_rate_ms", 1500))
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        self.proc_timer = QTimer(self)
        self.proc_timer.setInterval(self.settings.get("proc_refresh_ms", 5000))
        self.proc_timer.timeout.connect(self._refresh_processes)
        self.proc_timer.start()

    def _load_plugins(self):
        self.plugins = load_plugins()
        for mod in self.plugins:
            if hasattr(mod, "register_panels"):
                try:
                    mod.register_panels(self)
                    self._log("System", f"[PLUGIN] Loaded: {mod.__name__}")
                except Exception as e:
                    self._log("System", f"[PLUGIN ERROR] {mod.__name__}: {e}")

    # ---------- NAV ----------

    def _change_page(self, idx):
        self.pages.setCurrentIndex(idx)

    # ---------- LIVE TICK ----------

    def _tick(self):
        now = time.time()
        dt = max(now - self.last_tick, 0.001)
        self.last_tick = now

        cpu = get_cpu_overview()
        ram = get_ram_overview()
        gpu = get_gpu_overview()
        temps = get_temps_overview()

        # CPU
        self.cpu_bar.setValue(int(cpu["total"]))
        self.lbl_cpu_text.setText(f"CPU: {cpu['total']}%")

        # RAM
        self.ram_bar.setValue(int(ram["percent"]))
        self.lbl_ram_text.setText(f"RAM: {ram['percent']}%  ({ram['used_gb']}/{ram['total_gb']} GB)")

        # GPU
        if gpu:
            self.gpu_bar.setValue(int(gpu["load_percent"]))
            self.lbl_gpu_text.setText(
                f"{gpu['name']}  {gpu['load_percent']}%  VRAM {gpu['vram_used_mb']}/{gpu['vram_total_mb']} MB  {gpu['temp_c']}°C"
            )
        else:
            self.gpu_bar.setValue(0)
            self.lbl_gpu_text.setText("GPU: Not detected or unsupported")

        # Temps
        if temps:
            short = ", ".join(f"{t['label']} {t['current']}°C" for t in temps[:4])
            self.lbl_temps.setText(f"Temps: {short}")
        else:
            self.lbl_temps.setText("Temps: Not available")

        self._update_per_core(cpu["per_core"])

        # Disk / Net
        dn = get_disk_net_overview(self.prev_disk, self.prev_net, dt)
        self.prev_disk = dn["disk_raw"]
        self.prev_net = dn["net_raw"]

        self.lbl_net.setText(
            f"Up {dn['net_up_mb_s']} MB/s   Down {dn['net_down_mb_s']} MB/s"
        )
        self.lbl_disk.setText(
            f"Read {dn['disk_read_mb_s']} MB/s   Write {dn['disk_write_mb_s']} MB/s"
        )

        self.net_history.append(dn["net_down_mb_s"])
        self.disk_history.append(dn["disk_read_mb_s"])

        self._update_graphs()
        self._update_system_health(cpu, ram, gpu)
        self._check_process_events()

    def _update_per_core(self, per_core):
        if len(self.per_core_labels) != len(per_core):
            while self.per_core_container.count():
                item = self.per_core_container.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()
            self.per_core_labels = []
            for i in range(len(per_core)):
                lbl = QLabel(f"Core {i}: -- %")
                lbl.setStyleSheet("font-family: Consolas, monospace; font-size: 11px; color: #9CA3AF;")
                self.per_core_container.addWidget(lbl)
                self.per_core_labels.append(lbl)

        for i, val in enumerate(per_core):
            self.per_core_labels[i].setText(f"Core {i}: {val:.0f}%")

    def _update_graphs(self):
        if self.net_history:
            max_val = max(self.net_history) or 1
            bars = "".join("|" if v > 0 else "." for v in self.net_history)
            self.lbl_net_graph.setText(f"{bars}  (max {max_val:.2f} MB/s)")

        if self.disk_history:
            max_val = max(self.disk_history) or 1
            bars = "".join("|" if v > 0 else "." for v in self.disk_history)
            self.lbl_disk_graph.setText(f"{bars}  (max {max_val:.2f} MB/s)")

    def _update_system_health(self, cpu, ram, gpu):
        score = 100
        issues = []

        if cpu["total"] > 90:
            score -= 30
            issues.append(f"High CPU usage: {cpu['total']}%")
        elif cpu["total"] > 75:
            score -= 15
            issues.append(f"Elevated CPU usage: {cpu['total']}%")

        if ram["percent"] > 90:
            score -= 30
            issues.append(f"High RAM usage: {ram['percent']}%")
        elif ram["percent"] > 75:
            score -= 15
            issues.append(f"Elevated RAM usage: {ram['percent']}%")

        if gpu and gpu["load_percent"] > 90:
            score -= 10
            issues.append(f"High GPU usage: {gpu['load_percent']}%")

        score = max(0, min(100, score))

        if score >= 80:
            status = "Healthy"
        elif score >= 60:
            status = "Normal"
        elif score >= 40:
            status = "Watch"
        elif score >= 20:
            status = "Risky"
        else:
            status = "Critical"

        self.lbl_health.setText(f"System Health: {score} / 100 — {status}")

        if issues:
            self.lbl_issues.setText(" • " + "\n • ".join(issues))
        else:
            self.lbl_issues.setText("No major performance issues detected.")

    # ---------- PROCESSES / THREATS ----------

    def _on_proc_filter_changed(self):
        self.current_proc_search = self.proc_search.text().strip().lower()
        self.current_proc_filter = self.proc_filter_combo.currentText()
        self._refresh_processes()

    def _on_proc_freeze_toggled(self, checked):
        self.proc_frozen = checked
        self.btn_proc_freeze.setText("Unfreeze" if checked else "Freeze View")

    def _refresh_processes(self):
        if self.proc_frozen:
            return

        procs = get_process_snapshot()
        filtered = []

        show_system = self.settings.get("show_system_processes", False)
        active_only = self.chk_proc_active_only.isChecked()
        mode = self.current_proc_filter

        now = time.time()

        for p in procs:
            name = (p["name"] or "").lower()
            pid = p["pid"]
            cpu = p["cpu"]
            mem = p["mem_mb"]
            intel_label = p["intel_label"]

            if self.current_proc_search and self.current_proc_search not in name:
                continue

            if not show_system:
                try:
                    proc_obj = psutil.Process(pid)
                    if proc_obj.username().lower().startswith("nt authority"):
                        if mode not in ("System processes",):
                            continue
                except Exception:
                    pass

            if active_only and cpu <= 0.1:
                continue

            if mode == "User processes":
                try:
                    proc_obj = psutil.Process(pid)
                    if proc_obj.username().lower().startswith("nt authority"):
                        continue
                except Exception:
                    pass
            elif mode == "System processes":
                try:
                    proc_obj = psutil.Process(pid)
                    if not proc_obj.username().lower().startswith("nt authority"):
                        continue
                except Exception:
                    continue
            elif mode == "High CPU":
                if cpu < 10:
                    continue
            elif mode == "High RAM":
                if mem < 200:
                    continue
            elif mode == "Suspicious only":
                if intel_label not in ("watch", "risky", "dangerous"):
                    continue
            elif mode == "Recently spawned":
                try:
                    proc_obj = psutil.Process(pid)
                    if now - proc_obj.create_time() > 60:
                        continue
                except Exception:
                    continue

            filtered.append(p)

        # Sorting
        sort_mode = self.proc_sort_combo.currentText()
        if sort_mode == "CPU":
            filtered.sort(key=lambda x: x["cpu"], reverse=True)
        elif sort_mode == "RAM":
            filtered.sort(key=lambda x: x["mem_mb"], reverse=True)
        elif sort_mode == "Intel":
            filtered.sort(key=lambda x: x["intel_score"], reverse=True)
        elif sort_mode == "Name":
            filtered.sort(key=lambda x: (x["name"] or "").lower())
        elif sort_mode == "PID":
            filtered.sort(key=lambda x: x["pid"])

        self.tbl_procs.setRowCount(len(filtered))
        threat_rows = []

        for row, p in enumerate(filtered):
            self.tbl_procs.setItem(row, 0, QTableWidgetItem(str(p["pid"])))
            self.tbl_procs.setItem(row, 1, QTableWidgetItem(p["name"] or ""))
            self.tbl_procs.setItem(row, 2, QTableWidgetItem(str(p["cpu"])))
            self.tbl_procs.setItem(row, 3, QTableWidgetItem(str(p["mem_mb"])))
            self.tbl_procs.setItem(row, 4, QTableWidgetItem(f"{p['intel_label']} ({p['intel_score']})"))

            label = p["intel_label"]
            if label == "healthy":
                color = QColor("#22C55E")
            elif label == "normal":
                color = QColor("#E5E9F0")
            elif label == "watch":
                color = QColor("#EAB308")
            elif label == "risky":
                color = QColor("#F97316")
            elif label == "dangerous":
                color = QColor("#EF4444")
            else:
                color = QColor("#9CA3AF")

            for col in range(5):
                item = self.tbl_procs.item(row, col)
                if item:
                    item.setForeground(color)

            if label in ("risky", "dangerous"):
                threat_rows.append(p)

        # Threats table
        self.tbl_threats.setRowCount(len(threat_rows))
        for row, p in enumerate(threat_rows):
            self.tbl_threats.setItem(row, 0, QTableWidgetItem(str(p["pid"])))
            self.tbl_threats.setItem(row, 1, QTableWidgetItem(p["name"] or ""))
            self.tbl_threats.setItem(row, 2, QTableWidgetItem(str(p["cpu"])))
            self.tbl_threats.setItem(row, 3, QTableWidgetItem(str(p["mem_mb"])))
            self.tbl_threats.setItem(row, 4, QTableWidgetItem(f"{p['intel_label']} ({p['intel_score']})"))

        if threat_rows:
            self.lbl_threat_summary.setText(
                f"{len(threat_rows)} process(es) flagged as risky or dangerous."
            )
        else:
            self.lbl_threat_summary.setText("No active threats detected.")

    def _get_selected_pid(self):
        items = self.tbl_procs.selectedItems()
        if not items:
            return None
        pid_item = items[0]
        try:
            return int(pid_item.text())
        except ValueError:
            return None

    def _update_process_inspector(self):
        pid = self._get_selected_pid()
        if pid is None:
            self.inspector_text.setPlainText("")
            return

        try:
            proc = psutil.Process(pid)
            info_lines = [
                f"Name: {proc.name()}",
                f"PID: {proc.pid}",
                f"Status: {proc.status()}",
                f"Exe: {proc.exe()}",
                f"Cmdline: {' '.join(proc.cmdline())}",
                f"CPU%: {proc.cpu_percent(interval=0.0)}",
                f"Memory: {proc.memory_info().rss / (1024*1024):.1f} MB",
                f"Threads: {proc.num_threads()}",
            ]
            parent = proc.parent()
            if parent:
                info_lines.append(f"Parent: {parent.name()} (PID {parent.pid})")

            self.inspector_text.setPlainText("\n".join(info_lines))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            self.inspector_text.setPlainText("Process no longer available or access denied.")

    def _kill_selected_process(self):
        pid = self._get_selected_pid()
        if pid is None:
            return
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            self._log("Action", f"[KILL] Terminated {proc.name()} (PID {pid})")
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            self._log("Action", f"[KILL ERROR] PID {pid}: {e}")

    def _kill_selected_tree(self):
        pid = self._get_selected_pid()
        if pid is None:
            return
        try:
            proc = psutil.Process(pid)
            children = proc.children(recursive=True)
            for c in children:
                try:
                    c.terminate()
                except Exception:
                    pass
            proc.terminate()
            self._log("Action", f"[KILL TREE] Terminated {proc.name()} (PID {pid}) and {len(children)} children")
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            self._log("Action", f"[KILL TREE ERROR] PID {pid}: {e}")

    def _open_selected_location(self):
        pid = self._get_selected_pid()
        if pid is None:
            return
        try:
            proc = psutil.Process(pid)
            exe = proc.exe()
            if exe and os.path.isfile(exe):
                folder = os.path.dirname(exe)
                subprocess.Popen(f'explorer "{folder}"')
                self._log("Action", f"[OPEN] Opened file location for {proc.name()} (PID {pid})")
        except Exception as e:
            self._log("Action", f"[OPEN ERROR] PID {pid}: {e}")

    # ---------- STARTUP / SERVICES ----------

    def _refresh_startup(self):
        entries = list_startup_entries()
        self.tbl_startup.setRowCount(len(entries))
        for row, e in enumerate(entries):
            self.tbl_startup.setItem(row, 0, QTableWidgetItem(e["name"]))
            self.tbl_startup.setItem(row, 1, QTableWidgetItem(e["path"]))
            self.tbl_startup.setItem(row, 2, QTableWidgetItem(e["source"]))

    def _open_startup_location(self):
        items = self.tbl_startup.selectedItems()
        if not items:
            return
        path_item = self.tbl_startup.item(items[0].row(), 1)
        if not path_item:
            return
        path = path_item.text()
        if os.path.isfile(path):
            folder = os.path.dirname(path)
        else:
            folder = path
        try:
            subprocess.Popen(f'explorer "{folder}"')
            self._log("Action", f"[OPEN STARTUP] {path}")
        except Exception as e:
            self._log("Action", f"[OPEN STARTUP ERROR] {e}")

    def _refresh_services(self):
        services = list_services_summary()
        self._services_cache = services
        self._apply_service_filter()

    def _filter_services(self):
        self._apply_service_filter()

    def _apply_service_filter(self):
        services = getattr(self, "_services_cache", [])
        text = self.svc_search.text().strip().lower()
        status_filter = self.svc_status_filter.currentText()
        start_filter = self.svc_start_filter.currentText()

        filtered = []
        for s in services:
            name = (s["name"] or "").lower()
            disp = (s["display_name"] or "").lower()
            status = (s["status"] or "").lower()
            start_type = (s["start_type"] or "").lower()

            if text and text not in name and text not in disp:
                continue
            if status_filter != "All" and status != status_filter:
                continue
            if start_filter != "All" and start_type != start_filter:
                continue
            filtered.append(s)

        self.tbl_services.setRowCount(len(filtered))
        for row, s in enumerate(filtered):
            self.tbl_services.setItem(row, 0, QTableWidgetItem(s["name"] or ""))
            self.tbl_services.setItem(row, 1, QTableWidgetItem(s["display_name"] or ""))
            self.tbl_services.setItem(row, 2, QTableWidgetItem(s["status"] or ""))
            self.tbl_services.setItem(row, 3, QTableWidgetItem(s["start_type"] or ""))

    # ---------- LOGS / EVENTS ----------

    def _on_log_filter_changed(self):
        self.current_log_filter = self.log_filter_combo.currentText()

    def _log(self, category, text):
        # category: "Process", "Threat", "System", "Action"
        if self.current_log_filter != "All" and self.current_log_filter != category:
            return
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] [{category}] {text}"
        self.log_view.append(line)
        if self.chk_log_autoscroll.isChecked():
            self.log_view.moveCursor(QTextCursor.End)

    def _check_process_events(self):
        current_pids = set()
        for p in psutil.process_iter(["pid", "name"]):
            try:
                current_pids.add(p.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # ignore kernel pseudo-processes
        filtered_current = {pid for pid in current_pids if pid not in (0, 4)}
        filtered_known = {pid for pid in self.known_pids if pid not in (0, 4)}

        new_pids = filtered_current - filtered_known
        dead_pids = filtered_known - filtered_current

        if new_pids:
            for pid in new_pids:
                try:
                    proc = psutil.Process(pid)
                    self._log("Process", f"[PROC-SPAWN] {proc.name()} (PID {pid})")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

        if dead_pids:
            for pid in dead_pids:
                self._log("Process", f"[PROC-KILL] PID {pid}")

        self.known_pids = filtered_current

    # ---------- EXPORT ----------

    def _export_snapshot(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Snapshot",
            "taskflux_snapshot.json",
            "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            export_snapshot_to_json(path)
            self._log("Action", f"[EXPORT] Snapshot saved to {path}")
        except Exception as e:
            self._log("System", f"[EXPORT ERROR] {e}")

    # ---------- SETTINGS ----------

    def _save_settings_clicked(self):
        # refresh rate
        idx = self.cmb_refresh.currentIndex()
        if idx == 0:
            self.settings["refresh_rate_ms"] = 1000
        elif idx == 1:
            self.settings["refresh_rate_ms"] = 1500
        elif idx == 2:
            self.settings["refresh_rate_ms"] = 2000
        else:
            self.settings["refresh_rate_ms"] = 3000

        # proc refresh
        idx = self.cmb_proc_refresh.currentIndex()
        if idx == 0:
            self.settings["proc_refresh_ms"] = 3000
        elif idx == 1:
            self.settings["proc_refresh_ms"] = 5000
        elif idx == 2:
            self.settings["proc_refresh_ms"] = 8000
        else:
            self.settings["proc_refresh_ms"] = 10000

        self.settings["show_splash"] = self.chk_show_splash.isChecked()
        self.settings["show_system_processes"] = self.chk_show_system.isChecked()
        self.settings["auto_sort_processes"] = self.cmb_auto_sort.currentText()

        save_settings(self.settings)

        # apply timers live
        self.timer.setInterval(self.settings["refresh_rate_ms"])
        self.proc_timer.setInterval(self.settings["proc_refresh_ms"])

        self._log("System", "[SETTINGS] Saved and applied.")

    def _reset_settings_clicked(self):
        default = {
            "refresh_rate_ms": 1500,
            "proc_refresh_ms": 5000,
            "show_splash": True,
            "show_system_processes": False,
            "auto_sort_processes": "CPU",
            "theme": "neon",
        }
        self.settings.update(default)
        save_settings(self.settings)
        self._log("System", "[SETTINGS] Reset to defaults. Restart TaskFlux to fully apply.")


def main():
    settings = load_settings()

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("taskflux_logo.png"))

    splash = None
    if settings.get("show_splash", True):
        splash = SplashScreen(settings)
        splash.show()
        app.processEvents()

        splash.set_status("Initializing diagnostic engine...")
        time.sleep(0.35)
        splash.set_status("Scanning system topology...")
        time.sleep(0.35)
        splash.set_status("Loading process intelligence...")
        time.sleep(0.35)
        splash.set_status("Starting TaskFlux UI...")
        time.sleep(0.3)

    win = TaskFluxWindow(settings)
    win.show()
    if splash:
        splash.close()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
