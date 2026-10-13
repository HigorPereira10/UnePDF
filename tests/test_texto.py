from unepdf.utils.texto import plural


def test_plural():
    assert plural(0, "arquivo", "arquivos") == "0 arquivos"
    assert plural(1, "arquivo", "arquivos") == "1 arquivo"
    assert plural(2, "arquivo unido", "arquivos unidos") == "2 arquivos unidos"
