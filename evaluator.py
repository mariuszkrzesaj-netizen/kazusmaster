import os
import time
import streamlit as st
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from legal_sources import zbierz_kontekst_prawny


class KazusEgzaminacyjny(BaseModel):
    tytul: str = Field(description="Tytuł kazusu")
    dziedzina: str = Field(description="Gałąź prawa, np. Prawo cywilne, Prawo karne, Prawo administracyjne")
    poziom: str = Field(default="Studia prawnicze", description="Poziom trudności")
    stan_faktyczny: str = Field(description="Szczegółowy opis stanu faktycznego z datami i zdarzeniami")
    pytanie_prawne: str = Field(description="Główne pytanie egzaminacyjne do rozstrzygnięcia")
    akt_glowny: str = Field(default="Kodeks cywilny", description="Główny akt prawny")
    artykul: str = Field(default="", description="Kluczowy artykuł lub artykuły")
    wzorcowa_os_czasu: str = Field(default="", description="Chronologiczne zestawienie faktów")
    wzorcowy_problem: str = Field(default="", description="Wzorcowy problem prawny (Issue)")
    wzorcowa_podstawa: str = Field(default="", description="Wzorcowa podstawa prawna (Rule)")
    wzorcowa_subsumcja: str = Field(default="", description="Wzorcowa subsumcja (Application)")
    wzorcowa_konkluzja: str = Field(default="", description="Wzorcowa konkluzja (Conclusion)")


class OcenaKroku(BaseModel):
    punkty: int = Field(ge=0, le=100, description="Liczba punktów od 0 do 100")
    zaliczony: bool = Field(description="Czy etap został zaliczony")
    komentarz: str = Field(description="Szczegółowa ocena merytoryczna egzaminatora")
    wskazowka: str = Field(default="", description="Wskazówka do poprawy lub sygnatury orzeczeń SN/NSA/TSUE")
    wzorcowa_odpowiedz: str = Field(default="", description="Wzorcowe sformułowanie tego etapu")


class KazusEvaluator:
    def __init__(self, api_key: str | None = None):
        if not api_key:
            try:
                if "GEMINI_API_KEY" in st.secrets:
                    api_key = st.secrets["GEMINI_API_KEY"]
            except Exception:
                pass
        if not api_key:
            api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("Brak klucza GEMINI_API_KEY w Streamlit Secrets.")

        self.client = genai.Client(api_key=api_key)
        # Lista modeli w kolejności priorytetu – przy 503 automatycznie przełącza na kolejny
        self.models_fallback = ["gemini-3.8-flash", "gemini-4-hydrogen"]

    def _call_with_fallback(self, prompt: str, schema) -> str:
        ostatni_blad = None
        for model_name in self.models_fallback:
            for proba in range(2):
                try:
                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=schema,
                            temperature=1.0,
                        ),
                    )
                    return response.text
                except Exception as e:
                    ostatni_blad = e
                    err_str = str(e)
                    if "503" in err_str or "UNAVAILABLE" in err_str or "429" in err_str:
                        time.sleep(1.2)
                        continue
                    break
        raise RuntimeError(f"Wszystkie modele AI są chwilowo przeciążone. Szczegóły: {ostatni_blad}")

    def generuj_kazus(self, dziedzina: str = "Prawo cywilne", temat: str = "", poziom: str = "Studia prawnicze") -> KazusEgzaminacyjny:
        kontekst_5_baz = zbierz_kontekst_prawny(
            dziedzina=dziedzina,
            akt=dziedzina,
            artykul="",
            temat_kazusu=temat or dziedzina,
        )

        prompt = f"""
Jesteś profesorem prawa tworzącym egzaminacyjny kazus prawniczy dla studentów wszystkich lat wydziałów prawa (projekt: Ratio Legis – patronat merytoryczny BSKK).
Dziedzina: {dziedzina}
Temat / zagadnienie: {temat or 'dowolne kluczowe zagadnienie egzaminacyjne'}
Poziom: {poziom}

Wykorzystaj poniższy zweryfikowany kontekst prawny z oficjalnych baz (ELI/Sejm, RCL, SAOS/SN, CBOSA/NSA, EUR-Lex):
{kontekst_5_baz}

Wygeneruj realistyczny, wielowątkowy kazus egzaminacyjny wraz ze wzorcowym rozwiązaniem w 5 krokach metody IRAC.
"""
        raw_json = self._call_with_fallback(prompt, KazusEgzaminacyjny)
        return KazusEgzaminacyjny.model_validate_json(raw_json)

    def ocen_krok(
        self,
        kazus: KazusEgzaminacyjny | dict,
        etap: str,
        odpowiedz_studenta: str,
        kontekst_dodatkowy: str = "",
    ) -> OcenaKroku:
        if isinstance(kazus, dict):
            dziedzina = kazus.get("dziedzina", "Prawo cywilne")
            tytul = kazus.get("tytul", "")
            stan_faktyczny = kazus.get("stan_faktyczny", kazus.get("tresc", ""))
            akt = kazus.get("akt_glowny", dziedzina)
            artykul = str(kazus.get("artykul", ""))
        else:
            dziedzina = kazus.dziedzina
            tytul = kazus.tytul
            stan_faktyczny = kazus.stan_faktyczny
            akt = kazus.akt_glowny
            artykul = kazus.artykul

        kontekst_5_baz = zbierz_kontekst_prawny(
            dziedzina=dziedzina,
            akt=akt,
            artykul=artykul,
            temat_kazusu=tytul,
        )

        prompt = f"""
Jesteś surowym, ale sprawiedliwym egzaminatorem akademickim na wydziale prawa (projekt: Ratio Legis – patronat merytoryczny BSKK).
Oceniasz etap rozwiązania kazusu: **{etap}**.

STAN FAKTYCZNY KAZUSU:
{stan_faktyczny}

{kontekst_5_baz}

{kontekst_dodatkowy}

ODPOWIEDŹ STUDENTA NA ETAP ({etap}):
{odpowiedz_studenta}

INSTRUKCJA OCENY:
1. Zweryfikuj poprawność merytoryczną w oparciu o przepisy (ELI/Sejm), uzasadnienia ustaw (RCL) oraz linię orzeczniczą SN (SAOS), NSA/WSA (CBOSA) i TSUE (EUR-Lex) widoczną powyżej.
2. Jeśli w kontekście znajdują się sygnatury wyroków SN, NSA lub aktów UE pasujące do kazusu, przywołaj je w komentarzu lub wskazówce.
3. Przyznaj uczciwą punktację (0–100 pkt) i podaj wzorcowe ujęcie tego etapu.
"""
        raw_json = self._call_with_fallback(prompt, OcenaKroku)
        return OcenaKroku.model_validate_json(raw_json)
