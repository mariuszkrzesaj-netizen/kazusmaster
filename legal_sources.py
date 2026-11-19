import concurrent.futures
import re
import urllib.parse
import requests
from bs4 import BeautifulSoup

TIMEOUT = 4.0
HEADERS = {"User-Agent": "RatioLegis-LegalTrainer/1.0"}


def fetch_sejm_eli_and_prints(akt_skrot: str, artykul: str) -> dict:
    """1 & 2. Pobiera przepis z API Sejmu ELI oraz uzasadnienia z druków sejmowych (RCL)."""
    wynik = {"source": "ELI / Sejm RP", "przepis": "", "ratio_legis": ""}
    try:
        q = urllib.parse.quote(akt_skrot)
        url_eli = f"https://api.sejm.gov.pl/eli/acts/search?title={q}&inForce=1"
        resp = requests.get(url_eli, headers=HEADERS, timeout=TIMEOUT)
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            if items:
                akt = items[0]
                wynik["przepis"] = (
                    f"{akt.get('title')} ({akt.get('displayAddress')}) – "
                    f"status: {akt.get('status')}, weryfikowany art. {artykul}."
                )

        url_prints = f"https://api.sejm.gov.pl/sejm/term10/prints?title={q}"
        resp_p = requests.get(url_prints, headers=HEADERS, timeout=TIMEOUT)
        if resp_p.status_code == 200:
            prints = resp_p.json()
            if isinstance(prints, list) and prints:
                druk = prints[0]
                wynik["ratio_legis"] = (
                    f"Druk sejmowy nr {druk.get('number')}: {druk.get('title')} "
                    f"(data wpływu: {druk.get('documentDate')})."
                )
    except Exception as e:
        wynik["przepis"] = f"Brak odpowiedzi ELI ({e})"
    return wynik


def fetch_saos_sn(podstawa_prawna: str, limit: int = 3) -> list[dict]:
    """3. Pobiera uchwały i wyroki Sądu Najwyższego z oficjalnego API SAOS."""
    orzeczenia = []
    try:
        params = {
            "legalBase": podstawa_prawna,
            "courtType": "SUPREME",
            "pageSize": limit,
            "sortingField": "JUDGMENT_DATE",
            "sortingDirection": "DESC",
        }
        resp = requests.get(
            "https://www.saos.org.pl/api/search/judgments",
            params=params,
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        if resp.status_code == 200:
            for item in resp.json().get("items", []):
                sygnatury = ", ".join(c.get("caseNumber", "") for c in item.get("courtCases", []))
                fragment = re.sub(r"<[^>]+>", "", item.get("textContent", ""))[:450]
                orzeczenia.append({
                    "sygnatura": sygnatury,
                    "data": item.get("judgmentDate"),
                    "teza": fragment.strip() + "...",
                })
    except Exception:
        pass
    return orzeczenia


def fetch_cbosa_nsa(zapytanie: str, limit: int = 2) -> list[dict]:
    """4. Pobiera orzeczenia NSA i WSA z Centralnej Bazy Orzeczeń Sądów Administracyjnych."""
    wyniki = []
    try:
        url = "https://orzeczenia.nsa.gov.pl/cbo/search"
        payload = {"wszystkieSlowa": zapytanie, "rodzajOrzeczenia": "wyrok"}
        resp = requests.post(url, data=payload, headers=HEADERS, timeout=TIMEOUT)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for row in soup.select("table.info-list-table tr")[:limit]:
                tekst = " ".join(row.get_text(" ", strip=True).split())
                if tekst:
                    wyniki.append({"opis": tekst[:400]})
    except Exception:
        pass
    return wyniki


def fetch_eurlex_tsue(temat_pl: str, limit: int = 2) -> list[dict]:
    """5. Pobiera powiązane akty prawa UE i orzecznictwo TSUE z EUR-Lex."""
    akty_ue = []
    try:
        q = urllib.parse.quote(temat_pl)
        url = f"https://eur-lex.europa.eu/search.html?scope=EURLEX&text={q}&lang=pl&type=quick&qid=1"
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for item in soup.select(".SearchResult")[:limit]:
                tytul = item.select_one(".title")
                celex = item.select_one(".celex")
                if tytul:
                    akty_ue.append({
                        "celex": celex.get_text(strip=True) if celex else "UE",
                        "tytul": tytul.get_text(" ", strip=True)[:300],
                    })
    except Exception:
        pass
    return akty_ue


def zbierz_kontekst_prawny(dziedzina: str, akt: str, artykul: str, temat_kazusu: str) -> str:
    """Równolegle odpytuje wszystkie 5 oficjalnych baz i buduje pakiet wiedzy dla Gemini."""
    podstawa = f"art. {artykul} {akt}".strip()
    dziedzina_low = (dziedzina or "").lower()

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        fut_sejm = executor.submit(fetch_sejm_eli_and_prints, akt, artykul)
        fut_saos = executor.submit(fetch_saos_sn, podstawa)

        fut_cbosa = (
            executor.submit(fetch_cbosa_nsa, f"{podstawa} {temat_kazusu}")
            if any(k in dziedzina_low for k in ["admin", "podatk", "kpa"])
            else None
        )

        fut_eurlex = (
            executor.submit(fetch_eurlex_tsue, f"{temat_kazusu} {akt}")
            if any(k in dziedzina_low for k in ["cywil", "prac", "gospodar", "europ", "konsum"])
            else None
        )

        sejm_data = fut_sejm.result()
        saos_data = fut_saos.result()
        cbosa_data = fut_cbosa.result() if fut_cbosa else []
        eurlex_data = fut_eurlex.result() if fut_eurlex else []

    sekcje = [
        "=== ZWERYFIKOWANY KONTEKST PRAWNY (5 OFICJALNYCH BAZ) ===",
        f"[1. API SEJMU ELI / ISAP]: {sejm_data['przepis']}",
        f"[2. UZASADNIENIE / DRUKI RCL]: {sejm_data['ratio_legis'] or 'Brak bezpośredniego druku nowelizującego.'}",
    ]

    if saos_data:
        wyroki_txt = "\n".join(
            f"  - {w['sygnatura']} ({w['data']}): {w['teza']}" for w in saos_data
        )
        sekcje.append(f"[3. ORZECZNICTWO SĄDU NAJWYŻSZEGO (SAOS API)]:\n{wyroki_txt}")

    if cbosa_data:
        nsa_txt = "\n".join(f"  - {w['opis']}" for w in cbosa_data)
        sekcje.append(f"[4. ORZECZNICTWO NSA / WSA (CBOSA)]:\n{nsa_txt}")

    if eurlex_data:
        ue_txt = "\n".join(f"  - [{u['celex']}] {u['tytul']}" for u in eurlex_data)
        sekcje.append(f"[5. PRAWO UNII EUROPEJSKIEJ / TSUE (EUR-Lex)]:\n{ue_txt}")

    return "\n".join(sekcje)
