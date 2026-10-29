"""Testes estáticos (sem Docker, sem rede) dos arquivos da instância de TESTE da Laya (mglaya / anamnesia:laya-test)."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "docker" / "docker-compose.laya-test.yml"
DOCKERFILE = ROOT / "docker" / "Dockerfile.laya-test"
ENVF = ROOT / "docker" / "laya-test.env.example"
SCRIPT = ROOT / "scripts" / "mglaya.py"


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def svc(compose):
    return compose["services"]["laya"]


def test_files_exist():
    for p in (COMPOSE, DOCKERFILE, ENVF, SCRIPT):
        assert p.is_file(), p


def test_ports_never_8000_or_8010(svc):
    ports = svc["ports"]
    assert ports, "deve publicar uma porta"
    for spec in ports:
        assert spec == "127.0.0.1:${LAYA_TEST_PORT:-8030}:8000", f"somente loopback, padrao 8030: {spec}"
    env = ENVF.read_text(encoding="utf-8")
    assert re.search(r"^LAYA_TEST_PORT=8030\s*$", env, re.M)


def test_names_are_own(compose, svc):
    assert svc["image"] == "anamnesia:laya-test"
    assert svc["image"] != "anamnesia:local"
    assert compose["volumes"]["laya-data"]["name"] == "mglaya_data"
    assert compose["networks"]["laya"]["name"] == "mglaya_net"
    sub = compose["networks"]["laya"]["ipam"]["config"][0]["subnet"]
    assert sub != "172.29.240.0/24"            # sub-rede do mgtest
    assert "container_name" not in svc or svc["container_name"].startswith("mglaya")
    txt = COMPOSE.read_text(encoding="utf-8")
    assert "mgtest_anamnesia-data" not in txt and "anamnesia:local" not in txt.split("services:", 1)[1]


def test_weights_mounted_read_only(svc):
    mounts = {v["target"]: v for v in svc["volumes"] if isinstance(v, dict)}
    assert mounts["/models"]["type"] == "bind" and mounts["/models"]["read_only"] is True
    assert mounts["/vault"]["read_only"] is True
    assert mounts["/data"]["type"] == "volume" and mounts["/data"]["source"] == "laya-data"
    # nenhum bind de escrita em nada que não seja o volume nomeado
    for v in svc["volumes"]:
        if isinstance(v, dict) and v["type"] == "bind":
            assert v.get("read_only") is True, v


def test_laya_env(svc):
    e = svc["environment"]
    assert e["MG_LAYA_MODE"] == "inproc"
    assert e["MG_LAYA_MULTILINGUAL_DIR"] == "/models/laya-multilingual"
    assert e["MG_LAYA_ENGLISH_DIR"] == "/models/laya-english"
    assert e["MG_LAYA_MODELS_DIR"] == "/models"
    assert e["MG_LAYA_DEVICE"] == "cpu"
    assert e["HF_HUB_OFFLINE"] == "1"
    assert "OMP_NUM_THREADS" in e and "MKL_NUM_THREADS" in e and "MG_LAYA_THREADS" in e
    assert e["MG_TRUSTED_LOCAL_CLIENTS"] == "172.29.241.1"      # gateway da rede própria


def test_no_privileged_or_docker_sock(svc):
    txt = COMPOSE.read_text(encoding="utf-8")
    assert "docker.sock" not in txt
    for bad in ("privileged", "cap_add", "pid", "network_mode", "devices", "security_opt"):
        assert bad not in svc, bad
    assert svc.get("restart") == "no"


def test_dockerfile_rules():
    d = DOCKERFILE.read_text(encoding="utf-8")
    assert re.search(r"^FROM python:3\.12-slim@sha256:[0-9a-f]{64}$", d, re.M)
    assert "laya==0.4.8" in d and "torch==2.14.1" in d and "download.pytorch.org/whl/cpu" in d
    assert re.search(r"^USER anamnesia$", d, re.M)
    assert not re.search(r"^(COPY|ADD)\b.*\b(models|safetensors|local_ai)", d, re.M | re.I)  # pesos nunca na imagem
    assert "HEALTHCHECK" in d


def test_no_secrets():
    pat = re.compile(r"(?i)(sk-[A-Za-z0-9_-]{16,}|api[_-]?key\s*[=:]\s*\S{8,}|MG_LOCAL_TOKEN\s*[=:]\s*\S+|\b[A-Fa-f0-9]{40,}\b|BEGIN [A-Z ]*PRIVATE KEY)")
    for p in (COMPOSE, DOCKERFILE, ENVF, SCRIPT):
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if "sha256:" in line:       # digests de imagem/pesos publicados não são segredo
                continue
            assert not pat.search(line), f"{p.name}:{i}"


def _load_script():
    spec = importlib.util.spec_from_file_location("mglaya_under_test", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_script_guards():
    m = _load_script()
    assert m.PROJECT == "mglaya" and m.CONTAINER == "mglaya-laya-1" and m.IMAGE == "anamnesia:laya-test"
    assert {8000, 8010} <= m.FORBIDDEN_PORTS
    with pytest.raises(SystemExit):
        m.cmd_down("-v")
    with pytest.raises(SystemExit):
        m.cmd_down("--rmi")
    assert m.port() == 8030
    cmd = m.compose_base()
    assert cmd[:4] == ["docker", "compose", "-p", "mglaya"] and str(COMPOSE) in cmd


def test_compare_tolerance(tmp_path):
    m = _load_script()
    a = tmp_path / "a.json"; b = tmp_path / "b.json"; c = tmp_path / "c.json"
    a.write_text('{"results":[{"p_yes":0.3036,"lat_ms":10}]}'); b.write_text('{"results":[{"p_yes":0.3040,"lat_ms":99}]}')
    c.write_text('{"results":[{"p_yes":0.5,"lat_ms":99}]}')
    with pytest.raises(SystemExit) as ok:
        m.cmd_compare(str(a), str(b), "--tol", "0.01")
    assert ok.value.code == 0
    with pytest.raises(SystemExit) as bad:
        m.cmd_compare(str(a), str(c), "--tol", "0.01")
    assert bad.value.code == 1
