"""Docker E2E (D2): arquivos `*.env` (ex.: segredo.env) devem ser tratados como segredo na pré-visualização,
consistente com o scanner de indexação (`*.env`)."""
import pytest

from app.terminals.projects import SecretFileError, is_secret_file, read_file


@pytest.mark.parametrize("name", [".env", ".env.local", "segredo.env", "PROD.ENV", "id_rsa", "a.pem"])
def test_is_secret_file_true(name):
    assert is_secret_file(name)


@pytest.mark.parametrize("name", ["environment.py", "env.md", "nota.md", "a.py"])
def test_is_secret_file_false(name):
    assert not is_secret_file(name)


def test_read_file_blocks_suffix_env(tmp_path):
    (tmp_path / "segredo.env").write_text("VALOR_FALSO=x\n", encoding="utf-8")
    with pytest.raises(SecretFileError):
        read_file(str(tmp_path), "segredo.env")
