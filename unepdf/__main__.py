"""Ponto de entrada do UnePDF. Execute com: py -m unepdf"""
import sys
from pathlib import Path

if not __package__:
    # Rodando como script (ex.: pelo menu do Explorer, a partir do código-fonte): torna o pacote importável
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unepdf.ui.app import executar  # noqa: E402


def main() -> None:
    sys.exit(executar())


if __name__ == "__main__":
    main()
