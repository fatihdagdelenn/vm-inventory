"""
Zombie VM scoring engine - multi-metric correlation (false-positive reduction).
CPU alone is misleading (an idle-CPU VM may be doing disk/network work);
CPU, RAM variance, disk I/O and network are correlated over a 14-30 day window.
"""

# Weights (sum 1.0). CPU is the strongest signal; correlation kills false positives.
W_CPU, W_RAM, W_DISK, W_NET = 0.40, 0.20, 0.20, 0.20

# Thresholds
CPU_AVG_IDLE = 3.0      # % - below this is fully idle
CPU_AVG_TAPER = 8.0     # % - CPU sub-score reaches 0 at this value
CPU_PEAK_OK = 10.0      # % - a peak above this signals "in use"
CPU_PEAK_TAPER = 30.0   # % - a peak here zeroes the CPU sub-score entirely
RAM_FLAT = 0.05         # (max-min)/avg <= 5% -> flat line
RAM_TAPER = 0.20        # %20 dalgalanmada RAM alt-skoru 0
DISK_IDLE_KBPS = 20.0   # KB/s - roughly 1 IOPS; above = activity
NET_HEARTBEAT_KBPS = 10.0  # KB/s - keep-alive only; above = meaningful traffic


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _cpu_sub(cpu_avg, cpu_max):
    if cpu_avg is None:
        return None
    # high when the average is low; full score below CPU_AVG_IDLE
    avg_sub = _clamp((CPU_AVG_TAPER - cpu_avg) / (CPU_AVG_TAPER - CPU_AVG_IDLE))
    if cpu_avg <= CPU_AVG_IDLE:
        avg_sub = 1.0
    # peak gate: shrink the score as the peak exceeds 10%
    if cpu_max is None:
        peak_gate = 1.0
    elif cpu_max <= CPU_PEAK_OK:
        peak_gate = 1.0
    else:
        peak_gate = _clamp((CPU_PEAK_TAPER - cpu_max) / (CPU_PEAK_TAPER - CPU_PEAK_OK))
    return avg_sub * peak_gate


def _ram_sub(ram_avg, ram_min, ram_max):
    if not ram_avg or ram_min is None or ram_max is None:
        return None
    flat = (ram_max - ram_min) / max(ram_avg, 1)
    if flat <= RAM_FLAT:
        return 1.0
    return _clamp((RAM_TAPER - flat) / (RAM_TAPER - RAM_FLAT))


def _disk_sub(diskio_kbps):
    if diskio_kbps is None:
        return None
    return _clamp((DISK_IDLE_KBPS - diskio_kbps) / DISK_IDLE_KBPS)


def _net_sub(net_kbps):
    if net_kbps is None:
        return None
    return _clamp((NET_HEARTBEAT_KBPS - net_kbps) / NET_HEARTBEAT_KBPS)


def score_vm(*, cpu_avg=None, cpu_max=None, ram_avg_mb=None, ram_min_mb=None,
             ram_max_mb=None, net_kbps=None, diskio_kbps=None, days=0):
    """Zombie analysis for one VM.
        Returns: score, klass, confidence, reasons, subs (sub-scores), has_io."""
    subs = {
        "cpu": (_cpu_sub(cpu_avg, cpu_max), W_CPU),
        "ram": (_ram_sub(ram_avg_mb, ram_min_mb, ram_max_mb), W_RAM),
        "disk": (_disk_sub(diskio_kbps), W_DISK),
        "net": (_net_sub(net_kbps), W_NET),
    }
    has_io = subs["disk"][0] is not None or subs["net"][0] is not None
    num = sum(s * w for s, w in subs.values() if s is not None)
    den = sum(w for s, w in subs.values() if s is not None)
    score = round(100 * num / den) if den > 0 else 0

    # Confidence: days of data + presence of IO metrics
    if days < 3 or den == 0:
        confidence = "düşük"
    elif days >= 7 and has_io:
        confidence = "yüksek"
    else:
        confidence = "orta"

    if score >= 80 and confidence == "yüksek":
        klass, klass_code = "Kesin Zombi", "zombie"
    elif score >= 55:
        klass, klass_code = "Şüpheli (Sahibine Sor)", "suspect"
    else:
        klass, klass_code = "Aktif", "active"
    conf_code = {"düşük": "low", "orta": "medium", "yüksek": "high"}[confidence]

    reasons, reasons_s = [], []
    cs, rs, ds, ns = (subs["cpu"][0], subs["ram"][0], subs["disk"][0], subs["net"][0])
    if cs is not None:
        reasons.append(f"CPU ort %{round(cpu_avg or 0, 1)}, tepe %{round(cpu_max or 0, 1)}"
                       + (" (idle)" if cs > 0.7 else ""))
        reasons_s.append({"m": "cpu", "avg": round(cpu_avg or 0, 1),
                          "max": round(cpu_max or 0, 1), "idle": cs > 0.7})
    if rs is not None:
        flat = (ram_max_mb - ram_min_mb) / max(ram_avg_mb or 1, 1)
        reasons.append(f"RAM dalgalanma %{round(flat * 100, 1)}"
                       + (" (düz)" if rs > 0.7 else ""))
        reasons_s.append({"m": "ram", "flat": round(flat * 100, 1), "ok": rs > 0.7})
    if ds is not None:
        reasons.append(f"Disk I/O ~{round(diskio_kbps or 0, 1)} KB/s"
                       + (" (boşta)" if ds > 0.7 else ""))
        reasons_s.append({"m": "disk", "kbps": round(diskio_kbps or 0, 1), "ok": ds > 0.7})
    else:
        reasons.append("Disk verisi henüz yok")
        reasons_s.append({"m": "disk", "none": True})
    if ns is not None:
        reasons.append(f"Ağ ~{round(net_kbps or 0, 1)} KB/s"
                       + (" (heartbeat)" if ns > 0.7 else ""))
        reasons_s.append({"m": "net", "kbps": round(net_kbps or 0, 1), "ok": ns > 0.7})
    else:
        reasons.append("Ağ verisi henüz yok")
        reasons_s.append({"m": "net", "none": True})

    return {"score": score, "klass": klass, "klass_code": klass_code,
            "confidence": confidence, "confidence_code": conf_code,
            "reasons": reasons, "reasons_s": reasons_s, "has_io": has_io, "days": days,
            "subs": {k: (round(v[0], 2) if v[0] is not None else None)
                     for k, v in subs.items()}}
