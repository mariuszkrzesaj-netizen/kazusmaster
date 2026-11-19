import os
from datetime import date
from typing import Dict, List, Literal, Optional
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from isap_client import ISAPClient, REJESTR_KODEKSOW
from terminy import oblicz_termin


# =====================================================================
# 1. SCHEMATY DANYCH WYJŚCIOWYCH (Zgodne z Gemini Developer API)
# =====================================================================

class PodmiotKazusu(BaseModel):
    nazwa: str = Field(description="Imię, nazwisko lub nazwa podmiotu (np. Jan Kowalski, Alfa Sp. z o.o.)")
    rola_prawna: str = Field(description="Rola w stosunku prawnym lub procesie (np. Sprzedawca, Kupujący, Powód, Pozwany)")
    status_szczegolny: Optional[str] = Field(
        default=None,
        description="Np. konsument, przedsiębiorca, małoletni, pełnomocnik procesowy"
    )


class ZdarzenieOsiCzasu(BaseModel):
    data: str = Field(description="Data w formacie YYYY-MM-DD lub opis względny z kazusu")
    opis_zdarzenia: str = Field(description="Co dokładnie wydarzyło się w tym dniu")
    znaczenie_prawne: str = Field(description="Dlaczego ta data jest istotna (np. początek biegu terminu rękojmi/apelacji)")


class PodstawaPrawnaUstawy(BaseModel):
    skrot_ustawy: str = Field(description="Skrót aktu prawnego z listy: KC, KPC, KK, KPK, KSH, KPA, KP, KRO")
    numery_artykulow: List[str] = Field(description="Lista numerów artykułów, np. ['556', '560']")


class PrzeslankaPrzepisu(BaseModel):
    artykul: str = Field(description="Oznaczenie przepisu, np. art. 415 KC")
    nazwa_przeslanki: str = Field(description="Nazwa przesłanki ustawowej, np. Zdarzenie zawinione (bezprawność i wina)")
    wzorcowa_subsumpcja: str = Field(description="Jak konkretny fakt z kazusu wypełnia tę przesłankę")


class KazusEgzaminacyjny(BaseModel):
    tytul: str = Field(description="Krótki tytuł kazusu, np. Wadliwy samochód i spóźniona apelacja")
    pion_prawa: str = Field(description="Np. Cywilny i Gospodarczy (KC + KPC)")
    poziom_trudnosci: Literal["student_podstawowy", "student_zaawansowany", "aplikacja_wstepny", "wlasny_z_uczelni"]
    stan_faktyczny: str = Field(description="Pełny opis stanu faktycznego zawierający daty i szczegóły")
    pytanie_do_studenta: str = Field(description="Główne polecenie egzaminacyjne dla studenta")
    klucz_podmioty: List[PodmiotKazusu]
    klucz_os_czasu: List[ZdarzenieOsiCzasu]
    klucz_problem_prawny: str = Field(description="Wzorcowe sformułowanie problemu prawnego")
    klucz_podstawy_lista: List[PodstawaPrawnaUstawy] = Field(
        description="Lista aktów prawnych i przypisanych do nich numerów artykułów"
    )
    klucz_przeslanki_i_subsumpcja: List[PrzeslankaPrzepisu]
    klucz_pulapki_formalne: List[str] = Field(
        description="Lista ukrytych pułapek (np. termin zawity, sobota/święto z art. 115 KC, forma ad solemnitatem)"
    )
    klucz_konkluzja: str = Field(description="Wzorcowe, jednoznaczne rozstrzygnięcie kazusu")

    @property
    def klucz_podstawy_prawne(self) -> Dict[str, List[str]]:
        """Zwraca słownik {skrot_ustawy: [numery_artykulow]} dla zachowania kompatybilności z exporter.py."""
        return {item.skrot_ustawy.upper(): item.numery_artykulow for item in self.klucz_podstawy_lista}


class WstepnaAnalizaWlasnegoKazusu(BaseModel):
    """Pomocniczy schemat do wstępnego wytypowania przepisów z tekstu wklejonego przez studenta."""
    tytul_roboczy: str = Field(description="Zwięzły tytuł nadany na podstawie treści zadania")
    pion_prawa: str = Field(description="Zidentyfikowana gałąź prawa, np. Cywilny (KC + KPC)")
    wyodrebniony_stan_faktyczny: str = Field(description="Czysty opis stanu faktycznego bez pytań końcowych")
    wyodrebnione_pytanie: str = Field(description="Pytanie lub polecenie wykładowcy wyodrębnione z tekstu")
    typowane_przepisy_lista: List[PodstawaPrawnaUstawy] = Field(
        description="Lista ustaw (KC, KPC, KK, KPK, KSH, KPA, KP, KRO) i artykułów do pobrania z ISAP"
    )


class OcenaKroku(BaseModel):
    zaliczony: bool = Field(description="True tylko wtedy, gdy student spełnił wymogi merytoryczne danego kroku")
    punkty_procent: int = Field(ge=0, le=100, description="Ocena punktowa tego etapu w skali 0-100")
    co_dobrze: List[str] = Field(description="Elementy poprawnie zidentyfikowane przez studenta")
    braki_i_bledy: List[str] = Field(description="Konkretne braki merytoryczne, pominięte przesłanki lub błędne kwalifikacje")
    wskazowka_naprowadzajaca: str = Field(
        description="Pytanie lub podpowiedź sokratejska (bez podawania gotowego rozwiązania!), jeśli krok nie jest zaliczony"
    )
    fiszka_powtorkowa: Optional[str] = Field(
        default=None,
        description="Wypełniana wyłącznie w Kroku 5: zwięzła fiszka Active Recall (Pytanie -> Odpowiedź z podstawą prawną)"
    )


# =====================================================================
# 2. GŁÓWNY SILNIK EWALUACJI (GEMINI 4 NEON + ISAP + TERMINY)
# =====================================================================

class KazusEvaluator:
    """
    Silnik generowania, parsowania własnych kazusów i weryfikacji rozwiązań oparty na:
    - modelu Gemini 4 Neon (thinking_level='high', temperature=1.0),
    - oficjalnej bazie ustaw Sejmu RP (ISAPClient),
    - deterministycznym kalkulatorze terminów (terminy.py).
    """

    def __init__(self, api_key: Optional[str] = None):
        klucz = api_key or os.environ.get("GEMINI_API_KEY")
        if not klucz:
            raise ValueError(
                "Brak klucza GEMINI_API_KEY. Ustaw zmienną środowiskową lub przekaż klucz do konstruktora."
            )
        self.client = genai.Client(api_key=klucz)
        self.model_id = "gemini-4-hydrogen"
        self.isap = ISAPClient()

    def _pobierz_kontekst_ustaw(self, mapa_artykulow: Dict[str, List[str]]) -> str:
        bloki = []
        for skrot_ustawy, numery in mapa_artykulow.items():
            kod = skrot_ustawy.upper().strip()
            if kod not in REJESTR_KODEKSOW:
                continue
            dane = self.isap.pobierz_konkretne_artykuly(kod, numery)
            naglowek = f"=== {dane['ustawa']} ({dane['publikator']}) | Status: {dane['status']} ==="
            tresci = [f"[{nr}] {tekst}" for nr, tekst in dane["przepisy"].items()]
            if dane["nieodnalezione"]:
                tresci.append(f"UWAGA: Nie odnaleziono w oficjalnym tekście ustawy artykułów: {dane['nieodnalezione']}")
            bloki.append(naglowek + "\n" + "\n".join(tresci))
        return "\n\n".join(bloki)

    def wygeneruj_kazus(
        self,
        pion_prawa: str = "Cywilny i Gospodarczy (KC + KPC)",
        poziom: Literal["student_podstawowy", "student_zaawansowany", "aplikacja_wstepny"] = "student_zaawansowany",
        przepisy_bazowe: Optional[Dict[str, List[str]]] = None,
    ) -> KazusEgzaminacyjny:
        if przepisy_bazowe is None:
            przepisy_bazowe = {
                "KC": ["111", "112", "115", "415", "471", "556", "560", "568"],
                "KPC": ["165", "369"],
            }

        oficjalne_przepisy = self._pobierz_kontekst_ustaw(przepisy_bazowe)

        prompt_systemowy = (
            "Jesteś wybitnym polskim egzaminatorem prawniczym (sędzią i wykładowcą uniwersyteckim). "
            "Twoim zadaniem jest stworzenie realistycznego kazusu prawniczego oraz precyzyjnego arkusza oceny (klucza). "
            "ZASADA BEZWZGLĘDNA: Opieraj się WYŁĄCZNIE na oficjalnych przepisach dostarczonych w kontekście. "
            "Nie zmyślaj numerów artykułów ani nieistniejących instytucji. Wpleć w kazus konkretne daty (rok 2026) "
            "oraz co najmniej jedną klasyczną pułapkę egzaminacyjną (np. koniec terminu w sobotę/święto z art. 115 KC, "
            "nadanie pisma kurierem prywatnym zamiast Pocztą Polską z art. 165 § 2 KPC lub zbieg roszczeń)."
        )

        prompt_uzytkownika = (
            f"Wygeneruj kazus dla pionu: {pion_prawa}, poziom trudności: {poziom}.\n\n"
            f"OFICJALNE PRZEPISY Z BAZY SEJMU (ELI/ISAP) DO WYKORZYSTANIA:\n{oficjalne_przepisy}"
        )

        response = self.client.models.generate_content(
            model=self.model_id,
            contents=prompt_uzytkownika,
            config=types.GenerateContentConfig(
                system_instruction=prompt_systemowy,
                temperature=1.0,
                thinking_config=types.ThinkingConfig(
                    thinking_level=types.ThinkingLevel.HIGH
                ),
                response_mime_type="application/json",
                response_schema=KazusEgzaminacyjny,
            ),
        )

        return KazusEgzaminacyjny.model_validate_json(response.text)

    def przygotuj_wlasny_kazus_z_uczelni(
        self,
        surowy_tekst_zadania: str,
        sugerowane_przepisy: Optional[Dict[str, List[str]]] = None,
    ) -> KazusEgzaminacyjny:
        dostepne_kody = ", ".join(REJESTR_KODEKSOW.keys())

        prompt_etap1 = (
            "Przeanalizuj wklejony przez studenta kazus z zajęć na uczelni. "
            "Rozdziel jego treść na czysty stan faktyczny oraz polecenie/pytanie wykładowcy (bez zmieniania faktów ani dat!). "
            f"Wytypuj wszystkie artykuły z kodeksów ({dostepne_kody}), które są niezbędne do rozwiązania tego kazusu "
            "(uwzględnij także przepisy ogólne, np. o terminach z art. 111-115 KC, wadach oświadczeń woli czy procedurze)."
        )

        resp_etap1 = self.client.models.generate_content(
            model=self.model_id,
            contents=f"TREŚĆ KAZUSU OD STUDENTA:\n{surowy_tekst_zadania}",
            config=types.GenerateContentConfig(
                system_instruction=prompt_etap1,
                temperature=1.0,
                thinking_config=types.ThinkingConfig(
                    thinking_level=types.ThinkingLevel.HIGH
                ),
                response_mime_type="application/json",
                response_schema=WstepnaAnalizaWlasnegoKazusu,
            ),
        )
        wstepna = WstepnaAnalizaWlasnegoKazusu.model_validate_json(resp_etap1.text)

        polaczone_przepisy: Dict[str, List[str]] = {}
        for item in wstepna.typowane_przepisy_lista:
            kod_up = item.skrot_ustawy.upper().strip()
            if kod_up in REJESTR_KODEKSOW:
                polaczone_przepisy[kod_up] = list(set(item.numery_artykulow))

        if sugerowane_przepisy:
            for kod, numery in sugerowane_przepisy.items():
                kod_up = kod.upper().strip()
                if kod_up in REJESTR_KODEKSOW:
                    istniejace = set(polaczone_przepisy.get(kod_up, []))
                    istniejace.update(numery)
                    polaczone_przepisy[kod_up] = list(istniejace)

        if not polaczone_przepisy:
            polaczone_przepisy = {"KC": ["5", "6", "58", "111", "115", "415", "471"]}

        oficjalne_przepisy = self._pobierz_kontekst_ustaw(polaczone_przepisy)

        prompt_etap2 = (
            "Jesteś polskim egzaminatorem prawniczym. Student wkleił własny kazus z uczelni. "
            "ZACHOWAJ DOKŁADNIE stan faktyczny i pytanie z zadania (nie dopisuj nowych faktów!). "
            "Na podstawie dostarczonych OFICJALNYCH PRZEPISÓW Z API SEJMU (ELI/ISAP) ułóż kompletny, "
            "szczegółowy klucz egzaminacyjny (podmioty, oś czasu, problem prawny, przesłanki do subsumpcji, "
            "pułapki formalne oraz wzorcową konkluzję), według którego student będzie oceniany w 5 krokach. "
            "Ustaw pole poziom_trudnosci na 'wlasny_z_uczelni'."
        )

        prompt_user_etap2 = (
            f"TYTUŁ ROBOCZY: {wstepna.tytul_roboczy}\n"
            f"PION PRAWA: {wstepna.pion_prawa}\n"
            f"STAN FAKTYCZNY (ORYGINAŁ):\n{wstepna.wyodrebniony_stan_faktyczny}\n\n"
            f"PYTANIE WYKŁADOWCY:\n{wstepna.wyodrebnione_pytanie}\n\n"
            f"OFICJALNE PRZEPISY Z BAZY SEJMU (ELI/ISAP):\n{oficjalne_przepisy}"
        )

        resp_etap2 = self.client.models.generate_content(
            model=self.model_id,
            contents=prompt_user_etap2,
            config=types.GenerateContentConfig(
                system_instruction=prompt_etap2,
                temperature=1.0,
                thinking_config=types.ThinkingConfig(
                    thinking_level=types.ThinkingLevel.HIGH
                ),
                response_mime_type="application/json",
                response_schema=KazusEgzaminacyjny,
            ),
        )

        return KazusEgzaminacyjny.model_validate_json(resp_etap2.text)

    def ocen_krok(
        self,
        kazus: KazusEgzaminacyjny,
        numer_kroku: Literal[1, 2, 3, 4, 5],
        odpowiedz_studenta: str,
        artykuly_studenta: Optional[Dict[str, List[str]]] = None,
        dane_terminu_do_sprawdzenia: Optional[dict] = None,
    ) -> OcenaKroku:
        opisy_krokow = {
            1: "KROK 1: Wizualizacja stanu faktycznego (identyfikacja wszystkich podmiotów, ich ról prawnych oraz chronologicznej osi dat).",
            2: "KROK 2: Sformułowanie problemu prawnego (precyzyjne określenie, kto, czego, od kogo i na jakiej podstawie żąda lub jakiej odpowiedzialności podlega).",
            3: "KROK 3: Podstawa prawna i rozbicie przepisu na przesłanki (Hipoteza – Dyspozycja – Wyjątki).",
            4: "KROK 4: Subsumpcja (szczegółowe dopasowanie konkretnych faktów z kazusu do każdej przesłanki przepisu z osobna; odrzucaj ogólniki!).",
            5: "KROK 5: Konkluzja (jednoznaczne rozstrzygnięcie prawne i odpowiedź na pytanie z kazusu).",
        }

        dodatkowy_kontekst_weryfikacji = ""

        if artykuly_studenta:
            dodatkowy_kontekst_weryfikacji += (
                "\nOFICJALNA TREŚĆ ARTYKUŁÓW WSKAZANYCH PRZEZ STUDENTA (Z API SEJMU ELI):\n"
                + self._pobierz_kontekst_ustaw(artykuly_studenta)
            )

        if dane_terminu_do_sprawdzenia:
            wynik_term = oblicz_termin(
                data_zdarzenia=date.fromisoformat(dane_terminu_do_sprawdzenia["data_zdarzenia"]),
                wartosc=dane_terminu_do_sprawdzenia["wartosc"],
                jednostka=dane_terminu_do_sprawdzenia["jednostka"],
                tryb=dane_terminu_do_sprawdzenia.get("tryb", "procesowy_kpc"),
            )
            dodatkowy_kontekst_weryfikacji += (
                f"\nDETERMINISTYCZNE WYLICZENIE Z MODUŁU terminy.py:\n"
                f"Podstawa: {wynik_term.podstawa_prawna}\n"
                f"Koniec surowy: {wynik_term.koniec_surowy.isoformat()}\n"
                f"Koniec ostateczny: {wynik_term.koniec_ostateczny.isoformat()}\n"
                f"Uzasadnienie: {wynik_term.uzasadnienie}\n"
            )

        prompt_systemowy = (
            "Jesteś surowym, ale sprawiedliwym egzaminatorem na aplikacji prawniczej. "
            "Oceniasz wyłącznie aktualny krok rozwiązania kazusu. "
            "REGUŁY OCENY:\n"
            "1. Jeśli student używa ogólników bez odniesienia do faktów z kazusu (szczególnie w Kroku 4 - Subsumpcja), "
            "ustaw zaliczony=False i wskaż w 'wskazowka_naprowadzajaca', którego faktu brakuje.\n"
            "2. Nie podawaj gotowego rozwiązania, jeśli zaliczony=False — zadaj pytanie naprowadzające.\n"
            "3. W Kroku 5 (gdy zaliczony=True) obowiązkowo wygeneruj pole 'fiszka_powtorkowa' podsumowującą główną regułę z kazusu."
        )

        prompt_uzytkownika = (
            f"OCENIANY ETAP: {opisy_krokow[numer_kroku]}\n\n"
            f"TREŚĆ KAZUSU:\n{kazus.stan_faktyczny}\nPytanie: {kazus.pytanie_do_studenta}\n\n"
            f"UKRYTY KLUCZ EGZAMINACYJNY (DO WGLĄDU TYLKO DLA CIEBIE):\n"
            f"{kazus.model_dump_json(indent=2)}\n\n"
            f"{dodatkowy_kontekst_weryfikacji}\n\n"
            f"ODPOWIEDŹ STUDENTA DO OCENY:\n{odpowiedz_studenta}"
        )

        response = self.client.models.generate_content(
            model=self.model_id,
            contents=prompt_uzytkownika,
            config=types.GenerateContentConfig(
                system_instruction=prompt_systemowy,
                temperature=1.0,
                thinking_config=types.ThinkingConfig(
                    thinking_level=types.ThinkingLevel.HIGH
                ),
                response_mime_type="application/json",
                response_schema=OcenaKroku,
            ),
        )

        return OcenaKroku.model_validate_json(response.text)