from pathlib import Path

from unepdf.utils import programas


def test_prefere_a_copia_que_vai_junto_com_o_app(tmp_path, monkeypatch):
    do_app = tmp_path / "app" / "ghostscript" / "bin" / "gswin64c.exe"
    instalado = tmp_path / "gs" / "gs10.08.0" / "bin" / "gswin64c.exe"
    for executavel in (do_app, instalado):
        executavel.parent.mkdir(parents=True)
        executavel.write_bytes(b"")
    monkeypatch.setattr(programas, "pasta_do_app", lambda: tmp_path / "app")
    monkeypatch.setattr(programas, "_do_registro", lambda: [instalado])

    assert programas.localizar_ghostscript() == do_app

    do_app.unlink()
    assert programas.localizar_ghostscript() == instalado


def test_sem_ghostscript(tmp_path, monkeypatch):
    monkeypatch.setattr(programas, "pasta_do_app", lambda: tmp_path)
    monkeypatch.setattr(programas, "_do_registro", lambda: [])
    monkeypatch.setattr(programas, "_das_pastas_padrao", lambda: [])
    monkeypatch.setattr(programas.shutil, "which", lambda nome: None)
    assert programas.localizar_ghostscript() is None


def test_prefere_a_versao_mais_nova_nas_pastas_padrao(tmp_path, monkeypatch):
    for versao in ("gs9.56.1", "gs10.08.0", "gs10.2.1"):
        executavel = tmp_path / "gs" / versao / "bin" / "gswin64c.exe"
        executavel.parent.mkdir(parents=True)
        executavel.write_bytes(b"")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("ProgramW6432", raising=False)

    assert programas._das_pastas_padrao()[0].parts[-3] == "gs10.08.0"


def test_versao_no_caminho():
    assert programas._versao(Path(r"C:\Program Files\gs\gs10.08.0\bin")) == (10, 8, 0)
    assert programas._versao(Path(r"C:\gs\bin")) == ()
