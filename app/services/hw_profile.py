"""Detector de hardware multi-OS (ANAM-030).

Saida JSON com ``hw_fingerprint`` estavel (so campos que identificam a maquina,
nunca valores "livres" que flutuam). Usa psutil/pynvml se existirem; senao
``nvidia-smi``/ctypes/stdlib. VRAM vem de NVML/nvidia-smi, NUNCA de AdapterRAM
(campo de 32 bits que satura em 4 GB). Throughput de disco so em funcao opt-in.
Sem segredos: nada de hostname, usuario ou variaveis de ambiente.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import random
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Callable, Optional

GIB = 1024 ** 3
Runner = Callable[[list], Optional[str]]


def _run(cmd: list, timeout: float = 8.0) -> Optional[str]:
    """Executa um comando e devolve stdout (ou None em qualquer falha)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _gib(n: Optional[float]) -> Optional[float]:
    return None if n is None else round(n / GIB, 2)


# ---------------------------------------------------------------- RAM
def _ram_windows() -> Optional[dict]:
    import ctypes

    class MEMSTATUS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    st = MEMSTATUS()
    st.dwLength = ctypes.sizeof(MEMSTATUS)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):  # type: ignore[attr-defined]
        return None
    return {"total": st.ullTotalPhys, "free_phys": st.ullAvailPhys, "free_commit": st.ullAvailPageFile}


def _ram_linux() -> Optional[dict]:
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            kv = {ln.split(":")[0]: int(ln.split(":")[1].split()[0]) * 1024 for ln in f if ":" in ln}
    except (OSError, ValueError):
        return None
    out = {"total": kv.get("MemTotal"), "free_phys": kv.get("MemAvailable", kv.get("MemFree"))}
    if "CommitLimit" in kv and "Committed_AS" in kv:
        out["free_commit"] = max(0, kv["CommitLimit"] - kv["Committed_AS"])
    return out


def _ram_macos(run: Runner) -> Optional[dict]:
    total = run(["sysctl", "-n", "hw.memsize"])
    if not total or not total.strip().isdigit():
        return None
    free = None
    vm = run(["vm_stat"]) or ""
    page = 4096
    pages = {}
    for ln in vm.splitlines():
        if "page size of" in ln:
            digits = [t for t in ln.replace("(", " ").split() if t.isdigit()]
            page = int(digits[0]) if digits else page
        elif ":" in ln:
            k, v = ln.split(":", 1)
            v = v.strip().rstrip(".")
            if v.isdigit():
                pages[k.strip()] = int(v)
    if pages:
        free = (pages.get("Pages free", 0) + pages.get("Pages inactive", 0)
                + pages.get("Pages speculative", 0)) * page
    return {"total": int(total.strip()), "free_phys": free}


def detect_ram(run: Runner = _run) -> dict:
    """RAM total/livre. Windows: livre = min(fisica livre, commit livre)."""
    raw: Optional[dict] = None
    try:
        import psutil  # type: ignore
        vm = psutil.virtual_memory()
        raw = {"total": vm.total, "free_phys": vm.available}
        if sys.platform == "win32":
            w = _ram_windows()
            raw["free_commit"] = (w or {}).get("free_commit")
    except Exception:
        raw = None
    if raw is None:
        if sys.platform == "win32":
            raw = _ram_windows()
        elif sys.platform == "darwin":
            raw = _ram_macos(run)
        else:
            raw = _ram_linux()
    raw = raw or {}
    candidates = [v for v in (raw.get("free_phys"), raw.get("free_commit")) if v is not None]
    return {"total_gb": _gib(raw.get("total")),
            "free_gb": _gib(min(candidates)) if candidates else None,
            "free_phys_gb": _gib(raw.get("free_phys")),
            "free_commit_gb": _gib(raw.get("free_commit"))}


# ---------------------------------------------------------------- CPU
def _cpu_name(run: Runner) -> str:
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                return str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
        except Exception:
            pass
    elif sys.platform == "darwin":
        out = run(["sysctl", "-n", "machdep.cpu.brand_string"])
        if out and out.strip():
            return out.strip()
    else:
        try:
            with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
                for ln in f:
                    if ln.lower().startswith("model name"):
                        return ln.split(":", 1)[1].strip()
        except OSError:
            pass
    return platform.processor() or platform.machine() or "unknown"


def _physical_cores(run: Runner) -> Optional[int]:
    try:
        import psutil  # type: ignore
        n = psutil.cpu_count(logical=False)
        if n:
            return int(n)
    except Exception:
        pass
    if sys.platform == "win32":
        out = run(["powershell", "-NoProfile", "-Command",
                   "(Get-CimInstance Win32_Processor | Measure-Object NumberOfCores -Sum).Sum"])
    elif sys.platform == "darwin":
        out = run(["sysctl", "-n", "hw.physicalcpu"])
    else:
        out = run(["sh", "-c", "lscpu -p=CORE,SOCKET 2>/dev/null | grep -v '^#' | sort -u | wc -l"])
    return int(out.strip()) if out and out.strip().isdigit() and int(out.strip()) > 0 else None


def detect_cpu(run: Runner = _run) -> dict:
    return {"name": _cpu_name(run), "cores": _physical_cores(run),
            "threads": os.cpu_count(), "arch": platform.machine()}


# ---------------------------------------------------------------- GPU
_SMI_FIELDS = "name,memory.total,memory.free,driver_version,compute_cap"


def _to_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def parse_nvidia_smi(text: str) -> list:
    """Parseia ``--query-gpu=<_SMI_FIELDS> --format=csv,noheader,nounits`` (MiB)."""
    gpus = []
    for ln in (text or "").splitlines():
        p = [x.strip() for x in ln.split(",")]
        if len(p) < 5 or not p[0]:
            continue
        tot, free = _to_float(p[1]), _to_float(p[2])
        cc = p[4]
        gpus.append({"vendor": "nvidia", "name": p[0],
                     "vram_total_gb": None if tot is None else round(tot / 1024, 2),
                     "vram_free_gb": None if free is None else round(free / 1024, 2),
                     "driver": p[3], "compute_cap": cc if _to_float(cc) is not None else None,
                     "sm": ("sm_" + cc.replace(".", "")) if _to_float(cc) is not None else None,
                     "source": "nvidia-smi"})
    return gpus


def _gpus_nvml() -> list:
    try:
        import pynvml  # type: ignore
        pynvml.nvmlInit()
    except Exception:
        return []
    gpus = []
    try:
        drv = pynvml.nvmlSystemGetDriverVersion()
        drv = drv.decode() if isinstance(drv, bytes) else str(drv)
        for i in range(pynvml.nvmlDeviceGetCount()):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(h)
            name = name.decode() if isinstance(name, bytes) else str(name)
            mem = pynvml.nvmlDeviceGetMemoryInfo(h)
            maj, mnr = pynvml.nvmlDeviceGetCudaComputeCapability(h)
            gpus.append({"vendor": "nvidia", "name": name, "vram_total_gb": _gib(mem.total),
                         "vram_free_gb": _gib(mem.free), "driver": drv,
                         "compute_cap": f"{maj}.{mnr}", "sm": f"sm_{maj}{mnr}", "source": "nvml"})
    except Exception:
        return []
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass
    return gpus


def detect_gpus(run: Runner = _run) -> list:
    """GPUs NVIDIA via NVML, senao nvidia-smi. Sem GPU/driver -> lista vazia."""
    gpus = _gpus_nvml()
    if gpus:
        return gpus
    out = run(["nvidia-smi", f"--query-gpu={_SMI_FIELDS}", "--format=csv,noheader,nounits"])
    return parse_nvidia_smi(out) if out else []


# ---------------------------------------------------------------- disco
def detect_disk(path: str = ".") -> dict:
    try:
        u = shutil.disk_usage(os.path.abspath(path))
    except OSError:
        return {"path": path, "total_gb": None, "free_gb": None}
    anchor = os.path.splitdrive(os.path.abspath(path))[0] or os.path.abspath(path)
    return {"path": anchor, "total_gb": _gib(u.total), "free_gb": _gib(u.free)}


def measure_disk_throughput(directory: str, size_mb: int = 64, rand_reads: int = 512) -> dict:
    """OPT-IN. Le um arquivo temporario: sequencial 128 KB e aleatorio 4 KB.

    Aviso: o cache do SO infla a leitura de arquivos recem-escritos; trate como
    teto otimista, nao como medida de disco frio.
    """
    size = max(1, int(size_mb)) * 1024 * 1024
    fd, tmp = tempfile.mkstemp(prefix="hwprobe_", dir=directory)
    try:
        with os.fdopen(fd, "wb") as f:
            blk = os.urandom(1024 * 1024)
            for _ in range(size // len(blk)):
                f.write(blk)
            f.flush()
            os.fsync(f.fileno())
        with open(tmp, "rb", buffering=0) as f:
            t0, n = time.perf_counter(), 0
            while True:
                b = f.read(128 * 1024)
                if not b:
                    break
                n += len(b)
            seq_s = max(time.perf_counter() - t0, 1e-9)
            rng = random.Random(0)
            t0 = time.perf_counter()
            for _ in range(rand_reads):
                f.seek(rng.randrange(0, size - 4096) // 4096 * 4096)
                f.read(4096)
            rnd_s = max(time.perf_counter() - t0, 1e-9)
        return {"seq_128k_mb_s": round(n / 1048576 / seq_s, 1),
                "rand_4k_iops": round(rand_reads / rnd_s), "size_mb": size_mb,
                "caveat": "cache do SO pode inflar; teto otimista"}
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------- perfil
def compute_fingerprint(profile: dict) -> str:
    """Hash estavel: so campos de identidade (sem valores livres/driver/tempo)."""
    ram = (profile.get("ram") or {}).get("total_gb")
    cpu = profile.get("cpu") or {}
    ident = {"os": profile.get("os", {}).get("system"),
             "cpu": [cpu.get("name"), cpu.get("cores"), cpu.get("threads")],
             "ram_gib": None if ram is None else round(ram),
             "gpus": sorted([g.get("name"), round(g.get("vram_total_gb") or 0), g.get("compute_cap")]
                            for g in profile.get("gpus", []) if isinstance(g, dict)).__repr__()}
    blob = json.dumps(ident, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def detect_hardware(disk_path: str = ".", measure_disk: bool = False,
                    run: Runner = _run) -> dict:
    """Perfil completo. ``measure_disk=True`` e o unico caminho que escreve em disco."""
    profile = {"schema": 1,
               "os": {"system": platform.system(), "release": platform.release()},
               "cpu": detect_cpu(run), "ram": detect_ram(run),
               "gpus": detect_gpus(run), "disk": detect_disk(disk_path)}
    if measure_disk:
        profile["disk_throughput"] = measure_disk_throughput(os.path.abspath(disk_path))
    profile["hw_fingerprint"] = compute_fingerprint(profile)
    return profile


def main(argv: Optional[list] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    print(json.dumps(detect_hardware(measure_disk="--measure-disk" in args),
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
