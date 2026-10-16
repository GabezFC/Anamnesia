"""ANAM-030 (hw_profile) e ANAM-031 (model_catalog)."""
import copy
import json

import pytest

from app.services import hw_profile as hw
from app.services import model_catalog as mc

SMI_GOLDEN = "NVIDIA GeForce RTX 3060, 12288, 10800, 616.92, 8.6\n"


def _runner(smi=SMI_GOLDEN):
    def run(cmd):
        return smi if cmd and cmd[0] == "nvidia-smi" else None
    return run


def test_parse_nvidia_smi_golden_vram_e_sm():
    g = hw.parse_nvidia_smi(SMI_GOLDEN)[0]
    assert g["vram_total_gb"] == 12.0 and g["sm"] == "sm_86" and g["driver"] == "616.92"


def test_parse_nvidia_smi_lixo_ignorado():
    assert hw.parse_nvidia_smi("") == [] and hw.parse_nvidia_smi("erro qualquer") == []
    assert hw.parse_nvidia_smi("X, [N/A], [N/A], 1, [N/A]")[0]["compute_cap"] is None


def test_golden_profile_com_mocks(monkeypatch):
    monkeypatch.setattr(hw, "detect_cpu", lambda run=None: {
        "name": "AMD Ryzen 7 5700G with Radeon Graphics", "cores": 8, "threads": 16, "arch": "AMD64"})
    monkeypatch.setattr(hw, "detect_ram", lambda run=None: {
        "total_gb": 39.79, "free_gb": 20.0, "free_phys_gb": 22.0, "free_commit_gb": 20.0})
    monkeypatch.setattr(hw, "_gpus_nvml", lambda: [])
    monkeypatch.setattr(hw, "detect_disk", lambda p=".": {"path": "C:", "total_gb": 930.4, "free_gb": 619.0})
    p = hw.detect_hardware(run=_runner())
    assert p["cpu"]["cores"] == 8 and p["cpu"]["threads"] == 16
    assert abs(p["ram"]["total_gb"] * 1.0737 - 42.7) < 0.2  # ~42,7 GB decimais
    assert p["gpus"][0]["vram_total_gb"] == 12.0 and p["gpus"][0]["sm"] == "sm_86"
    assert "disk_throughput" not in p  # opt-in
    assert len(p["hw_fingerprint"]) == 16


def test_fingerprint_estavel_ignora_valores_livres(monkeypatch):
    monkeypatch.setattr(hw, "_gpus_nvml", lambda: [])
    base = {"os": {"system": "Windows"}, "cpu": {"name": "c", "cores": 8, "threads": 16},
            "ram": {"total_gb": 39.79}, "gpus": hw.parse_nvidia_smi(SMI_GOLDEN)}
    other = copy.deepcopy(base)
    other["gpus"][0]["vram_free_gb"] = 1.0
    other["gpus"][0]["driver"] = "999.0"
    other["ram"]["free_gb"] = 3
    assert hw.compute_fingerprint(base) == hw.compute_fingerprint(other)
    other["gpus"][0]["vram_total_gb"] = 24
    assert hw.compute_fingerprint(base) != hw.compute_fingerprint(other)


def test_sem_nvidia_smi_gpus_vazio(monkeypatch):
    monkeypatch.setattr(hw, "_gpus_nvml", lambda: [])
    assert hw.detect_gpus(run=lambda c: None) == []


def test_ram_usa_minimo_fisica_commit(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "psutil", None)  # força caminho stdlib
    monkeypatch.setattr(hw, "_ram_windows", lambda: {"total": 40 * hw.GIB, "free_phys": 30 * hw.GIB,
                                                      "free_commit": 12 * hw.GIB})
    monkeypatch.setattr(hw.sys, "platform", "win32")
    r = hw.detect_ram()
    assert r["total_gb"] == 40 and r["free_gb"] == 12


def test_throughput_opt_in_roda_e_limpa(tmp_path):
    r = hw.measure_disk_throughput(str(tmp_path), size_mb=2, rand_reads=16)
    assert r["seq_128k_mb_s"] > 0 and r["rand_4k_iops"] > 0
    assert list(tmp_path.iterdir()) == []


def test_detector_real_serializa_json():
    p = hw.detect_hardware()
    json.dumps(p)
    assert p["cpu"]["threads"] and p["hw_fingerprint"]


# ------------------------------------------------------------ catalogo
def test_catalogo_real_passa_esquema():
    cat = mc.load_catalog()
    assert mc.validate_catalog(cat) == [] and len(cat["models"]) >= 20


def test_llama_gemma_unverified_e_bloqueados_em_comercial():
    models = {m["id"]: m for m in mc.load_catalog()["models"]}
    for mid, m in models.items():
        if any(t in mid for t in ("gemma", "llama")):
            assert m["license_status"] == "UNVERIFIED" and m["license"] is None, mid
            with pytest.raises(mc.CommercialBlocked):
                mc.get_model(mid)
            assert mc.get_model(mid, mode="livre")["id"] == mid


def test_comercial_libera_apache_verificado():
    m = mc.get_model("qwen3.5-9b")
    assert m["license"] == "apache-2.0" and m["commercial_use"] is True
    assert all(mc.is_commercial_ok(x) for x in mc.list_models())
    assert len(mc.list_models()) < len(mc.list_models(mode="livre"))


def test_comercial_bloqueia_non_commercial_e_sem_licenca():
    nc = {"license": "cc-by-nc-4.0", "license_status": "VERIFIED", "commercial_use": True}
    assert not mc.is_commercial_ok(nc)
    assert not mc.is_commercial_ok({"license": "mit", "license_status": "VERIFIED", "commercial_use": False})
    assert not mc.is_commercial_ok({"license": None, "license_status": "UNVERIFIED", "commercial_use": None})


def test_esquema_rejeita_violacoes():
    cat = copy.deepcopy(mc.load_catalog())
    cat["models"][0]["revision_sha"] = "main"
    cat["models"][1]["license_status"] = "UNVERIFIED"
    cat["models"][1]["license"] = "mit"
    del cat["models"][2]["repo"]
    cat["models"].append(copy.deepcopy(cat["models"][3]))
    errs = " | ".join(mc.validate_catalog(cat))
    assert "revision_sha" in errs and "UNVERIFIED nao pode" in errs
    assert "campo ausente 'repo'" in errs and "duplicado" in errs


def test_nenhum_valor_unverified_vaza_no_catalogo():
    for m in mc.load_catalog()["models"]:
        assert "UNVERIFIED" not in str(m.get("license") or "")
        assert m["revision_sha"] is None or len(m["revision_sha"]) == 40


def test_pesos_ignorados_no_git():
    import subprocess
    r = subprocess.run(["git", "check-ignore", "data/local_ai/models/x.gguf"],
                       capture_output=True, text=True)
    assert r.returncode == 0
