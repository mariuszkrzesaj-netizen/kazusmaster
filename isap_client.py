import json
import re
from pathlib import Path
from typing import Dict, List, Optional
import requests
from bs4 import BeautifulSoup

# Oficjalny punkt końcowy API Sejmu RP (European Legislation Identifier)
SEJM_ELI_BASE_URL = "https://api.sejm.gov.pl/eli"

# Rejestr podstawowych kodów ELI dla kluczowych kodeksów (Piony I–IV z protokołu)
REJESTR_KODEKSOW = {
    "KC": {"publisher": "DU", "year": 1964, "pos": 93, "nazwa": "Kodeks cywilny"},
    "KPC": {"publisher": "DU", "year": 1964, "pos": 296, "nazwa": "Kodeks postępowania cywilnego"},
    "KK": {"publisher": "DU", "year": 1997, "pos": 553, "nazwa": "Kodeks karny"},
    "KPK": {"publisher": "DU", "year": 1997, "pos": 555, "nazwa": "Kodeks postępowania karnego"},
    "KSH": {"publisher": "DU", "year": 2000, "pos": 1037, "nazwa": "Kodeks spółek handlowych"},
    "KPA": {"publisher": "DU", "year": 1960, "pos": 168, "nazwa": "Kodeks postępowania administracyjnego"},
    "KP": {"publisher": "DU", "year": 1974, "pos": 141, "nazwa": "Kodeks pracy"},
    "KRO": {"publisher": "DU", "year": 1964, "pos": 59, "nazwa": "Kodeks rodzinny i opiekuńczy"},
}


class ISAPClient:
    """Klient oficjalnego API Sejmu (ELI) z lokalnym buforowaniem tekstów jednolitych."""

    def __init__(self, cache_dir: str = "./baza_ustaw_cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "LegalCaseTrainer-EduApp/1.0"
        })

    def pobierz_metadane_aktu(self, publisher: str, year: int, pos: int) -> dict:
        """Pobiera metadane aktu prawnego wraz z informacją o statusie i tekstach jednolitych."""
        url = f"{SEJM_ELI_BASE_URL}/acts/{publisher}/{year}/{pos}"
        response = self.session.get(url, timeout=15)
        response.raise_for_status()
        return response.json()

    def _znajdz_najnowszy_tekst_jednolity(self, metadane: dict) -> Optional[dict]:
        """
        Zwraca informacje o najnowszym tekście jednolitym (typ 'U')
        lub ostatnim dostępnym tekście (typ 'O' / 'T').
        """
        teksty = metadane.get("texts", [])
        if not teksty:
            return None

        teksty_jednolite = [t for t in teksty if t.get("type") == "U"]
        if teksty_jednolite:
            teksty_jednolite.sort(key=lambda x: x.get("published", ""), reverse=True)
            return teksty_jednolite[0]

        teksty_ogloszone = [t for t in teksty if t.get("type") == "O"]
        if teksty_ogloszone:
            return teksty_ogloszone[-1]

        return teksty[-1]

    def pobierz_i_sparsuj_ustawe(self, kod_skrotu: str, wymus_odswiezenie: bool = False) -> dict:
        """
        Pobiera oficjalny tekst ustawy z API Sejmu, parsuje na artykuły
        i zapisuje w lokalnym pliku JSON.
        """
        kod_skrotu = kod_skrotu.upper()
        if kod_skrotu not in REJESTR_KODEKSOW:
            raise ValueError(f"Nieznany skrót ustawy: {kod_skrotu}. Dostępne: {list(REJESTR_KODEKSOW.keys())}")

        cache_file = self.cache_dir / f"{kod_skrotu}_parsed.json"
        if cache_file.exists() and not wymus_odswiezenie:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)

        info = REJESTR_KODEKSOW[kod_skrotu]
        metadane = self.pobierz_metadane_aktu(info["publisher"], info["year"], info["pos"])

        status_aktu = metadane.get("status", "nieznany")
        tytul_oficjalny = metadane.get("title", info["nazwa"])
        adres_publikacyjny = metadane.get("displayAddress", "")

        html_url = f"{SEJM_ELI_BASE_URL}/acts/{info['publisher']}/{info['year']}/{info['pos']}/text.html"
        html_resp = self.session.get(html_url, headers={"Accept": "text/html"}, timeout=30)
        html_resp.raise_for_status()
        html_resp.encoding = "utf-8"

        artykuly = self._parsuj_html_do_artykulow(html_resp.text)

        wynik = {
            "skrot": kod_skrotu,
            "tytul": tytul_oficjalny,
            "adres_publikacyjny": adres_publikacyjny,
            "status": status_aktu,
            "data_ostatniej_zmiany": metadane.get("changeDate", ""),
            "liczba_artykulow": len(artykuly),
            "artykuly": artykuly
        }

        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(wynik, f, ensure_ascii=False, indent=2)

        return wynik

    def _parsuj_html_do_artykulow(self, html_content: str) -> Dict[str, str]:
        """
        Parsuje dokument HTML z ISAP/ELI na słownik:
        {'415': 'Art. 415. Kto z winy swej wyrządził drugiemu szkodę...', ...}
        Obsługuje również artykuły z indeksami górnymi/literowymi (np. '446(1)', '556[1]').
        """
        soup = BeautifulSoup(html_content, "html.parser")
        pelny_tekst = soup.get_text(separator="\n")

        linie = [re.sub(r"\s+", " ", linia).strip() for linia in pelny_tekst.splitlines()]
        linie = [l for l in linie if l]

        artykuly: Dict[str, str] = {}
        aktualny_nr: Optional[str] = None
        bufor_tresci: List[str] = []

        wzorzec_art = re.compile(r"^Art\.\s*(\d+[a-zA-Z0-9\(\)\[\]\^]*)\.\s*(.*)$")

        for linia in linie:
            dopasowanie = wzorzec_art.match(linia)
            if dopasowanie:
                if aktualny_nr is not None:
                    artykuly[aktualny_nr] = " ".join(bufor_tresci).strip()

                aktualny_nr = dopasowanie.group(1)
                reszta_linii = dopasowanie.group(2)
                bufor_tresci = [f"Art. {aktualny_nr}. {reszta_linii}".strip()]
            else:
                if aktualny_nr is not None:
                    if not re.match(r"^(DZIAŁ|ROZDZIAŁ|TYTUŁ|KSIĘGA|Oddział)\b", linia, re.IGNORECASE):
                        bufor_tresci.append(linia)

        if aktualny_nr is not None:
            artykuly[aktualny_nr] = " ".join(bufor_tresci).strip()

        return artykuly

    def pobierz_konkretne_artykuly(self, kod_skrotu: str, numery_artykulow: List[str]) -> dict:
        """
        Zwraca oficjalne brzmienie wskazanych artykułów oraz dane źródłowe
        do wstrzyknięcia w kontekst weryfikatora Gemini 4 Neon.
        """
        dane_ustawy = self.pobierz_i_sparsuj_ustawe(kod_skrotu)
        znalezione = {}
        brakujace = []

        for nr in numery_artykulow:
            nr_czysty = nr.strip().replace("Art.", "").replace("art.", "").strip()
            if nr_czysty in dane_ustawy["artykuly"]:
                znalezione[nr_czysty] = dane_ustawy["artykuly"][nr_czysty]
            else:
                brakujace.append(nr_czysty)

        return {
            "ustawa": dane_ustawy["tytul"],
            "publikator": dane_ustawy["adres_publikacyjny"],
            "status": dane_ustawy["status"],
            "przepisy": znalezione,
            "nieodnalezione": brakujace
        }


if __name__ == "__main__":
    klient = ISAPClient()
    print("Pobieranie przepisów z Kodeksu cywilnego (API Sejmu ELI)...")
    wynik = klient.pobierz_konkretne_artykuly("KC", ["118", "415", "471", "556"])
    print(f"\nŹródło: {wynik['ustawa']} ({wynik['publikator']}) | Status: {wynik['status']}")
    print("-" * 70)
    for nr, tresc in wynik["przepisy"].items():
        print(f"[{nr}] {tresc}\n")
