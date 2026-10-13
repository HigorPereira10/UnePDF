"""Ponto de entrada do UnePDF. Execute com: py -m unepdf"""
import sys

from unepdf.ui.app import executar


def main() -> None:
    sys.exit(executar())


if __name__ == "__main__":
    main()
