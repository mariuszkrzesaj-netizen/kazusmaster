import json
import os
import re
import time
import streamlit as st
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from google.oauth2 import service_account
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


def _wyciagnij_json(tekst: str) -> dict:
    """Bezpiecznie parsuje odpowiedź JSON nawet jeśli model doda znaki markdown."""
    czysty = re.sub(r"^```(?:json)?\s*|\s*```$", "", tekst.strip(), flags=re.IGNORECASE)
    return json.loads(czysty)


class KazusEvaluator:
    def __init__(self, api_key: str | None = None):
        self.client = None

        # 1. Priorytet: Konto usługi Google Cloud Vertex AI (projekt new-its-system)
        try:
            if "gcp_service_account" in st.secrets:
                creds_info = dict(st.secrets["gcp_service_account"])
                if "private_key" in creds_info and isinstance(creds_info["private_key"], str):
                    creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
                credentials = service_account.Credentials.from_service_account_info(
                    creds_info,
                    scopes=["https://www.googleapis.com/auth/cloud-platform"],
                )
                self.client = genai.Client(
                    vertexai=True,
                    project=creds_info.get("project_id", "new-its-system"),
                    location="global",
                    credentials=credentials,
                )
        except Exception as e:
            raise ValueError(f"Błąd autoryzacji Vertex AI (gcp_service_account): {e}")

        # 2. Tryb zapasowy: standardowy klucz GEMINI_API_KEY
        if not self.client:
            if not api_key:
                try:
                    if "GEMINI_API_KEY" in st.secrets:
                        api_key = st.secrets["GEMINI_API_KEY"]
                except Exception:
                    pass
            if not api_key:
                api_key = os.environ.get("GEMINI_API_KEY")
            if api_key:
                self.client = genai.Client(api_key=api_key)

        if not self.client:
            raise ValueError("Brak sekcji [gcp_service_account] ani GEMINI_API_KEY w Streamlit Secrets.")

        # Modele aktywne w projekcie new-its-system (endpoint global)
        self.models_fallback = [
            "gemini-4-neon",
            "gemini-4-carbon",
            "gemini-2.5-flash",
        ]

    def _call_with_fallback(self, prompt: str) -> str:
        ostatni_blad = None
        for model_name in self.models_fallback:
            for _ in range(2):
                try:
                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            temperature=0.7,
                        ),
                    )
                    if response and response.text:
                        return response.text
                except Exception as e:
                    ostatni_blad = e
                    err_str = str(e)
                    if "404" in err_str or "NOT_FOUND" in err_str:
                        break
                    time.sleep(0.8)
                    continue
        raise RuntimeError(f"Błąd połączenia z Vertex AI. Szczegóły: {ostatni_blad}")

    def generuj_kazus(self, dziedzina: str = "Prawo cywilne", temat: str = "", poziom: str = "Studia prawnicze") -> KazusEgzaminacyjny:
        prompt = f"""
Jesteś profesorem prawa tworzącym kazus prawniczy dla studentów wydziałów prawa (projekt: Ratio Legis – patronat merytoryczny BSKK).
Dziedzina: {dziedzina}
Temat / zagadnienie: {temat or 'dowolne kluczowe zagadnienie egzaminacyjne'}
Poziom: {poziom}

Zwróć odpowiedź WYŁĄCZNIE jako poprawny obiekt JSON o dokładnie następujących kluczach (wszystkie wartości jako tekst):
{{
  "tytul": "krótki tytuł kazusu",
  "dziedzina": "{dziedzina}",
  "poziom": "{poziom}",
  "stan_faktyczny": "szczegółowy, realistyczny opis stanu faktycznego z datami i imionami",
  "pytanie_prawne": "główne pytanie egzaminacyjne do rozstrzygnięcia",
  "akt_glowny": "nazwa głównego kodeksu lub ustawy, np. Kodeks cywilny",
  "artykul": "numer głównego artykułu, np. 415",
  "wzorcowa_os_czasu": "chronologiczne zestawienie dat i faktów",
  "wzorcowy_problem": "wzorcowy problem prawny (Issue)",
  "wzorcowa_podstawa": "wzorcowa podstawa prawna z uzasadnieniem (Rule)",
  "wzorcowa_subsumcja": "wzorcowa subsumcja krok po kroku (Application)",
  "wzorcowa_konkluzja": "wzorcowa konkluzja (Conclusion)"
}}
"""
        raw_json = self._call_with_fallback(prompt)
        data = _wyciagnij_json(raw_json)
        return KazusEgzaminacyjny.model_validate(data)

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
Jesteś egzaminatorem akademickim na wydziale prawa (projekt: Ratio Legis – patronat merytoryczny BSKK).
Oceniasz etap rozwiązania kazusu: **{etap}**.

STAN FAKTYCZNY KAZUSU:
{stan_faktyczny}

{kontekst_5_baz}

{kontekst_dodatkowy}

ODPOWIEDŹ STUDENTA NA ETAP ({etap}):
{odpowiedz_studenta}

Zweryfikuj poprawność merytoryczną na podstawie przepisów (ELI/Sejm), uzasadnień (RCL) oraz orzecznictwa SN (SAOS), NSA/WSA (CBOSA) i TSUE (EUR-Lex) widocznego powyżej.
Zwróć odpowiedź WYŁĄCZNIE jako poprawny obiekt JSON o dokładnie następujących kluczach:
{{
  "punkty": 85,
  "zaliczony": true,
  "komentarz": "szczegółowa ocena merytoryczna egzaminatora",
  "wskazowka": "wskazówka do poprawy lub konkretne sygnatury wyroków SN/NSA/TSUE z kontekstu",
  "wzorcowa_odpowiedz": "wzorcowe sformułowanie tego etapu"
}}
"""
        raw_json = self._call_with_fallback(prompt)
        data = _wyciagnij_json(raw_json)
        return OcenaKroku.model_validate(data)
