import json
import streamlit as st
from evaluator import KazusEvaluator, KazusEgzaminacyjny, OcenaKroku
from legal_sources import zbierz_kontekst_prawny

st.set_page_config(
    page_title="Ratio Legis – Kazusy Prawne | BSKK",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- STYLIZACJA AKADEMICKA (GRANAT & ZŁOTO BSKK) ---
st.markdown(
    """
    <style>
    .main-header {
        background: linear-gradient(135deg, #0b1d3a 0%, #163360 100%);
        padding: 1.6rem 2rem;
        border-radius: 12px;
        border-left: 6px solid #d4af37;
        color: #ffffff;
        margin-bottom: 1.2rem;
    }
    .main-header h1 {
        color: #ffffff;
        margin: 0 0 0.3rem 0;
        font-size: 2rem;
    }
    .main-header p {
        color: #e2e8f0;
        margin: 0;
        font-size: 1.05rem;
    }
    .patronat-badge {
        display: inline-block;
        background-color: rgba(212, 175, 55, 0.18);
        border: 1px solid #d4af37;
        color: #f6e08b;
        padding: 0.25rem 0.75rem;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
        margin-top: 0.7rem;
    }
    .db-card {
        background-color: #f8fafc;
        border: 1px solid #cbd5e1;
        border-top: 3px solid #163360;
        border-radius: 8px;
        padding: 0.85rem;
        height: 100%;
    }
    .db-card h4 {
        margin: 0 0 0.35rem 0;
        font-size: 0.95rem;
        color: #0b1d3a;
    }
    .db-card p {
        margin: 0;
        font-size: 0.82rem;
        color: #475569;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- NAGŁÓWEK GŁÓWNY ---
st.markdown(
    """
    <div class="main-header">
        <h1>⚖️ Ratio Legis</h1>
        <p>Kazusy prawne dla studentów każdego roku wydziałów prawnych</p>
        <div class="patronat-badge">Patronat merytoryczny: BSKK Kancelaria (Wrocław) • Metoda IRAC + AI</div>
    </div>
    """,
    unsafe_allow_html=True,
)

# --- WIDOCZNY PASEK 5 OFICJALNYCH BAZ PRAWNYCH ---
with st.expander("📚 Zintegrowane oficjalne bazy aktów prawnych i orzecznictwa (5 źródeł aktywnych)", expanded=True):
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.markdown(
            """
            <div class="db-card">
                <h4>🏛️ Sejm RP (ELI / ISAP)</h4>
                <p>Aktualne teksty jednolite ustaw i kodeksów obowiązujących w Polsce.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            """
            <div class="db-card">
                <h4>📜 Druki Sejmowe / RCL</h4>
                <p>Uzasadnienia projektów ustaw i cel regulacji (<i>ratio legis</i>).</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            """
            <div class="db-card">
                <h4>⚖️ Sąd Najwyższy (SAOS)</h4>
                <p>Uchwały 7 sędziów, zasady prawne i wyroki SN oraz sądów powszechnych.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            """
            <div class="db-card">
                <h4>🏢 NSA / WSA (CBOSA)</h4>
                <p>Centralna Baza Orzeczeń Sądów Administracyjnych i podatkowych.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c5:
        st.markdown(
            """
            <div class="db-card">
                <h4>🇪🇺 Prawo UE (EUR-Lex)</h4>
                <p>Rozporządzenia unijne, dyrektywy oraz orzecznictwo TSUE.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

# --- INICJALIZACJA STANU SESJI ---
if "kazus" not in st.session_state:
    st.session_state.kazus = None
if "oceny" not in st.session_state:
    st.session_state.oceny = {}
if "kontekst_z_baz" not in st.session_state:
    st.session_state.kontekst_z_baz = ""

# --- PANEL BOCZNY: KONFIGURACJA KAZUSU ---
with st.sidebar:
    st.header("🎓 Konfiguracja egzaminu")
    rok_studiow = st.selectbox(
        "Rok studiów prawniczych",
        [
            "I rok (Wstęp do prawoznawstwa, Prawo rzymskie, Konstytucyjne)",
            "II rok (Prawo cywilne – cz. ogólna/rzeczowe, Prawo karne materialne)",
            "III rok (Zobowiązania, Postępowanie karne KPK, Prawo administracyjne)",
            "IV rok (Spadki, KPC, KPA, Prawo handlowe i spółek, Pracy)",
            "V rok / Aplikacje (Kazusy przekrojowe, Podatkowe, Gospodarcze UE)",
        ],
        index=1,
    )

    dziedzina = st.selectbox(
        "Gałąź prawa",
        [
            "Prawo cywilne",
            "Prawo karne",
            "Prawo administracyjne",
            "Postępowanie cywilne (KPC)",
            "Postępowanie karne (KPK)",
            "Postępowanie administracyjne (KPA)",
            "Prawo handlowe i gospodarcze",
            "Prawo pracy",
            "Prawo konstytucyjne",
            "Prawo podatkowe",
            "Prawo Unii Europejskiej",
        ],
    )

    temat = st.text_input(
        "Zagadnienie lub konkretny artykuł (opcjonalnie)",
        placeholder="np. art. 415 KC, bezpodstawne wzbogacenie, obrona konieczna...",
    )

    poziom = st.select_slider(
        "Poziom trudności",
        options=["Kolokwium", "Egzamin ustny/pisemny", "Egzamin na aplikację"],
        value="Egzamin ustny/pisemny",
    )

    if st.button("🚀 Generuj nowy kazus", type="primary", use_container_width=True):
        with st.spinner("Pobieram przepisy i orzecznictwo z 5 baz oraz układam kazus..."):
            try:
                evaluator = KazusEvaluator()
                pelny_poziom = f"{poziom} ({rok_studiow})"
                kazus_obj = evaluator.generuj_kazus(
                    dziedzina=dziedzina,
                    temat=temat,
                    poziom=pelny_poziom,
                )
                st.session_state.kazus = kazus_obj
                st.session_state.oceny = {}
                st.session_state.kontekst_z_baz = zbierz_kontekst_prawny(
                    dziedzina=kazus_obj.dziedzina,
                    akt=kazus_obj.akt_glowny,
                    artykul=kazus_obj.artykul,
                    temat_kazusu=kazus_obj.tytul,
                )
            except Exception as e:
                st.error(f"Błąd podczas generowania kazusu: {e}")

    st.divider()
    st.info(
        "**Jak pracować z trenażerem?**\n"
        "Rozwiązuj kazus krok po kroku metodą **IRAC** (Oś czasu → Problem → Podstawa prawna → Subsumcja → Konkluzja). "
        "Każdy etap jest weryfikowany z ustawami Sejmu oraz linią orzeczniczą SN, NSA i TSUE."
    )

# --- GŁÓWNA PRZESTRZEŃ ROBOCZA ---
kazus: KazusEgzaminacyjny | None = st.session_state.kazus

if not kazus:
    st.info("👈 Wybierz **rok studiów** oraz **gałąź prawa** w panelu po lewej stronie i kliknij **„Generuj nowy kazus”**, aby rozpocząć trening.")
else:
    st.markdown(f"### 📋 {kazus.tytul}")
    st.caption(f"Dziedzina: **{kazus.dziedzina}** | Poziom: **{kazus.poziom}** | Główny akt: **{kazus.akt_glowny}**")

    st.warning(f"**STAN FAKTYCZNY:**\n\n{kazus.stan_faktyczny}")
    st.success(f"**PYTANIE PRAWNE DO ROZSTRZYGNIĘCIA:**\n\n{kazus.pytanie_prawne}")

    if st.session_state.kontekst_z_baz:
        with st.expander("🔎 Podgląd danych pobranych z 5 oficjalnych baz dla tego kazusu (ELI, RCL, SAOS, CBOSA, EUR-Lex)", expanded=False):
            st.code(st.session_state.kontekst_z_baz, language="text")

    st.divider()
    st.subheader("✍️ Twoje rozwiązanie metodą IRAC (5 etapów egzaminacyjnych)")

    etapy = [
        ("1. Oś czasu i fakty prawnie relewantne", "os_czasu", "Wypisz chronologicznie kluczowe daty, zdarzenia i podmioty występujące w stanie faktycznym..."),
        ("2. Issue – Problem prawny", "issue", "Sformułuj precyzyjne pytanie lub pytania prawne, od których zależy rozstrzygnięcie sprawy..."),
        ("3. Rule – Podstawa prawna i linia orzecznicza", "rule", "Wskaż konkretne artykuły kodeksów/ustaw oraz znane Ci uchwały SN, wyroki NSA lub dyrektywy UE..."),
        ("4. Application – Subsumcja (zastosowanie prawa do faktów)", "application", "Odnieś każdą przesłankę wskazanego przepisu bezpośrednio do faktów z kazusu. Uzasadnij krok po kroku..."),
        ("5. Conclusion – Konkluzja (rozstrzygnięcie)", "conclusion", "Podaj jednoznaczną odpowiedź na pytanie prawne postawione w kazusie..."),
    ]

    for tytul_etapu, klucz_etapu, placeholder_txt in etapy:
        with st.container(border=True):
            st.markdown(f"#### {tytul_etapu}")
            odpowiedz = st.text_area(
                label=f"Twoja odpowiedź ({tytul_etapu})",
                key=f"input_{klucz_etapu}",
                height=120,
                placeholder=placeholder_txt,
                label_visibility="collapsed",
            )

            col_btn, col_score = st.columns([1, 3])
            with col_btn:
                if st.button(f"Sprawdź etap {klucz_etapu.upper()}", key=f"btn_{klucz_etapu}", use_container_width=True):
                    if not odpowiedz.strip():
                        st.warning("Wpisz najpierw swoją odpowiedź przed sprawdzeniem.")
                    else:
                        with st.spinner("Egzaminator weryfikuje odpowiedź z 5 bazami prawa..."):
                            try:
                                evaluator = KazusEvaluator()
                                ocena: OcenaKroku = evaluator.ocen_krok(
                                    kazus=kazus,
                                    etap=tytul_etapu,
                                    odpowiedz_studenta=odpowiedz,
                                )
                                st.session_state.oceny[klucz_etapu] = ocena
                            except Exception as e:
                                st.error(f"Błąd oceny: {e}")

            if klucz_etapu in st.session_state.oceny:
                ocena: OcenaKroku = st.session_state.oceny[klucz_etapu]
                with col_score:
                    if ocena.zaliczony:
                        st.success(f"✅ Etap zaliczony — wynik: **{ocena.punkty} / 100 pkt**")
                    else:
                        st.error(f"⚠️ Etap wymaga poprawy — wynik: **{ocena.punkty} / 100 pkt**")

                st.markdown(f"**Ocena egzaminatora:** {ocena.komentarz}")
                if ocena.wskazowka:
                    st.info(f"💡 **Wskazówka / Orzecznictwo:** {ocena.wskazowka}")
                if ocena.wzorcowa_odpowiedz:
                    with st.expander("📖 Zobacz wzorcowe sformułowanie tego etapu"):
                        st.write(ocena.wzorcowa_odpowiedz)

    # --- PODSUMOWANIE KOŃCOWE ---
    if len(st.session_state.oceny) == 5:
        srednia = sum(o.punkty for o in st.session_state.oceny.values()) / 5
        st.divider()
        st.subheader(f"🏆 Wynik końcowy z całego kazusu: {srednia:.1f} / 100 pkt")
        if srednia >= 80:
            st.balloons()
            st.success("Ocena egzaminacyjna: **Bardzo dobry (5.0)** – świetna subsumcja i znajomość podstaw prawnych!")
        elif srednia >= 60:
            st.info("Ocena egzaminacyjna: **Dobry (4.0)** – poprawny kierunek, dopracuj szczegóły orzecznicze.")
        else:
            st.warning("Ocena egzaminacyjna: **Dostateczny / Do poprawy** – przeanalizuj wzorcowe odpowiedzi w każdym etapie.")
