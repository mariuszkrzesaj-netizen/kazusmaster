import os
import streamlit as st
from google import genai
from google.genai import types
from legal_sources import zbierz_kontekst_prawny


def get_gemini_client() -> genai.Client:
    """Inicjalizuje klienta Gemini z Streamlit Secrets lub zmiennej środowiskowej."""
    api_key = None
    try:
        if "GEMINI_API_KEY" in st.secrets:
            api_key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass

    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        raise ValueError("Brak klucza GEMINI_API_KEY w Streamlit Secrets lub zmiennych środowiskowych.")

    return genai.Client(api_key=api_key)


def ocen_rozwiazanie_irac(
    kazus: dict,
    odpowiedz_studenta: dict,
) -> dict:
    """
    Ocenia 5-etapowe rozwiązanie kazusu (Oś czasu -> Issue -> Rule -> Application -> Conclusion)
    w oparciu o dane pobrane w czasie rzeczywistym z ELI, RCL, SAOS (SN), CBOSA (NSA) i EUR-Lex.
    """
    client = get_gemini_client()

    dziedzina = kazus.get("dziedzina", "Prawo cywilne")
    akt_glowny = kazus.get("akt_glowny", "Kodeks cywilny")
    artykul = str(kazus.get("artykul", ""))
    tytul_kazusu = kazus.get("tytul", "")
    tresc_kazusu = kazus.get("tresc", "")

    # Równoległe pobranie materiału z 5 baz prawnych
    kontekst_5_baz = zbierz_kontekst_prawny(
        dziedzina=dziedzina,
        akt=akt_glowny,
        artykul=artykul,
        temat_kazusu=tytul_kazusu,
    )

    prompt = f"""
Jesteś egzaminatorem akademickim na wydziale prawa (projekt: Ratio Legis – patronat merytoryczny BSKK).
Oceń rozwiązanie kazusu przygotowane przez studenta metodą IRAC (z uwzględnieniem osi czasu).

DANE KAZUSU:
- Dziedzina: {dziedzina}
- Tytuł: {tytul_kazusu}
- Stan faktyczny: {tresc_kazusu}

{kontekst_5_baz}

ODPOWIEDŹ STUDENTA:
1. Oś czasu i fakty prawnie relewantne: {odpowiedz_studenta.get('os_czasu', '')}
2. Problem prawny (Issue): {odpowiedz_studenta.get('issue', '')}
3. Podstawa prawna (Rule): {odpowiedz_studenta.get('rule', '')}
4. Subsumcja (Application): {odpowiedz_studenta.get('application', '')}
5. Konkluzja (Conclusion): {odpowiedz_studenta.get('conclusion', '')}

INSTRUKCJE OCENY:
1. Zweryfikuj poprawność podstawy prawnej oraz rozumienie celu regulacji (ratio legis) na podstawie danych z API Sejmu ELI i druków RCL.
2. Sprawdź, czy konkluzja i subsumcja studenta są zgodne z linią orzeczniczą Sądu Najwyższego (SAOS), NSA/WSA (CBOSA) oraz prawem UE/TSUE (EUR-Lex) widoczną w kontekście powyżej.
3. W informacji zwrotnej przywołaj konkretne sygnatury wyroków SN/NSA lub akty UE z powyższego kontekstu, aby pokazać studentowi wzorcowe uzasadnienie egzaminacyjne.
4. Przyznaj punktację w skali 0–100 pkt, wskaż mocne strony, błędy merytoryczne oraz napisz wzorcową subsumcję.
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.2,
        ),
    )

    return {
        "ocena_tekst": response.text,
        "zrodla_uzyte": kontekst_5_baz,
    }
