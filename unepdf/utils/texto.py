"""Formatação de textos exibidos ao usuário."""


def plural(quantidade: int, singular: str, plural: str) -> str:
    """Ex.: plural(1, "arquivo", "arquivos") -> "1 arquivo"; plural(3, ...) -> "3 arquivos"."""
    return f"{quantidade} {singular if quantidade == 1 else plural}"
