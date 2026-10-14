"""Formatação de textos exibidos ao usuário."""


def plural(quantidade: int, singular: str, plural: str) -> str:
    """Ex.: plural(1, "arquivo", "arquivos") -> "1 arquivo"; plural(3, ...) -> "3 arquivos"."""
    return f"{quantidade} {singular if quantidade == 1 else plural}"


def tamanho_legivel(bytes_: int) -> str:
    """Ex.: 850 -> "850 bytes"; 1_250_000 -> "1,2 MB" (com vírgula, como no Windows em português)."""
    for limite, unidade in ((1024**3, "GB"), (1024**2, "MB"), (1024, "KB")):
        if bytes_ >= limite:
            valor = bytes_ / limite
            texto = f"{valor:.1f}" if valor < 10 else f"{valor:.0f}"
            return f"{texto.replace('.', ',')} {unidade}"
    return plural(bytes_, "byte", "bytes")
