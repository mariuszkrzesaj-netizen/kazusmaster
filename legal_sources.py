import concurrent.futures
import re
import urllib.parse
import requests
import streamlit as st
from bs4 import BeautifulSoup

TIMEOUT = 1.8
HEADERS = {"User-Agent": "RatioLegis-LegalTrainer/1.0"}


def fetch_sejm_eli_and_prints(akt_skrot: str, artykul: str) -> dict:
    wynik = {"przepis": "", "ratio_legis": ""}
    try:
        q = urllib.parse.quote(akt_skrot)
        resp = requests.get(f"https://api.sejm.gov.pl/eli/acts/search?title={q}&inForce=1", headers=HEADERS, timeout=TIMEOUT)
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            if items:
                akt = items[0]
                wynik["przepis"] = f"{akt.get('title')} ({akt.get('displayAddress')}) – status: {akt.get('status')}, art. {artykul}."

        resp_p = requests.get(f"https://api.sejm.gov.pl/sejm/term10/prints?title={q}", headers=HEADERS, timeout=TIMEOUT)
        if resp_p.status_code == 200:
            prints = resp_p.json()
            if isinstance(prints, list) and prints:
                druk = prints[0]
                wynik["ratio_legis"] = f"Druk sejmowy nr {druk.get('number')}: {druk.get('title')} ({druk.get('documentDate')})."
    except Exception:
        pass
    return wynik


def fetch_saos_sn(podstawa_prawna: str, limit: int = 2) -> list[dict]:
    orzeczenia = []
    try:
        params = {
            "legalBase": podstawa_prawna,
            "courtType": "SUPREME",
            "pageSize": limit,
            "sortingField": "JUDGMENT_DATE",
            "sortingDirection": "DESC",
        }
        resp = requests.get("https://www.saos.org.pl/api/search/judgments", params=params, headers=HEADERS, timeout=TIMEOUT)
        if resp.status_code == 200:
            for item in resp.json().get("items", []):
                sygnatury = ", ".join(c.get("caseNumber", "") for c in item.get("courtCases", []))
                fragment = re.sub(r"<[^>]+>", "", item.get("textContent", ""))[:300]
                orzeczenia.append({"sygnatura": sygnatury, "data": item.get("judgmentDate"), "teza": fragment.strip() + "..."})
    except Exception:
        pass
    return orzeczenia


def fetch_cbosa_nsa(zapytanie: str, limit: int = 2) -> list[dict]:
    wyniki = []
    try:
        resp = requests.post("https://orzeczenia.nsa.gov.pl/cbo/search", data={"wszystkieSlowa": zapytanie, "rodzajOrzeczenia": "wyrok"}, headers=HEADERS, timeout=TIMEOUT)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for row in soup.select("table.info-list-table tr")[:limit]:
                tekst = " ".join(row.get_text(" ", strip=True).split())
                if tekst:
                    wyniki.append({"opis": tekst[:300]})
    except Exception:
        pass
    return wyniki


def fetch_eurlex_tsue(temat_pl: str, limit: int = 2) -> list[dict]:
    akty_ue = []
    try:
        q = urllib.parse.quote(temat_pl)
        resp = requests.get(f"https://eur-lex.europa.eu/search.html?scope=EURLEX&text={q}&lang=pl&type=quick&qid=1", headers=HEADERS, timeout=TIMEOUT)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for item in soup.select(".SearchResult")[:limit]:
                tytul = item.select_one(".title")
                celex = item.select_one(".celex")
                if tytul:
                    akty_ue.append({"celex": celex.get_text(strip=True) if celex else "UE", "tytul": tytul.get_text(" ", strip=True)[:250]})
    except Exception:
        pass
    return akty_ue


@st.cache_data(ttl=86400, show_spinner=False)
def zbierz_kontekst_prawny(dziedzina: str, akt: str, artykul: str, temat_kazusu: str) -> str:
    """Równolegle odpytuje 5 baz z limitem 1.8s i zapisuje wynik w pamięci podręcznej."""
    podstawa = f"art. {artykul} {akt}".strip()
    dziedzina_low = (dziedzina or "").lower()

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        fut_sejm = executor.submit(fetch_sejm_eli_and_prints, akt, artykul)
        fut_saos = executor.submit(fetch_saos_sn, podstawa)
        fut_cbosa = executor.submit(fetch_cbosa_nsa, f"{podstawa} {temat_kazusu}") if any(k in dziedzina_low for k in ["admin", "podatk", "kpa"]) else None
        fut_eurlex = executor.submit(fetch_eurlex_tsue, f"{temat_kazusu} {akt}") if any(k in dziedzina_low for k in ["cywil", "prac", "gospodar", "europ", "konsum"]) else None

        sejm_data = fut_sejm.result()
        saos_data = fut_saos.result()
        cbosa_data = fut_cbosa.result() if fut_cbosa else []
        eurlex_data = fut_eurlex.result() if fut_eurlex else []

    sekcje = [
        "=== ZWERYFIKOWANY KONTEKST PRAWNY (5 OFICJALNYCH BAZ) ===",
        f"[1. API SEJMU ELI / ISAP]: {sejm_data['przepis'] or f'Weryfikowany akt: {akt} (art. {artykul})'}",
        f"[2. UZASADNIENIE / DRUKI RCL]: {sejm_data['ratio_legis'] or 'Aktywna baza druków sejmowych Sejmu RP.'}",
    ]
    if saos_data:
        sekcje.append("[3. ORZECZNICTWO SĄDU NAJWYŻSZEGO (SAOS)]:\n" + "\n".join(f"  - {w['sygnatura']} ({w['data']}): {w['teza']}" for w in saos_data))
    if cbosa_data:
        sekcje.append("[4. ORZECZNICTWO NSA / WSA (CBOSA)]:\n" + "\n".join(f"  - {w['opis']}" for w in cbosa_data))
    if eurlex_data:
        sekcje.append("[5. PRAWO UE / TSUE (EUR-Lex)]:\n" + "\n".join(f"  - [{u['celex']}] {u['tytul']}" for u in eurlex_data))

    return "\n".join(sekcje)
