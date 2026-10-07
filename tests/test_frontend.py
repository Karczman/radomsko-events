import re
from pathlib import Path

WEB = Path(__file__).parent.parent / "web"


def test_every_function_called_in_app_js_is_defined():
    """Brak node w CI, więc prosta kontrola statyczna (wyłapała usunięcie `subscribeLink` przy edycji)."""
    js = (WEB / "app.js").read_text("utf-8")
    defined = set(re.findall(r"(?:function\s+|const\s+)(\w+)\s*(?:\(|=)", js))
    called_in_main = re.search(r"async function main\(\) \{(.*?)\n\}\nmain\(\);", js, re.S).group(1)
    builtins = {"if", "catch", "for", "while", "fetch", "prompt", "setTimeout", "Promise", "URL", "Set", "Date"}
    # tylko wywołania bez obiektu (bez `.metoda(`)
    for name in re.findall(r"(?<![.\w])([a-zA-Z_]\w*)\(", called_in_main):
        assert name in defined or name in builtins, f"app.js woła niezdefiniowaną funkcję {name}"


def test_index_references_existing_assets_and_dom_ids_used_by_script():
    html = (WEB / "index.html").read_text("utf-8")
    for asset in re.findall(r'(?:src|href)="((?!https?:)[^"#]+)"', html):
        assert (WEB / asset).exists(), asset
    js = (WEB / "app.js").read_text("utf-8")
    ids = set(re.findall(r'\$\("(\w+)"\)', js))
    assert ids <= set(re.findall(r'id="(\w+)"', html)), ids - set(re.findall(r'id="(\w+)"', html))
