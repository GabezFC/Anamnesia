"""ANAM-004/005: allow-list de egress + OFFLINE sem abrir socket."""
import socket

import pytest

from app.services import egress, jev_setup, offline
from app.services.egress import EgressBlocked, check_egress


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for k in (egress.ALLOW_ENV, *offline.ENV_VARS):
        monkeypatch.delenv(k, raising=False)


def test_host_fora_da_lista_recusado():
    with pytest.raises(EgressBlocked, match="allow-list"):
        check_egress("https://evil.example.com/v1", "teste")


def test_http_remoto_recusado_e_loopback_permitido():
    with pytest.raises(EgressBlocked):
        check_egress("http://api.openai.com", "teste")
    check_egress("http://127.0.0.1:11434", "teste")
    check_egress("http://localhost:8000", "teste")


def test_hosts_oficiais_default_permitidos():
    for h in egress.DEFAULT_ALLOW_HOSTS:
        check_egress(f"https://{h}/x", "teste")


def test_env_substitui_lista_e_aceita_curinga(monkeypatch):
    monkeypatch.setenv(egress.ALLOW_ENV, "meu.host.com, *.corp.io")
    check_egress("https://meu.host.com", "t")
    check_egress("https://a.corp.io", "t")
    with pytest.raises(EgressBlocked):
        check_egress("https://corp.io", "t")
    with pytest.raises(EgressBlocked):
        check_egress("https://api.openai.com", "t")


def test_jev_setup_valida_base_url_com_allow_list(monkeypatch):
    assert jev_setup.validate_base_url("https://api.typesafe.ai/") == "https://api.typesafe.ai"
    with pytest.raises(jev_setup.JevSetupError) as ei:
        jev_setup.validate_base_url("https://exfil.attacker.net")
    assert ei.value.code == "host_not_allowed" and ei.value.field == "base_url"
    monkeypatch.setenv(egress.ALLOW_ENV, "exfil.attacker.net")
    assert jev_setup.validate_base_url("https://exfil.attacker.net") == "https://exfil.attacker.net"
    assert jev_setup.validate_base_url("http://localhost:9000") == "http://localhost:9000"


def test_log_nao_vaza_caminho_nem_query(caplog):
    with caplog.at_level("INFO", logger="anamnesia.egress"):
        check_egress("https://api.openai.com/v1/chat?key=SEGREDO123", "t")
        with pytest.raises(EgressBlocked):
            check_egress("https://x.evil.com/p?key=SEGREDO123", "t")
    assert "SEGREDO123" not in caplog.text and "api.openai.com" in caplog.text


def test_offline_nao_abre_socket(monkeypatch):
    monkeypatch.setenv("ANAMNESIA_OFFLINE", "1")
    calls = []
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: calls.append(("connect", a)))
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: calls.append(("cc", a)))
    for url in ("https://api.openai.com", "https://api.typesafe.ai", "https://evil.com"):
        with pytest.raises(offline.OfflineBlocked):
            check_egress(url, "t")
    check_egress("http://127.0.0.1:11434", "t")  # loopback segue permitido
    # adaptador real: devolve falha tratada, sem tocar socket
    from app.adapters.models.providers import OpenAIAdapter
    OpenAIAdapter("m").generate("oi")
    assert calls == []
