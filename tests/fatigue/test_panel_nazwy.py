# catalog-read
"""One name per component, everywhere the reader can see it.

Why this exists (2026-08-07, pilot session P04): the panel showed the formula with
internal keys - `DFI = (0.40×volume + 0.25×concurrency + 0.20×burstiness + …)` - and,
directly underneath, a table of weights using reader-facing labels ("Activity spike").
The participant had to ask whether the two referred to the same thing:

    "which here is the weight for burstiness. Is this the activity spike?"

That question costs the study twice. It spends the participant's attention on naming
while we are measuring their cognitive load, and it lands in the field notes as
"did not understand the component" when the truth is "did not recognise the name".

These are static checks: they read the config and the page, so they run without a
browser and without a server. They fail when a component is added to the index and
its label is forgotten - which is exactly when the mismatch would come back.
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "app" / "static" / "dashboard.html"
CONFIG = ROOT / "fatigue_config.yaml"
ENGINE = ROOT / "app" / "services" / "fatigue_engine.py"


def _weight_rows() -> dict:
    """The key → label mapping the page uses for the weights table."""
    html = DASHBOARD.read_text(encoding="utf-8")
    blok = re.search(r"const WEIGHT_ROWS = \[(.*?)\];", html, re.S)
    assert blok, "WEIGHT_ROWS disappeared from the dashboard"
    return dict(re.findall(r'\["(\w+)",\s*"([^"]+)"\]', blok.group(1)))


def test_every_weighted_component_has_a_label():
    """A component with a weight but no label would show up as a bare key."""
    wagi = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["weights"]
    etykiety = _weight_rows()
    brakujace = sorted(set(wagi) - set(etykiety))
    assert not brakujace, f"components without a reader-facing label: {brakujace}"


def test_formula_is_translated_before_it_is_shown():
    """The page must render the formula through the label mapping, not raw."""
    html = DASHBOARD.read_text(encoding="utf-8")
    assert "function formulaWithLabels" in html, "the translation helper is gone"
    assert re.search(r'class:\s*"dfi-formula",\s*text:\s*formulaWithLabels\(', html), (
        "the formula is rendered raw again - internal keys will reach the reader"
    )


def test_translation_leaves_no_internal_key_behind():
    """Run the same substitution the page runs, on the formula the engine sends."""
    wzor = re.search(r'"(DFI = \(.*?)"\s*\n?\s*"(.*?)"', ENGINE.read_text(encoding="utf-8"), re.S)
    formula = (wzor.group(1) + wzor.group(2)) if wzor else ""
    assert "DFI =" in formula, "could not read the formula from the engine"

    etykiety = _weight_rows()
    przetlumaczona = formula
    for klucz, etykieta in etykiety.items():
        przetlumaczona = przetlumaczona.replace(klucz, etykieta)

    # A key counts as leftover only when it stands on its own - "volume" inside
    # "Recent volume" is the substitution working, not failing.
    for klucz, etykieta in etykiety.items():
        bez_etykiet = przetlumaczona.replace(etykieta, "")
        assert not re.search(rf"\b{re.escape(klucz)}\b", bez_etykiet), (
            f"internal key '{klucz}' survives in the formula shown to the reader"
        )


def test_labels_are_not_internal_keys():
    """A label identical to the key means the rename never happened."""
    for klucz, etykieta in _weight_rows().items():
        assert etykieta != klucz, f"'{klucz}' is shown under its internal name"


def test_panel_pokazuje_werdykt_kwalifikacji():
    """P10: pomiar niekwalifikowany nie moze wygladac na panelu jak pierwszorzedny.

    Do 2026-09-11 `dashboard.html` nie mial ani jednego wystapienia `eligibility` - a panel
    widzieli uczestnicy Fazy A i B, wiec liczba bez werdyktu byla im pokazywana jako gotowy
    wynik. Uczestnik P04 powiedzial o panelu "I just see a lot of numbers here"; jedna z tych
    liczb mogla nie miec prawa wejsc do analizy i nikt by tego nie zobaczyl.
    """
    tresc = DASHBOARD.read_text(encoding="utf-8")
    assert "renderEligibility" in tresc, "panel nie ma sekcji werdyktu"
    assert "eligibility_reasons" in tresc, "panel nie pokazuje powodow dyskwalifikacji"
    assert "PRIMARY_ELIGIBLE" in tresc, "panel nie rozpoznaje werdyktu pierwszorzednego"
    # Sekcja musi byc SKLADANA, nie tylko zdefiniowana - funkcja bez wywolania nic nie pokaze.
    assert "renderEligibility(data)" in tresc, "sekcja werdyktu nie jest wstawiana do panelu"


def test_panel_nie_przedstawia_novelty_jako_czesci_wyniku():
    """Panel widzi uczestnik PRZED wypełnieniem ankiety - i czyta go sam.

    Od config 1.8.0 (D1=B) `novelty` jest liczona i pokazywana, ale nie wchodzi do
    `fatigue_score`. Pasek bez oznaczenia i wiersz „5%" w tabeli wag mówiłyby czytającemu,
    że składnik przesunął jego liczbę - a to nieprawda. To ta sama klasa błędu, którą
    projekt naprawia w kodzie: etykieta niezgodna z faktem.

    Test jest statyczny (czyta stronę i konfigurację), więc chodzi bez przeglądarki.
    """
    html = DASHBOARD.read_text(encoding="utf-8")
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    pierwszorzedne = set(config["primary_components_per_event"])
    poza = set(config["weights"]) - pierwszorzedne
    assert poza, "test straciłby moc: każdy składnik wchodzi do wyniku"

    for skladnik in poza:
        wpis = re.search(r'\{\s*key:\s*"%s".*?\}' % skladnik, html, re.S)
        assert wpis, f"składnik {skladnik} zniknął z indeksu panelu"
        assert "excluded: true" in wpis.group(0), (
            f"{skladnik} nie wchodzi do wyniku, a panel pokazuje go jak każdy inny "
            "składnik - czytający ma prawo sądzić, że przesunął jego liczbę")

    # Tabela wag ma liczyć udziały wobec składników pierwszorzędnych, a nie wobec 1,0.
    assert "not counted" in html, (
        "tabela wag nie oznacza składnika spoza wyniku")
    assert re.search(r"primary\s*\.indexOf|indexOf\(r\[0\]\)", html), (
        "tabela wag nie pyta o zakres pomiaru - pokaże wagę surową dla każdego składnika")


def test_wzor_na_panelu_opisuje_wariant_per_event():
    """Panel per-event pokazuje wzór, którym policzono TĘ liczbę.

    API wysyłało wzór wariantu ekosystemowego na obu ścieżkach, więc po zmianie zakresu
    uczestnik zobaczyłby pięcioskładnikowy wzór pod czteroskładnikowym wynikiem."""
    silnik = ENGINE.read_text(encoding="utf-8")
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

    assert "FORMULA_PER_EVENT" in silnik, "brak wzoru wariantu per-event"
    wzor = re.search(r"FORMULA_PER_EVENT = \(\s*(.*?)\)\s*\n", silnik, re.S).group(1)
    assert "novelty" not in wzor, "wzór per-event nadal wymienia novelty"
    assert "0.95" in wzor, "wzór per-event nie pokazuje dzielnika"

    # Każda ścieżka per-event w API musi wysyłać ten wzór, nie ekosystemowy.
    per_event = re.findall(r"formula=FatigueEngine\.(\w+),\s*\n\s*mode=", main)
    assert per_event, "nie znaleziono ścieżek per-event w API"
    assert set(per_event) == {"FORMULA_PER_EVENT"}, per_event


def test_panel_dostaje_zakres_z_ODPOWIEDZI_nie_zaklada_go():
    """Tabela wag musi liczyć udziały wobec zakresu z odpowiedzi API.

    Wartość domyślna „wszystkie składniki" jest w kodzie po to, żeby stary zapis nie
    wywracał strony - ale gdyby wywołanie nie przekazało zakresu, panel LICZYŁBY z niej
    zawsze i pokazywał 5% przy składniku spoza wyniku. Tę pomyłkę widać wyłącznie
    w miejscu wywołania, nie w samej funkcji."""
    html = DASHBOARD.read_text(encoding="utf-8")
    # Pierwsza wersja tego warunku trafiała w DEFINICJĘ funkcji (ma parametr o tej nazwie)
    # i przechodziła niezależnie od tego, co robi wywołanie. Szukamy wywołania: argumenty
    # pochodzące z odpowiedzi API, czyli z `data.`.
    wywolania = [m for m in re.findall(r"renderHowCalculated\((.*?)\)[,;]", html, re.S)
                 if "data." in m]
    assert wywolania, "panel nie renderuje tabeli wag z danych odpowiedzi"
    assert all("primary_components" in w for w in wywolania), (
        f"wywołanie nie przekazuje zakresu pomiaru - tabela pokaże wagi surowe: {wywolania}")


def test_pasek_skladnika_spoza_wyniku_jest_oznaczony_na_stronie():
    """Sama flaga w indeksie nic nie zmienia, dopóki nie trafi do renderowanego wiersza."""
    html = DASHBOARD.read_text(encoding="utf-8")
    assert "spec.excluded" in html, "flaga `excluded` nie dociera do paska"
    assert "dfi-bar-excluded" in html, "brak widocznego oznaczenia przy pasku"
    assert ".dfi-bar-excluded {" in html, "oznaczenie nie ma stylu - wyjdzie jako goły tekst"
