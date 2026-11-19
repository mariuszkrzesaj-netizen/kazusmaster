from datetime import datetime
from io import BytesIO
from typing import Dict, List, Optional

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from evaluator import KazusEgzaminacyjny, OcenaKroku
from isap_client import ISAPClient


def _ustaw_tlo_komorki(komorka, kolor_hex: str) -> None:
    tc_pr = komorka._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), kolor_hex)
    tc_pr.append(shd)


def _ustaw_obramowanie_akapitu(akapit, kolor_hex: str = "1B365D", rozmiar: str = "12") -> None:
    p_pr = akapit._p.get_or_add_pPr()
    p_bdr = OxmlElement("w:pBdr")
    left = OxmlElement("w:left")
    left.set(qn("w:val"), "single")
    left.set(qn("w:sz"), rozmiar)
    left.set(qn("w:space"), "10")
    left.set(qn("w:color"), kolor_hex)
    p_bdr.append(left)
    p_pr.append(p_bdr)


def generuj_raport_docx(
    kazus: KazusEgzaminacyjny,
    odpowiedzi_studenta: Dict[int, str],
    oceny_krokow: Dict[int, OcenaKroku],
    isap_client: Optional[ISAPClient] = None,
    dodatkowe_przepisy_studenta: Optional[Dict[str, List[str]]] = None,
) -> bytes:
    """
    Tworzy kompletny, sformatowany dokument DOCX zawierający:
    1. Metrykę kazusu i tabelę wyników z 5 kroków IRAC,
    2. Stan faktyczny i polecenie egzaminacyjne,
    3. Pełne rozwiązanie studenta z 5 etapów wraz z komentarzem egzaminatora,
    4. Oficjalne brzmienie powołanych przepisów pobrane z API Sejmu (ELI/ISAP),
    5. Wzorcowy klucz egzaminacyjny i zestawienie pułapek formalnych.
    """
    doc = Document()

    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.0)
        section.right_margin = Cm(2.0)

    style_normal = doc.styles["Normal"]
    style_normal.font.name = "Calibri"
    style_normal.font.size = Pt(11)
    style_normal.font.color.rgb = RGBColor(0x22, 0x22, 0x22)

    granat = RGBColor(0x1B, 0x36, 0x5D)
    szary = RGBColor(0x55, 0x55, 0x55)

    # NAGŁÓWEK DOKUMENTU
    tytul_p = doc.add_paragraph()
    tytul_p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run_tytul = tytul_p.add_run(f"OPRACOWANIE KAZUSU: {kazus.tytul.upper()}")
    run_tytul.bold = True
    run_tytul.font.size = Pt(16)
    run_tytul.font.color.rgb = granat

    meta_p = doc.add_paragraph()
    run_meta = meta_p.add_run(
        f"Pion prawa: {kazus.pion_prawa}  |  Tryb: {kazus.poziom_trudnosci}  |  "
        f"Data wygenerowania: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    run_meta.font.size = Pt(9.5)
    run_meta.font.color.rgb = szary

    # TABELA WYNIKÓW Z 5 ETAPÓW
    nazwy_krokow = {
        1: "Etap 1: Oś czasu i podmioty",
        2: "Etap 2: Problem prawny",
        3: "Etap 3: Podstawa prawna i przesłanki",
        4: "Etap 4: Subsumpcja",
        5: "Etap 5: Konkluzja",
    }

    tabela_wynikow = doc.add_table(rows=1, cols=3)
    tabela_wynikow.alignment = WD_TABLE_ALIGNMENT.CENTER
    tabela_wynikow.style = "Table Grid"

    naglowki = ["Etap metodyki IRAC", "Status", "Wynik"]
    for idx, tekst in enumerate(naglowki):
        cell = tabela_wynikow.rows[0].cells[idx]
        _ustaw_tlo_komorki(cell, "1B365D")
        p = cell.paragraphs[0]
        r = p.add_run(tekst)
        r.bold = True
        r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        r.font.size = Pt(10)

    suma_punktow = 0
    for nr in range(1, 6):
        row_cells = tabela_wynikow.add_row().cells
        ocena = oceny_krokow.get(nr)
        pkt = ocena.punkty_procent if ocena else 0
        suma_punktow += pkt
        status_txt = "ZALICZONY" if (ocena and ocena.zaliczony) else "DO POPRAWY"

        row_cells[0].paragraphs[0].add_run(nazwy_krokow[nr]).font.size = Pt(10)
        row_cells[1].paragraphs[0].add_run(status_txt).font.size = Pt(10)
        row_cells[2].paragraphs[0].add_run(f"{pkt}%").font.size = Pt(10)

    row_sum = tabela_wynikow.add_row().cells
    _ustaw_tlo_komorki(row_sum[0], "F2F4F8")
    _ustaw_tlo_komorki(row_sum[1], "F2F4F8")
    _ustaw_tlo_komorki(row_sum[2], "F2F4F8")
    r_sum0 = row_sum[0].paragraphs[0].add_run("ŚREDNI WYNIK KOŃCOWY")
    r_sum0.bold = True
    r_sum0.font.size = Pt(10)
    r_sum2 = row_sum[2].paragraphs[0].add_run(f"{suma_punktow // 5}%")
    r_sum2.bold = True
    r_sum2.font.size = Pt(10)

    doc.add_paragraph()

    # SEKCJA I: STAN FAKTYCZNY I PYTANIE EGZAMINACYJNE
    h1 = doc.add_heading("I. Stan faktyczny i polecenie egzaminacyjne", level=1)
    h1.runs[0].font.color.rgb = granat

    p_stan = doc.add_paragraph(kazus.stan_faktyczny)
    _ustaw_obramowanie_akapitu(p_stan, kolor_hex="1B365D", rozmiar="16")

    p_pyt = doc.add_paragraph()
    r_pyt_lbl = p_pyt.add_run("Polecenie egzaminacyjne: ")
    r_pyt_lbl.bold = True
    p_pyt.add_run(kazus.pytanie_do_studenta)

    # SEKCJA II: ROZWIĄZANIE STUDENTA KROK PO KROKU
    h2 = doc.add_heading("II. Rozwiązanie studenta (5-etapowy schemat IRAC)", level=1)
    h2.runs[0].font.color.rgb = granat

    for nr in range(1, 6):
        h_krok = doc.add_heading(nazwy_krokow[nr], level=2)
        h_krok.runs[0].font.color.rgb = granat

        tresc_odp = odpowiedzi_studenta.get(nr, "(Brak zapisanej odpowiedzi)")
        p_odp = doc.add_paragraph(tresc_odp)
        p_odp.paragraph_format.left_indent = Cm(0.5)

        ocena = oceny_krokow.get(nr)
        if ocena and ocena.co_dobrze:
            p_uwagi = doc.add_paragraph()
            p_uwagi.paragraph_format.left_indent = Cm(0.5)
            r_uw = p_uwagi.add_run("Weryfikacja egzaminatora (elementy poprawne): ")
            r_uw.bold = True
            r_uw.font.size = Pt(9.5)
            r_uw.font.color.rgb = szary
            r_uw_txt = p_uwagi.add_run("; ".join(ocena.co_dobrze))
            r_uw_txt.font.size = Pt(9.5)
            r_uw_txt.font.color.rgb = szary

    # SEKCJA III: OFICJALNE PODSTAWY PRAWNE Z API SEJMU (ELI / ISAP)
    h3 = doc.add_heading("III. Oficjalne podstawy prawne (Baza Sejmu RP – ELI/ISAP)", level=1)
    h3.runs[0].font.color.rgb = granat

    polaczone_podstawy: Dict[str, List[str]] = {}
    for mapa in (kazus.klucz_podstawy_prawne, dodatkowe_przepisy_studenta or {}):
        for kod, numery in mapa.items():
            kod_up = kod.upper().strip()
            zbior = set(polaczone_podstawy.get(kod_up, []))
            zbior.update(numery)
            polaczone_podstawy[kod_up] = sorted(list(zbior))

    klient = isap_client or ISAPClient()
    for kod, numery in polaczone_podstawy.items():
        try:
            dane_ustawy = klient.pobierz_konkretne_artykuly(kod, numery)
            p_ust = doc.add_paragraph()
            r_ust = p_ust.add_run(
                f"{dane_ustawy['ustawa']} ({dane_ustawy['publikator']}) – status: {dane_ustawy['status']}"
            )
            r_ust.bold = True
            r_ust.font.color.rgb = granat

            for nr_art, tresc_art in dane_ustawy["przepisy"].items():
                p_art = doc.add_paragraph(tresc_art)
                p_art.paragraph_format.left_indent = Cm(0.5)
                p_art.runs[0].font.size = Pt(10)
        except Exception as exc:
            doc.add_paragraph(f"Nie udało się pobrać przepisów dla {kod}: {exc}")

    # SEKCJA IV: WZORCOWY KLUCZ EGZAMINACYJNY I PUŁAPKI FORMALNE
    doc.add_page_break()
    h4 = doc.add_heading("IV. Wzorcowy klucz egzaminacyjny i arkusz subsumpcji", level=1)
    h4.runs[0].font.color.rgb = granat

    p_prob = doc.add_paragraph()
    p_prob.add_run("Wzorcowy problem prawny: ").bold = True
    p_prob.add_run(kazus.klucz_problem_prawny)

    if kazus.klucz_przeslanki_i_subsumpcja:
        doc.add_heading("Wzorcowe rozbicie przesłanek i subsumpcja:", level=2)
        tab_sub = doc.add_table(rows=1, cols=3)
        tab_sub.alignment = WD_TABLE_ALIGNMENT.CENTER
        tab_sub.style = "Table Grid"

        for idx, nagl in enumerate(["Przepis", "Przesłanka ustawowa", "Wzorcowa subsumpcja (fakt z kazusu)"]):
            c = tab_sub.rows[0].cells[idx]
            _ustaw_tlo_komorki(c, "1B365D")
            r = c.paragraphs[0].add_run(nagl)
            r.bold = True
            r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            r.font.size = Pt(9.5)

        for item in kazus.klucz_przeslanki_i_subsumpcja:
            row = tab_sub.add_row().cells
            row[0].paragraphs[0].add_run(item.artykul).font.size = Pt(9.5)
            row[1].paragraphs[0].add_run(item.nazwa_przeslanki).font.size = Pt(9.5)
            row[2].paragraphs[0].add_run(item.wzorcowa_subsumpcja).font.size = Pt(9.5)

    doc.add_paragraph()
    if kazus.klucz_pulapki_formalne:
        p_pul = doc.add_paragraph()
        p_pul.add_run("Ukryte pułapki formalne i materialne w kazusie:").bold = True
        for pulapka in kazus.klucz_pulapki_formalne:
            doc.add_paragraph(pulapka, style="List Bullet")

    p_konk = doc.add_paragraph()
    p_konk.add_run("Wzorcowa konkluzja: ").bold = True
    p_konk.add_run(kazus.klucz_konkluzja)

    bufor = BytesIO()
    doc.save(bufor)
    bufor.seek(0)
    return bufor.getvalue()
