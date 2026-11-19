import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Literal, Optional


@dataclass
class WynikTerminu:
    """Struktura wynikowa z pełnym uzasadnieniem normatywnym dla studenta i weryfikatora AI."""
    data_zdarzenia: date
    typ_jednostki: str
    wartosc: int
    koniec_surowy: date
    koniec_ostateczny: date
    przesuniety: bool
    powody_przesuniecia: List[str]
    podstawa_prawna: str
    uzasadnienie: str


def oblicz_wielkanoc(rok: int) -> date:
    """
    Oblicza datę Niedzieli Wielkanocnej (kalendarz gregoriański)
    algorytmem Meeusa/Jonesa/Butchera.
    """
    a = rok % 19
    b = rok // 100
    c = rok % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    miesiac = (h + l - 7 * m + 114) // 31
    dzien = ((h + l - 7 * m + 114) % 31) + 1
    return date(rok, miesiac, dzien)


def pobierz_dni_ustawowo_wolne(rok: int) -> Dict[date, str]:
    """
    Zwraca słownik {data: nazwa_swieta} dla wszystkich dni ustawowo wolnych od pracy w Polsce
    zgodnie z ustawą z dnia 18 stycznia 1951 r. o dniach wolnych od pracy.
    """
    wielkanoc = oblicz_wielkanoc(rok)
    poniedzialek_wielkanocny = wielkanoc + timedelta(days=1)
    zielone_swiatki = wielkanoc + timedelta(days=49)
    boze_cialo = wielkanoc + timedelta(days=60)

    dni_wolne: Dict[date, str] = {
        date(rok, 1, 1): "Nowy Rok",
        date(rok, 1, 6): "Święto Trzech Króli (Objawienie Pańskie)",
        wielkanoc: "Pierwszy dzień Wielkiej Nocy (Niedziela Wielkanocna)",
        poniedzialek_wielkanocny: "Drugi dzień Wielkiej Nocy (Poniedziałek Wielkanocny)",
        date(rok, 5, 1): "Święto Państwowe (1 Maja)",
        date(rok, 5, 3): "Święto Narodowe Trzeciego Maja",
        zielone_swiatki: "Pierwszy dzień Zielonych Świątek",
        boze_cialo: "Dzień Bożego Ciała",
        date(rok, 8, 15): "Wniebowzięcie Najświętszej Maryi Panny",
        date(rok, 11, 1): "Wszystkich Świętych",
        date(rok, 11, 11): "Narodowe Święto Niepodległości",
        date(rok, 12, 25): "Pierwszy dzień Bożego Narodzenia",
        date(rok, 12, 26): "Drugi dzień Bożego Narodzenia",
    }

    if rok >= 2025:
        dni_wolne[date(rok, 12, 24)] = "Wigilia Bożego Narodzenia"

    return dni_wolne


def czy_dzien_wolny_lub_sobota(dzien: date) -> tuple[bool, Optional[str]]:
    """
    Sprawdza, czy dany dzień jest sobotą, niedzielą lub dniem ustawowo wolnym od pracy
    w rozumieniu art. 115 KC i art. 165 § 1 KPC.
    """
    dni_wolne = pobierz_dni_ustawowo_wolne(dzien.year)

    if dzien in dni_wolne:
        return True, f"{dzien.isoformat()} – dzień ustawowo wolny od pracy ({dni_wolne[dzien]})"
    if dzien.weekday() == 5:
        return True, f"{dzien.isoformat()} – sobota (zrównana z dniem wolnym na mocy art. 115 KC)"
    if dzien.weekday() == 6:
        return True, f"{dzien.isoformat()} – niedziela (dzień ustawowo wolny od pracy)"

    return False, None


def _dodaj_miesiace_art_112_kc(data_start: date, liczba_miesiecy: int) -> date:
    """
    Realizuje regułę z art. 112 zd. 1 KC:
    Termin oznaczony w miesiącach kończy się z upływem dnia, który datą odpowiada
    początkowemu dniowi terminu, a gdyby takiego dnia w ostatnim miesiącu nie było –
    w ostatnim dniu tego miesiąca.
    """
    docelowy_miesiac_idx = (data_start.month - 1) + liczba_miesiecy
    docelowy_rok = data_start.year + (docelowy_miesiac_idx // 12)
    docelowy_miesiac = (docelowy_miesiac_idx % 12) + 1

    ostatni_dzien_miesiaca = calendar.monthrange(docelowy_rok, docelowy_miesiac)[1]
    docelowy_dzien = min(data_start.day, ostatni_dzien_miesiaca)

    return date(docelowy_rok, docelowy_miesiac, docelowy_dzien)


def oblicz_termin(
    data_zdarzenia: date,
    wartosc: int,
    jednostka: Literal["dni", "tygodnie", "miesiace", "lata"],
    tryb: Literal["materialny_kc", "procesowy_kpc"] = "procesowy_kpc",
    stosuj_art_115: bool = True,
) -> WynikTerminu:
    """
    Oblicza koniec terminu zgodnie z art. 110–115 KC oraz art. 165 § 1 KPC.
    """
    if wartosc <= 0:
        raise ValueError("Wartość terminu musi być dodatnią liczbą całkowitą.")

    if jednostka == "dni":
        koniec_surowy = data_zdarzenia + timedelta(days=wartosc)
        podstawa = "art. 111 § 1 i § 2 KC"
    elif jednostka == "tygodnie":
        koniec_surowy = data_zdarzenia + timedelta(weeks=wartosc)
        podstawa = "art. 112 zd. 1 KC"
    elif jednostka == "miesiace":
        koniec_surowy = _dodaj_miesiace_art_112_kc(data_zdarzenia, wartosc)
        podstawa = "art. 112 zd. 1 KC"
    elif jednostka == "lata":
        koniec_surowy = _dodaj_miesiace_art_112_kc(data_zdarzenia, wartosc * 12)
        podstawa = "art. 112 zd. 1 KC"
    else:
        raise ValueError(f"Nieobsługiwana jednostka czasu: {jednostka}")

    if tryb == "procesowy_kpc":
        podstawa = f"art. 165 § 1 KPC w zw. z {podstawa}"

    koniec_ostateczny = koniec_surowy
    powody_przesuniecia: List[str] = []

    if stosuj_art_115:
        while True:
            czy_wolny, opis = czy_dzien_wolny_lub_sobota(koniec_ostateczny)
            if czy_wolny and opis:
                powody_przesuniecia.append(opis)
                koniec_ostateczny += timedelta(days=1)
            else:
                break

    przesuniety = len(powody_przesuniecia) > 0
    if przesuniety:
        podstawa += " oraz art. 115 KC"

    uzasadnienie_linie = [
        f"Zdarzenie początkowe nastąpiło w dniu {data_zdarzenia.isoformat()} (dnia tego nie wlicza się do biegu terminu).",
        f"Surowy upływ terminu ({wartosc} {jednostka}) przypada na dzień {koniec_surowy.isoformat()}.",
    ]
    if przesuniety:
        uzasadnienie_linie.append(
            "Nastąpiło przesunięcie końca terminu na podstawie art. 115 KC z uwagi na: "
            + "; ".join(powody_przesuniecia)
            + "."
        )
        uzasadnienie_linie.append(
            f"Ostateczny termin do dokonania czynności upływa z końcem dnia {koniec_ostateczny.isoformat()} (godz. 23:59:59)."
        )
    else:
        uzasadnienie_linie.append(
            f"Dzień {koniec_ostateczny.isoformat()} jest dniem roboczym, więc termin upływa z jego końcem (godz. 23:59:59)."
        )

    return WynikTerminu(
        data_zdarzenia=data_zdarzenia,
        typ_jednostki=jednostka,
        wartosc=wartosc,
        koniec_surowy=koniec_surowy,
        koniec_ostateczny=koniec_ostateczny,
        przesuniety=przesuniety,
        powody_przesuniecia=powody_przesuniecia,
        podstawa_prawna=podstawa,
        uzasadnienie=" ".join(uzasadnienie_linie),
    )


def sprawdz_zachowanie_terminu_kpc(
    termin_ostateczny: date,
    data_czynnosci: date,
    sposob_wniesienia: Literal[
        "biuro_podawcze_sadu",
        "operator_wyznaczony_pl",
        "operator_powszechny_ue",
        "kurier_prywatny",
        "system_teleinformatyczny",
    ],
) -> dict:
    """
    Weryfikuje zachowanie terminu procesowego na podstawie art. 165 § 2–4 KPC.
    """
    if sposob_wniesienia in ("biuro_podawcze_sadu", "system_teleinformatyczny"):
        data_skuteczna = data_czynnosci
        podstawa = "art. 165 § 1 KPC" if sposob_wniesienia == "biuro_podawcze_sadu" else "art. 165 § 4 KPC"
        komentarz = "Decyduje data fizycznego złożenia w sądzie lub wprowadzenia pisma do systemu teleinformatycznego."
    elif sposob_wniesienia in ("operator_wyznaczony_pl", "operator_powszechny_ue"):
        data_skuteczna = data_czynnosci
        podstawa = "art. 165 § 2 KPC"
        komentarz = (
            "Oddanie pisma w polskiej placówce pocztowej operatora wyznaczonego (Poczta Polska S.A.) "
            "lub operatora świadczącego pocztowe usługi powszechne w innym państwie UE jest równoznaczne z wniesieniem go do sądu."
        )
    elif sposob_wniesienia == "kurier_prywatny":
        return {
            "wymaga_daty_doreczenia_do_sadu": True,
            "podstawa_prawna": "art. 165 § 2 KPC a contrario",
            "ostrzezenie": (
                "PUŁAPKA KAZUSOWA: Nadanie pisma prywatną firmą kurierską (niebędącą operatorem wyznaczonym) "
                "NIE korzysta z domniemania z art. 165 § 2 KPC. O zachowaniu terminu decyduje dzień faktycznego "
                "wpływu przesyłki do biura podawczego sądu, a nie data nadania u kuriera!"
            ),
        }
    else:
        raise ValueError(f"Nieznany sposób wniesienia: {sposob_wniesienia}")

    w_terminie = data_skuteczna <= termin_ostateczny
    return {
        "zachowano_termin": w_terminie,
        "termin_ostateczny": termin_ostateczny.isoformat(),
        "data_skuteczna": data_skuteczna.isoformat(),
        "podstawa_prawna": podstawa,
        "komentarz": komentarz,
    }


def oblicz_wiek_prawny(data_urodzenia: date, osiagany_wiek: int) -> dict:
    """
    Realizuje regułę szczególną z art. 112 zd. 2 KC.
    """
    try:
        data_pelnoletnosci = date(data_urodzenia.year + osiagany_wiek, data_urodzenia.month, data_urodzenia.day)
    except ValueError:
        data_pelnoletnosci = date(data_urodzenia.year + osiagany_wiek, 2, 28)

    return {
        "data_urodzenia": data_urodzenia.isoformat(),
        "wiek": osiagany_wiek,
        "data_nabycia_statusu": data_pelnoletnosci.isoformat(),
        "chwila_uplywu": "godz. 00:00:00 (początek dnia)",
        "podstawa_prawna": "art. 112 zd. 2 KC",
    }
