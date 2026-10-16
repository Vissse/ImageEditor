"""What changed in each version, shown to the user once after an update
("Co je nového") and any time from the version number in the footer.

When releasing: add the new version at the TOP, written for users (what they
can now do, not how it is implemented), and bump CURRENT_VERSION to match.
"""
from __future__ import annotations

CHANGELOG: list[tuple[str, list[str]]] = [
    ("1.3.2", [
        "Chytrý ořez – v náhledu fotky klikněte na „Chytrý ořez“ (nebo klávesa A) "
        "a aplikace sama najde obrázek na jednobarevném pozadí, třeba naskenovanou "
        "stránku nebo obálku knihy. Rámeček jde ještě doladit, pak stačí „Uložit ořez“.",
    ]),
    ("1.3.1", [
        "Aplikace už neukládá svůj pomocný soubor do složky s fotkami (např. na Plochu).",
    ]),
    ("1.3.0", [
        "Ořez fotek – klikněte na fotku, pak „Oříznout“ (nebo klávesa C) a táhněte "
        "za úchyty rámečku jako v Malování.",
        "Zpět a Znovu – šipky v sekci Úpravy nebo Ctrl+Z / Ctrl+Y vrátí zpracování "
        "i ořez (až 10 kroků, dokud aplikaci nezavřete).",
        "Nové formáty: PDF, HEIC z iPhonu, PSD, TIFF a další. Při zpracování se převedou na JPG.",
        "Vícestránkové PDF se uloží do podsložky, jedna stránka = jeden JPG. Do podsložky "
        "vstoupíte kliknutím, zpět tlačítkem „← Zpět“ nebo klávesou Backspace.",
        "Přidávání souborů tlačítkem „Přidat soubory…“ nebo přetažením myší do okna.",
        "U hotových fotek je vidět, co se s nimi udělalo (např. 1024 · rámeček · jpg).",
        "Rámeček se už nikdy nepřidá dvakrát – fotky, které ho mají, se přeskočí "
        "a aplikace vás na to upozorní.",
        "Mazání vybraných fotek do Koše – tlačítko „Smazat“ nebo klávesa Delete.",
        "Export ukazuje náhled cílové složky, nově přesunuté fotky jsou zvýrazněné.",
        "Aktualizace jde kdykoliv zkontrolovat odkazem vpravo dole.",
        "Nový čistší vzhled: přehlednější pravý panel, hlášení ve stylu aplikace "
        "a srovnané náhledy fotek.",
    ]),
]


def _key(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return (0,)


def history(current: str) -> list[tuple[str, list[str]]]:
    """All entries up to `current`, newest first - what "Co je nového" shows,
    so the earlier versions' news stay readable after an update."""
    return [entry for entry in CHANGELOG if _key(entry[0]) <= _key(current)]
