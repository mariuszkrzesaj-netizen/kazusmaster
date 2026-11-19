import os
from datetime import date
from typing import Dict, List
import streamlit as st

from isap_client import ISAPClient, REJESTR_KODEKSOW
from terminy import oblicz_termin
from evaluator import KazusEvaluator, KazusEgzaminacyjny, OcenaKroku
from database import KazusDatabase
from exporter import generuj_raport_docx


# =====================================================================
# 1. KONFIGURACJA STRONY I PIONÓW USTAWOWYCH (ZGODNIE Z PROTOKOŁEM)
# =====================================================================

st.set_page_config(
    page_title="KazusMaster – Trenażer Kazusów Prawniczych (ELI/ISAP + Gemini 4 Neon)",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

PIONY_USTAWOWE = {
    "I. Cywilny i Gospodarczy (KC + KPC)": {
        "opis": "Zobowiązania, rękojmia, delikty, wady oświadczeń woli, terminy procesowe i apelacja.",
        "domyslne_przepisy": {"KC": ["111", "112", "115", "415", "471", "556", "560", "568"], "KPC": ["165", "369"]},
    },
    "II. Karny (KK + KPK)": {
        "opis": "Znamiona czynu zabronionego, wina, kontratypy, przedawnienie i środki zaskarżenia w KPK.",
        "domyslne_przepisy": {"KK": ["1", "9", "25", "26", "278", "286"], "KPK": ["122", "123", "425", "445"]},
    },
    "III. Administracyjny (KPA)": {
        "opis": "Decyzja administracyjna, terminy załatwiania spraw, odwołanie i wznowienie postępowania.",
        "domyslne_przepisy": {"KPA": ["35", "57", "104", "127", "129", "145"]},
    },
    "IV. Pracy i Ubezpieczeń (KP + KPC)": {
        "opis": "Rozwiązanie umowy o pracę, odpowiedzialność porządkowa i materialna pracownika.",
        "domyslne_przepisy": {"KP": ["30", "52", "114", "115", "264"]},
    },
}

POZIOMY_TRUDNOSCI = {
    "Student – poziom podstawowy (II–III rok)": "student_podstawowy",
    "Student – poziom zaawansowany (IV–V rok)": "student_zaawansowany",
    "Symulator Egzaminu Wstępnego na Aplikację (Wykaz MS)": "aplikacja_wstepny",
}


# =====================================================================
# 2. INICJALIZACJA STANU SESJI I ZASOBÓW (ISAP + SQLITE)
# =====================================================================

def inicjalizuj_stan():
    domyslne = {
        "kazus": None,
        "aktualny_krok": 1,
        "oceny_krokow": {},         # {nr_kroku: OcenaKroku}
        "odpowiedzi_studenta": {},  # {nr_kroku: str}
        "kazus_zapisany_w_db": False,
    }
    for klucz, wartosc in domyslne.items():
        if klucz not in st.session_state:
            st.session_state[klucz] = wartosc


inicjalizuj_stan()


@st.cache_resource
def pobierz_klienta_isap() -> ISAPClient:
    return ISAPClient()


@st.cache_resource
def pobierz_baze_danych() -> KazusDatabase:
    return KazusDatabase()


def parsuj_liste_przepisow_z_tekstu(tekst: str) -> Dict[str, List[str]]:
    wynik: Dict[str, List[str]] = {}
    if not tekst.strip():
        return wynik

    bloki = tekst.split(";")
    for blok in bloki:
        if ":" not in blok:
            continue
        ustawa, numery_str = blok.split(":", 1)
        kod = ustawa.strip().upper()
        numery = [n.strip() for n in numery_str.split(",") if n.strip()]
        if kod in REJESTR_KODEKSOW and numery:
            wynik[kod] = numery
    return wynik


db = pobierz_baze_danych()
statystyki = db.pobierz_statystyki_ogolne()


# =====================================================================
# 3. PANEL BOCZNY (KONFIGURACJA, WYBÓR TRYBU, ISAP, KALKULATOR TERMINÓW)
# =====================================================================

with st.sidebar:
    st.title("⚖️ KazusMaster")
    st.caption("Oficjalne API Sejmu (ELI/ISAP) + Gemini 4 Neon")

    col_s1, col_s2 = st.columns(2)
    with col_s1:
        st.metric("Ukończone", statystyki["ukonczone_kazusy"])
    with col_s2:
        st.metric("Fiszki dziś", statystyki["fiszki_na_dzis"])

    api_key = ""
    try:
        if "GEMINI_API_KEY" in st.secrets:
            api_key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass

    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY", "")

    if api_key:
        st.success("🔒 Klucz API załadowany (ukryty)")
    else:
        api_key = st.text_input(
            "Klucz GEMINI_API_KEY",
            type="password",
            help="Wygeneruj klucz w Google AI Studio (aistudio.google.com).",
        )

    st.divider()

    st.subheader("1. Źródło kazusu")
    tryb_zrodla = st.radio(
        "Wybierz tryb pracy:",
        options=["🎲 Generator kazusów (ISAP)", "📝 Własny kazus z uczelni"],
        label_visibility="collapsed",
    )

    if tryb_zrodla == "🎲 Generator kazusów (ISAP)":
        wybrany_pion = st.selectbox("Sparowany pion prawa:", list(PIONY_USTAWOWE.keys()))
        st.caption(PIONY_USTAWOWE[wybrany_pion]["opis"])

        wybrany_poziom_label = st.selectbox("Poziom trudności:", list(POZIOMY_TRUDNOSCI.keys()), index=1)
        wybrany_poziom = POZIOMY_TRUDNOSCI[wybrany_poziom_label]

        if st.button("🎲 Generuj nowy kazus z ISAP", use_container_width=True, type="primary"):
            if not api_key:
                st.error("Podaj klucz GEMINI_API_KEY powyżej, aby uruchomić Gemini 4 Neon.")
            else:
                with st.spinner("Pobieranie oficjalnych ustaw z API Sejmu i układanie kazusu w Gemini 4 Neon..."):
                    try:
                        evaluator = KazusEvaluator(api_key=api_key)
                        nowy_kazus = evaluator.wygeneruj_kazus(
                            pion_prawa=wybrany_pion,
                            poziom=wybrany_poziom,
                            przepisy_bazowe=PIONY_USTAWOWE[wybrany_pion]["domyslne_przepisy"],
                        )
                        st.session_state["kazus"] = nowy_kazus
                        st.session_state["aktualny_krok"] = 1
                        st.session_state["oceny_krokow"] = {}
                        st.session_state["odpowiedzi_studenta"] = {}
                        st.session_state["kazus_zapisany_w_db"] = False
                        st.rerun()
                    except Exception as e:
                        st.error(f"Błąd podczas generowania kazusu: {e}")

    else:
        st.caption("Wklej treść kazusu z ćwiczeń lub egzaminu. Gemini 4 Neon pobierze przepisy z API Sejmu i ułoży klucz.")
        wlasny_tekst = st.text_area(
            "Treść zadania od wykładowcy:",
            height=160,
            placeholder="Wklej tutaj opis stanu faktycznego wraz z pytaniem końcowym...",
        )
        sugerowane_input = st.text_input(
            "Opcjonalnie: przepisy z sylabusa (np. KC: 556, 560):",
            placeholder="KC: 415; KPC: 165",
        )

        if st.button("📥 Przygotuj kazus do rozwiązania", use_container_width=True, type="primary"):
            if not api_key:
                st.error("Podaj klucz GEMINI_API_KEY powyżej.")
            elif len(wlasny_tekst.strip()) < 30:
                st.warning("Wklej pełną treść kazusu wraz z pytaniem (minimum kilka zdań).")
            else:
                with st.spinner("Analiza kazusu, pobieranie oficjalnych przepisów z API Sejmu (ELI) i układanie rubryki..."):
                    try:
                        evaluator = KazusEvaluator(api_key=api_key)
                        sugerowane_dict = parsuj_liste_przepisow_z_tekstu(sugerowane_input)
                        wlasny_kazus = evaluator.przygotuj_wlasny_kazus_z_uczelni(
                            surowy_tekst_zadania=wlasny_tekst,
                            sugerowane_przepisy=sugerowane_dict if sugerowane_dict else None,
                        )
                        st.session_state["kazus"] = wlasny_kazus
                        st.session_state["aktualny_krok"] = 1
                        st.session_state["oceny_krokow"] = {}
                        st.session_state["odpowiedzi_studenta"] = {}
                        st.session_state["kazus_zapisany_w_db"] = False
                        st.rerun()
                    except Exception as e:
                        st.error(f"Błąd przetwarzania własnego kazusu: {e}")

    st.divider()

    with st.expander("📖 Podgląd przepisów (API Sejmu ELI)", expanded=False):
        kodeks_podglad = st.selectbox("Wybierz akt prawny:", list(REJESTR_KODEKSOW.keys()))
        artykuly_input = st.text_input("Numery artykułów (po przecinku):", value="115, 415, 556")
        if st.button("Pobierz tekst jednolity", use_container_width=True):
            isap = pobierz_klienta_isap()
            lista_art = [a.strip() for a in artykuly_input.split(",") if a.strip()]
            with st.spinner("Łączenie z api.sejm.gov.pl/eli..."):
                try:
                    dane_art = isap.pobierz_konkretne_artykuly(kodeks_podglad, lista_art)
                    st.caption(f"Źródło: {dane_art['publikator']} | Status: {dane_art['status']}")
                    for nr, tresc in dane_art["przepisy"].items():
                        st.info(tresc)
                    if dane_art["nieodnalezione"]:
                        st.warning(f"Nie odnaleziono w ustawie: {', '.join(dane_art['nieodnalezione'])}")
                except Exception as e:
                    st.error(f"Błąd połączenia z API Sejmu: {e}")

    with st.expander("📅 Kalkulator terminów (KC / KPC)", expanded=False):
        data_start = st.date_input("Data zdarzenia początkowego:", value=date(2026, 4, 17))
        col_w, col_j = st.columns(2)
        with col_w:
            wartosc_term = st.number_input("Liczba:", min_value=1, max_value=365, value=14)
        with col_j:
            jednostka_term = st.selectbox("Jednostka:", ["dni", "tygodnie", "miesiace", "lata"])

        tryb_term = st.radio(
            "Reżim prawny:",
            options=["procesowy_kpc", "materialny_kc"],
            format_func=lambda x: "Procesowy (art. 165 KPC)" if x == "procesowy_kpc" else "Materialny (art. 111–115 KC)",
        )

        if st.button("Oblicz koniec terminu", use_container_width=True):
            wynik_t = oblicz_termin(data_start, int(wartosc_term), jednostka_term, tryb=tryb_term)
            st.success(f"**Ostateczny termin:** {wynik_t.koniec_ostateczny.isoformat()}")
            st.caption(f"Podstawa: {wynik_t.podstawa_prawna}")
            st.write(wynik_t.uzasadnienie)


# =====================================================================
# 4. ZAKŁADKI GŁÓWNE APLIKACJI (TRENAŻER / FISZKI / HISTORIA SQLITE)
# =====================================================================

tab_trenazer, tab_fiszki, tab_historia = st.tabs(
    [
        "⚖️ Rozwiązywanie kazusu (5 kroków)",
        f"🧠 Baza fiszek Active Recall ({statystyki['fiszki_na_dzis']} na dziś)",
        f"📊 Historia i statystyki ({statystyki['ukonczone_kazusy']})",
    ]
)

with tab_trenazer:
    kazus: KazusEgzaminacyjny = st.session_state["kazus"]

    if kazus is None:
        st.header("⚖️ Trenażer Rozwiązywania Kazusów Prawniczych")
        st.markdown(
            """
            Aplikacja wymusza aktywną pracę nad kazusem według **5-etapowego algorytmu egzaminacyjnego (metoda IRAC)**,
            eliminując bierne czytanie i zgadywanie przepisów:

            1. **Krok 1: Wizualizacja stanu faktycznego** – identyfikacja podmiotów, ról oraz chronologicznej osi dat.
            2. **Krok 2: Sformułowanie problemu prawnego** – precyzyjne określenie roszczenia (*kto, czego i od kogo żąda*).
            3. **Krok 3: Podstawa prawna i rozbicie na przesłanki** – weryfikacja artykułów w oficjalnej bazie Sejmu (ELI/ISAP) oraz rozpisanie hipotezy, dyspozycji i wyjątków.
            4. **Krok 4: Subsumpcja** – dopasowanie każdego faktu z kazusu do poszczególnych przesłanek przepisu (system odrzuca ogólniki).
            5. **Krok 5: Konkluzja, fiszka Active Recall i eksport DOCX** – jednoznaczne rozstrzygnięcie, zapis karty powtórkowej do SQLite oraz pobranie opracowania w formacie Word (.docx).

            👈 **Wybierz w panelu bocznym „Generator kazusów (ISAP)” lub wklej „Własny kazus z uczelni”, aby rozpocząć.**
            """
        )
    else:
        st.subheader(f"📄 Kazus: {kazus.tytul}")
        col_meta1, col_meta2 = st.columns([2, 1])
        with col_meta1:
            st.caption(f"**Pion:** {kazus.pion_prawa}")
        with col_meta2:
            etykieta_poziomu = (
                "📝 Własny kazus z uczelni"
                if kazus.poziom_trudnosci == "wlasny_z_uczelni"
                else f"🎯 {kazus.poziom_trudnosci}"
            )
            st.caption(f"**Tryb:** {etykieta_poziomu}")

        with st.container(border=True):
            st.markdown("**Stan faktyczny:**")
            st.write(kazus.stan_faktyczny)
            st.info(f"**Polecenie egzaminacyjne:** {kazus.pytanie_do_studenta}")

        NAZWY_KROKOW = {
            1: "1. Oś czasu i podmioty",
            2: "2. Problem prawny",
            3: "3. Podstawa prawna i przesłanki",
            4: "4. Subsumpcja",
            5: "5. Konkluzja i podsumowanie",
        }

        aktualny_krok = st.session_state["aktualny_krok"]
        oceny_krokow: Dict[int, OcenaKroku] = st.session_state["oceny_krokow"]

        st.progress(len(oceny_krokow) / 5.0, text=f"Postęp rozwiązania: {len(oceny_krokow)} z 5 etapów zaliczonych")

        cols_steps = st.columns(5)
        for nr in range(1, 6):
            with cols_steps[nr - 1]:
                if nr in oceny_krokow and oceny_krokow[nr].zaliczony:
                    st.success(f"✅ {NAZWY_KROKOW[nr]}")
                elif nr == aktualny_krok:
                    st.info(f"▶️ {NAZWY_KROKOW[nr]}")
                else:
                    st.markdown(f"🔒 {NAZWY_KROKOW[nr]}")

        st.divider()
        st.markdown(f"### Etap {aktualny_krok}: {NAZWY_KROKOW[aktualny_krok]}")

        instrukcje_etapow = {
            1: "Wypisz wszystkie podmioty występujące w kazusie wraz z ich rolami prawnymi (np. Kupujący, Sprzedawca, Konsument) oraz ułóż chronologiczną oś wszystkich dat wraz z wyliczeniem terminów.",
            2: "Sformułuj główne pytanie prawne (problem): kto, czego, od kogo i z jakiego tytułu prawnego się domaga (lub jakiej odpowiedzialności podlega).",
            3: "Podaj dokładne numery artykułów w polu poniżej, a następnie rozbij wybrany przepis na przesłanki ustawowe (Hipoteza – Dyspozycja – Wyjątki).",
            4: "Przeprowadź pełną subsumpcję: dopasuj konkretne fakty z opisu stanu faktycznego do każdej z przesłanek z osobna. Unikaj ogólników!",
            5: "Sformułuj ostateczną, kategoryczną konkluzję odpowiadającą na pytanie egzaminacyjne z kazusu.",
        }

        st.write(instrukcje_etapow[aktualny_krok])

        artykuly_studenta_dict: Dict[str, List[str]] = {}
        if aktualny_krok in (3, 4):
            wpis_artykulow = st.text_input(
                "Powoływane przepisy (format: SKRÓT: nr1, nr2; np. KC: 556, 560; KPC: 165):",
                value=st.session_state.get("ostatnie_artykuly_input", ""),
                placeholder="KC: 415, 361; KPC: 165",
            )
            st.session_state["ostatnie_artykuly_input"] = wpis_artykulow
            artykuly_studenta_dict = parsuj_liste_przepisow_z_tekstu(wpis_artykulow)

            if artykuly_studenta_dict:
                with st.expander("🔍 Zweryfikowane brzmienie powołanych przepisów z bazy Sejmu (ELI)", expanded=True):
                    isap = pobierz_klienta_isap()
                    for kod, numery in artykuly_studenta_dict.items():
                        dane = isap.pobierz_konkretne_artykuly(kod, numery)
                        for nr, tresc in dane["przepisy"].items():
                            st.markdown(f"**{kod} art. {nr}:** {tresc}")
                        if dane["nieodnalezione"]:
                            st.error(f"BŁĄD FORMALNY: W ustawie {kod} nie istnieją artykuły: {', '.join(dane['nieodnalezione'])}")

        poprzednia_odp = st.session_state["odpowiedzi_studenta"].get(aktualny_krok, "")
        odpowiedz_studenta = st.text_area(
            "Twoja analiza dla tego etapu:",
            value=poprzednia_odp,
            height=180,
            key=f"pole_odp_krok_{aktualny_krok}",
        )

        col_btn1, col_btn2 = st.columns([1, 2])
        with col_btn1:
            sprawdz_clicked = st.button("✅ Sprawdź ten etap (Gemini 4 Neon)", type="primary", use_container_width=True)

        if sprawdz_clicked:
            if not api_key:
                st.error("Wprowadź klucz GEMINI_API_KEY w panelu bocznym.")
            elif len(odpowiedz_studenta.strip()) < 15:
                st.warning("Wpisz pełniejszą odpowiedź merytoryczną przed weryfikacją.")
            elif aktualny_krok == 3 and not artykuly_studenta_dict:
                st.error("W Kroku 3 musisz wskazać co najmniej jeden przepis w formacie np. 'KC: 415'.")
            else:
                st.session_state["odpowiedzi_studenta"][aktualny_krok] = odpowiedz_studenta
                with st.spinner("Gemini 4 Neon analizuje Twoją odpowiedź względem przepisów ISAP i klucza..."):
                    try:
                        evaluator = KazusEvaluator(api_key=api_key)
                        wynik_oceny = evaluator.ocen_krok(
                            kazus=kazus,
                            numer_kroku=aktualny_krok,
                            odpowiedz_studenta=odpowiedz_studenta,
                            artykuly_studenta=artykuly_studenta_dict if artykuly_studenta_dict else None,
                        )
                        st.session_state["oceny_krokow"][aktualny_krok] = wynik_oceny
                        st.rerun()
                    except Exception as e:
                        st.error(f"Błąd weryfikacji: {e}")

        if aktualny_krok in oceny_krokow:
            ocena = oceny_krokow[aktualny_krok]
            st.divider()

            if ocena.zaliczony:
                st.success(f"🎉 Etap {aktualny_krok} ZALICZONY! Wynik: **{ocena.punkty_procent}%**")
            else:
                st.error(f"❌ Etap {aktualny_krok} wymaga poprawy (Wynik: **{ocena.punkty_procent}%**)")

            col_ok, col_err = st.columns(2)
            with col_ok:
                st.markdown("**✔️ Poprawnie ujęte elementy:**")
                for item in ocena.co_dobrze:
                    st.markdown(f"- {item}")
            with col_err:
                st.markdown("**⚠️ Braki i błędy do uzupełnienia:**")
                if ocena.braki_i_bledy:
                    for item in ocena.braki_i_bledy:
                        st.markdown(f"- {item}")
                else:
                    st.markdown("- Brak istotnych uchybień.")

            if not ocena.zaliczony:
                st.warning(f"💡 **Wskazówka egzaminatora:** {ocena.wskazowka_naprowadzajaca}")
            else:
                if aktualny_krok < 5:
                    if st.button(f"➡️ Przejdź do Etapu {aktualny_krok + 1}", type="primary"):
                        st.session_state["aktualny_krok"] = aktualny_krok + 1
                        st.rerun()
                else:
                    if not st.session_state["kazus_zapisany_w_db"]:
                        db.zapisz_ukonczony_kazus(kazus, oceny_krokow)
                        st.session_state["kazus_zapisany_w_db"] = True

                    st.balloons()
                    srednia = sum(o.punkty_procent for o in oceny_krokow.values()) // 5
                    st.subheader(f"🏆 Kazus ukończony i zapisany w bazie SQLite! Średni wynik: {srednia}%")

                    if ocena.fiszka_powtorkowa:
                        st.info(f"🧠 **Fiszka Active Recall zapisana do powtórek:**\n\n{ocena.fiszka_powtorkowa}")

                    st.divider()
                    st.markdown("### 📥 Eksport pełnego opracowania")
                    st.caption(
                        "Pobierz sformatowany dokument Word (.docx) zawierający stan faktyczny, "
                        "Twoje rozwiązanie z wszystkich 5 etapów, oficjalne brzmienie przepisów z API Sejmu (ELI/ISAP) "
                        "oraz wzorcowy klucz egzaminacyjny."
                    )
                    plik_docx_bajty = generuj_raport_docx(
                        kazus=kazus,
                        odpowiedzi_studenta=st.session_state["odpowiedzi_studenta"],
                        oceny_krokow=oceny_krokow,
                        isap_client=pobierz_klienta_isap(),
                        dodatkowe_przepisy_studenta=parsuj_liste_przepisow_z_tekstu(
                            st.session_state.get("ostatnie_artykuly_input", "")
                        ),
                    )
                    bezpieczna_nazwa = "".join(
                        c if c.isalnum() or c in ("-", "_") else "_" for c in kazus.tytul[:40]
                    )
                    st.download_button(
                        label="📄 Pobierz pełne rozwiązanie kazusu (.DOCX)",
                        data=plik_docx_bajty,
                        file_name=f"KazusMaster_{bezpieczna_nazwa}.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        type="primary",
                        use_container_width=True,
                    )

                    with st.expander("🔑 Zobacz wzorcowy klucz egzaminacyjny i ukryte pułapki", expanded=True):
                        st.markdown(f"**Wzorcowy problem prawny:** {kazus.klucz_problem_prawny}")
                        st.markdown("**Pułapki egzaminacyjne w tym kazusie:**")
                        for p in kazus.klucz_pulapki_formalne:
                            st.markdown(f"- {p}")
                        st.markdown(f"**Wzorcowa konkluzja:** {kazus.klucz_konkluzja}")

with tab_fiszki:
    st.header("🧠 Fiszki Active Recall (Powtórki rozłożone w czasie)")
    pokaz_wszystkie = st.checkbox("Pokaż również fiszki zaplanowane na przyszłe dni", value=False)
    lista_fiszek = db.pobierz_fiszki_do_powtorki(tylko_na_dzis=not pokaz_wszystkie)

    if not lista_fiszek:
        st.info("Brak fiszek oczekujących na powtórkę. Ukończ kazus (Krok 5), aby automatycznie wygenerować nowe karty.")
    else:
        for fiszka in lista_fiszek:
            with st.container(border=True):
                col_f1, col_f2 = st.columns([3, 1])
                with col_f1:
                    st.caption(
                        f"Pion: **{fiszka['pion_prawa']}** | Poziom opanowania: **{fiszka['poziom_opanowania']}/5** | "
                        f"Następna powtórka: **{fiszka['nastepna_powtorka']}**"
                    )
                    st.markdown(fiszka["tresc_fiszki"])
                with col_f2:
                    if st.button("👍 Pamiętam", key=f"ok_fiszka_{fiszka['id']}", use_container_width=True):
                        db.aktualizuj_powtorke_fiszki(fiszka["id"], zapamietano=True)
                        st.rerun()
                    if st.button("🔁 Powtórz jutro", key=f"err_fiszka_{fiszka['id']}", use_container_width=True):
                        db.aktualizuj_powtorke_fiszki(fiszka["id"], zapamietano=False)
                        st.rerun()

with tab_historia:
    st.header("📊 Historia ukończonych kazusów i statystyki")

    m1, m2, m3 = st.columns(3)
    m1.metric("Ukończone kazusy", statystyki["ukonczone_kazusy"])
    m2.metric("Średni wynik globalny", f"{statystyki['sredni_wynik_globalny']}%")
    m3.metric("Zgromadzone fiszki", statystyki["wszystkie_fiszki"])

    st.divider()
    historia = db.pobierz_historie_kazusow(limit=30)

    if not historia:
        st.info("Twoja historia jest jeszcze pusta. Rozwiąż pierwszy kazus w zakładce obok.")
    else:
        for wpis in historia:
            with st.expander(
                f"#{wpis['id']} | {wpis['tytul']} — Wynik: {wpis['sredni_wynik']}% ({wpis['data_ukonczenia']})"
            ):
                st.caption(f"Pion: {wpis['pion_prawa']} | Tryb: {wpis['poziom_trudnosci']}")
                oceny_zapisane = wpis["oceny"]
                cols_h = st.columns(5)
                for nr in range(1, 6):
                    dane_kroku = oceny_zapisane.get(str(nr), {})
                    pkt = dane_kroku.get("punkty_procent", 0)
                    cols_h[nr - 1].metric(f"Etap {nr}", f"{pkt}%")
