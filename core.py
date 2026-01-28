import os
import time
import json
import psutil
import GPUtil

# ---------------------------------------------------------
# CPU OVERVIEW
# ---------------------------------------------------------
def get_cpu_overview():
    cpu_total = psutil.cpu_percent(interval=None)
    per_core = psutil.cpu_percent(interval=None, percpu=True)
    return {
        "total": cpu_total,
        "per_core": per_core,
        "count": len(per_core),
    }

# ---------------------------------------------------------
# RAM OVERVIEW
# ---------------------------------------------------------
def get_ram_overview():
    mem = psutil.virtual_memory()
    return {
        "percent": mem.percent,
        "total_gb": round(mem.total / (1024**3), 1),
        "used_gb": round(mem.used / (1024**3), 1),
    }

# ---------------------------------------------------------
# GPU OVERVIEW
# ---------------------------------------------------------
def get_gpu_overview():
    try:
        gpus = GPUtil.getGPUs()
        if not gpus:
            return None
        gpu = gpus[0]
        return {
            "name": gpu.name,
            "load_percent": round(gpu.load * 100, 1),
            "vram_used_mb": int(gpu.memoryUsed),
            "vram_total_mb": int(gpu.memoryTotal),
            "temp_c": int(gpu.temperature),
        }
    except Exception:
        return None

# ---------------------------------------------------------
# DISK + NETWORK OVERVIEW
# ---------------------------------------------------------
def get_disk_net_overview(prev_disk=None, prev_net=None, dt=1.0):
    disk = psutil.disk_io_counters()
    net = psutil.net_io_counters()

    if prev_disk is None or prev_net is None or dt <= 0:
        return {
            "disk_read_mb_s": 0.0,
            "disk_write_mb_s": 0.0,
            "net_up_mb_s": 0.0,
            "net_down_mb_s": 0.0,
            "disk_raw": disk,
            "net_raw": net,
        }

    dr = (disk.read_bytes - prev_disk.read_bytes) / (1024 * 1024 * dt)
    dw = (disk.write_bytes - prev_disk.write_bytes) / (1024 * 1024 * dt)
    up = (net.bytes_sent - prev_net.bytes_sent) / (1024 * 1024 * dt)
    dn = (net.bytes_recv - prev_net.bytes_recv) / (1024 * 1024 * dt)

    return {
        "disk_read_mb_s": round(max(dr, 0.0), 2),
        "disk_write_mb_s": round(max(dw, 0.0), 2),
        "net_up_mb_s": round(max(up, 0.0), 2),
        "net_down_mb_s": round(max(dn, 0.0), 2),
        "disk_raw": disk,
        "net_raw": net,
    }

# ---------------------------------------------------------
# TEMPERATURES
# ---------------------------------------------------------
def get_temps_overview():
    if not hasattr(psutil, "sensors_temperatures"):
        return None
    try:
        temps = psutil.sensors_temperatures()
        flat = []
        for name, entries in temps.items():
            for e in entries:
                flat.append({
                    "label": e.label or name,
                    "current": e.current,
                })
        return flat
    except Exception:
        return None

# ---------------------------------------------------------
# PROCESS INTELLIGENCE
# ---------------------------------------------------------
def classify_process_suspicion(proc: psutil.Process):
    try:
        name = (proc.info.get("name") or proc.name() or "").lower()
        exe = proc.info.get("exe") or proc.exe()
        cmdline = " ".join(proc.cmdline()) if proc.cmdline() else ""
        cpu = proc.info.get("cpu_percent", 0)
        mem = proc.info.get("memory_info").rss if proc.info.get("memory_info") else proc.memory_info().rss
        parent = proc.parent()
        parent_name = parent.name().lower() if parent else ""
        path = (exe or "").lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return {"score": 0, "tier": "unknown", "reasons": ["Process not fully readable"]}

    score = 0
    reasons = []

    if "downloads" in path or "\\temp" in path or "/temp" in path:
        score += 25
        reasons.append("Running from Downloads or Temp")

    if "appdata\\local\\temp" in path:
        score += 30
        reasons.append("Running from AppData\\Local\\Temp")

    if name in ("svchost.exe", "lsass.exe", "explorer.exe", "system", "csrss.exe"):
        reasons.append("Name matches core Windows component")
        if "windows" not in path:
            score += 40
            reasons.append("Core Windows name but not in Windows folder")

    if cpu > 50:
        score += 15
        reasons.append("High CPU usage")

    if mem > 500 * 1024 * 1024:
        score += 10
        reasons.append("High memory usage")

    cl = cmdline.lower()
    if "--type=renderer" in cl:
        reasons.append("Chrome renderer process")
    if "--type=gpu-process" in cl:
        reasons.append("Chrome GPU process")

    if score >= 60:
        tier = "high"
    elif score >= 30:
        tier = "medium"
    elif score > 0:
        tier = "low"
    else:
        tier = "normal"

    return {"score": score, "tier": tier, "reasons": reasons}

def process_intelligence_score(proc: psutil.Process):
    try:
        cpu = proc.info.get("cpu_percent", 0)
        mem = proc.info.get("memory_info").rss if proc.info.get("memory_info") else proc.memory_info().rss
        mem_mb = int(mem / (1024 * 1024))
        suspicion = classify_process_suspicion(proc)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return {"score": 0, "label": "unknown", "reasons": ["Process not readable"]}

    score = 100
    reasons = []

    if cpu > 70:
        score -= 15
        reasons.append("High CPU usage")

    if mem_mb > 1000:
        score -= 10
        reasons.append("High RAM usage")

    if suspicion["tier"] == "low":
        score -= 10
        reasons.append("Minor suspicious traits")
    elif suspicion["tier"] == "medium":
        score -= 25
        reasons.append("Moderate suspicious traits")
    elif suspicion["tier"] == "high":
        score -= 45
        reasons.append("Strong suspicious traits")

    score = max(0, min(100, score))

    if score >= 80:
        label = "healthy"
    elif score >= 60:
        label = "normal"
    elif score >= 40:
        label = "watch"
    elif score >= 20:
        label = "risky"
    else:
        label = "dangerous"

    return {"score": score, "label": label, "reasons": reasons}

# ---------------------------------------------------------
# PROCESS SNAPSHOT
# ---------------------------------------------------------
def get_process_snapshot():
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info", "exe"]):
        try:
            intel = process_intelligence_score(p)
            mem = p.info.get("memory_info")
            mem_mb = int(mem.rss / (1024 * 1024)) if mem else 0
            procs.append({
                "pid": p.info.get("pid"),
                "name": p.info.get("name"),
                "cpu": p.info.get("cpu_percent", 0),
                "mem_mb": mem_mb,
                "intel_score": intel["score"],
                "intel_label": intel["label"],
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return procs

# ---------------------------------------------------------
# SYSTEM SNAPSHOT EXPORT
# ---------------------------------------------------------
def collect_system_snapshot():
    cpu = get_cpu_overview()
    ram = get_ram_overview()
    gpu = get_gpu_overview()
    temps = get_temps_overview()
    procs = get_process_snapshot()
    disk = psutil.disk_io_counters()
    net = psutil.net_io_counters()

    return {
        "cpu": cpu,
        "ram": ram,
        "gpu": gpu,
        "temps": temps,
        "processes": procs,
        "disk": {
            "read_bytes": disk.read_bytes,
            "write_bytes": disk.write_bytes,
        },
        "net": {
            "bytes_sent": net.bytes_sent,
            "bytes_recv": net.bytes_recv,
        },
        "timestamp": time.time(),
    }

def export_snapshot_to_json(path):
    snap = collect_system_snapshot()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=2)
    return path

# ---------------------------------------------------------
# STARTUP ENTRIES
# ---------------------------------------------------------
def list_startup_entries():
    entries = []
    user_startup = os.path.join(os.path.expanduser("~"), "AppData", "Roaming",
                                "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
    if os.path.isdir(user_startup):
        for name in os.listdir(user_startup):
            entries.append({"source": "User", "name": name, "path": os.path.join(user_startup, name)})

    common_startup = os.path.join(os.environ.get("PROGRAMDATA", "C:\\ProgramData"),
                                  "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
    if os.path.isdir(common_startup):
        for name in os.listdir(common_startup):
            entries.append({"source": "All Users", "name": name, "path": os.path.join(common_startup, name)})

    return entries

# ---------------------------------------------------------
# SERVICES
# ---------------------------------------------------------
def list_services_summary():
    services = []
    try:
        for s in psutil.win_service_iter():
            try:
                info = s.as_dict()
                services.append({
                    "name": info.get("name"),
                    "display_name": info.get("display_name"),
                    "status": info.get("status"),
                    "start_type": info.get("start_type"),
                })
            except Exception:
                continue
    except Exception:
        return []
    return services

# ---------------------------------------------------------
# PLUGIN LOADER
# ---------------------------------------------------------
def load_plugins(plugin_dir="plugins"):
    plugins = []
    if not os.path.isdir(plugin_dir):
        return plugins

    for fname in os.listdir(plugin_dir):
        if not fname.endswith(".py"):
            continue
        path = os.path.join(plugin_dir, fname)
        mod_name = f"plugin_{os.path.splitext(fname)[0]}"
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(mod_name, path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            plugins.append(mod)
        except Exception:
            continue
    return plugins
