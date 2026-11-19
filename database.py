import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List

from evaluator import KazusEgzaminacyjny, OcenaKroku


class KazusDatabase:
    """
    Lokalna baza danych SQLite przechowująca:
    - historię ukończonych kazusów wraz z punktacją z 5 kroków,
    - fiszki Active Recall z harmonogramem powtórek (Spaced Repetition).
    """

    def __init__(self, db_path: str = "./kazus_master.db"):
        self.db_path = Path(db_path)
        self._inicjalizuj_tabele()

    def _polacz(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _inicjalizuj_tabele(self) -> None:
        with self._polacz() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kazusy_historia (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tytul TEXT NOT NULL,
                    pion_prawa TEXT NOT NULL,
                    poziom_trudnosci TEXT NOT NULL,
                    stan_faktyczny TEXT NOT NULL,
                    pytanie TEXT NOT NULL,
                    kazus_json TEXT NOT NULL,
                    oceny_json TEXT NOT NULL,
                    sredni_wynik INTEGER NOT NULL,
                    data_ukonczenia TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fiszki_powtorkowe (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kazus_id INTEGER,
                    pion_prawa TEXT NOT NULL,
                    tresc_fiszki TEXT NOT NULL,
                    poziom_opanowania INTEGER DEFAULT 0,
                    nastepna_powtorka TEXT NOT NULL,
                    data_utworzenia TEXT NOT NULL,
                    FOREIGN KEY (kazus_id) REFERENCES kazusy_historia (id)
                )
                """
            )
            conn.commit()

    def zapisz_ukonczony_kazus(
        self,
        kazus: KazusEgzaminacyjny,
        oceny_krokow: Dict[int, OcenaKroku],
    ) -> int:
        sredni_wynik = sum(o.punkty_procent for o in oceny_krokow.values()) // max(len(oceny_krokow), 1)
        teraz_iso = datetime.now().isoformat(timespec="seconds")
        dzis_iso = date.today().isoformat()

        oceny_serializowane = {
            str(nr): ocena.model_dump() for nr, ocena in oceny_krokow.items()
        }

        with self._polacz() as conn:
            cursor = conn.execute(
                """
                INSERT INTO kazusy_historia (
                    tytul, pion_prawa, poziom_trudnosci, stan_faktyczny,
                    pytanie, kazus_json, oceny_json, sredni_wynik, data_ukonczenia
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kazus.tytul,
                    kazus.pion_prawa,
                    kazus.poziom_trudnosci,
                    kazus.stan_faktyczny,
                    kazus.pytanie_do_studenta,
                    kazus.model_dump_json(),
                    json.dumps(oceny_serializowane, ensure_ascii=False),
                    sredni_wynik,
                    teraz_iso,
                ),
            )
            kazus_id = cursor.lastrowid

            ocena_5 = oceny_krokow.get(5)
            if ocena_5 and ocena_5.fiszka_powtorkowa:
                conn.execute(
                    """
                    INSERT INTO fiszki_powtorkowe (
                        kazus_id, pion_prawa, tresc_fiszki, poziom_opanowania,
                        nastepna_powtorka, data_utworzenia
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        kazus_id,
                        kazus.pion_prawa,
                        ocena_5.fiszka_powtorkowa.strip(),
                        0,
                        dzis_iso,
                        teraz_iso,
                    ),
                )

            conn.commit()
            return int(kazus_id)

    def pobierz_statystyki_ogolne(self) -> dict:
        with self._polacz() as conn:
            row_kazusy = conn.execute(
                "SELECT COUNT(*) AS liczba, COALESCE(AVG(sredni_wynik), 0) AS srednia FROM kazusy_historia"
            ).fetchone()
            row_fiszki = conn.execute(
                "SELECT COUNT(*) AS wszystkie FROM fiszki_powtorkowe"
            ).fetchone()
            row_do_powtorki = conn.execute(
                "SELECT COUNT(*) AS na_dzis FROM fiszki_powtorkowe WHERE nastepna_powtorka <= ?",
                (date.today().isoformat(),),
            ).fetchone()

        return {
            "ukonczone_kazusy": row_kazusy["liczba"],
            "sredni_wynik_globalny": round(row_kazusy["srednia"], 1),
            "wszystkie_fiszki": row_fiszki["wszystkie"],
            "fiszki_na_dzis": row_do_powtorki["na_dzis"],
        }

    def pobierz_historie_kazusow(self, limit: int = 20) -> List[dict]:
        with self._polacz() as conn:
            rows = conn.execute(
                """
                SELECT id, tytul, pion_prawa, poziom_trudnosci, sredni_wynik,
                       oceny_json, data_ukonczenia
                FROM kazusy_historia
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        wyniki = []
        for r in rows:
            wyniki.append(
                {
                    "id": r["id"],
                    "tytul": r["tytul"],
                    "pion_prawa": r["pion_prawa"],
                    "poziom_trudnosci": r["poziom_trudnosci"],
                    "sredni_wynik": r["sredni_wynik"],
                    "oceny": json.loads(r["oceny_json"]),
                    "data_ukonczenia": r["data_ukonczenia"],
                }
            )
        return wyniki

    def pobierz_fiszki_do_powtorki(self, tylko_na_dzis: bool = True) -> List[dict]:
        with self._polacz() as conn:
            if tylko_na_dzis:
                rows = conn.execute(
                    """
                    SELECT * FROM fiszki_powtorkowe
                    WHERE nastepna_powtorka <= ?
                    ORDER BY nastepna_powtorka ASC, id ASC
                    """,
                    (date.today().isoformat(),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM fiszki_powtorkowe ORDER BY id DESC"
                ).fetchall()

        return [dict(r) for r in rows]

    def aktualizuj_powtorke_fiszki(self, fiszka_id: int, zapamietano: bool) -> None:
        interwaly_dni = {0: 1, 1: 3, 2: 7, 3: 14, 4: 30, 5: 60}

        with self._polacz() as conn:
            row = conn.execute(
                "SELECT poziom_opanowania FROM fiszki_powtorkowe WHERE id = ?",
                (fiszka_id,),
            ).fetchone()
            if not row:
                return

            aktualny_poziom = row["poziom_opanowania"]
            if zapamietano:
                nowy_poziom = min(aktualny_poziom + 1, 5)
                dni_do_dodania = interwaly_dni[nowy_poziom]
            else:
                nowy_poziom = 0
                dni_do_dodania = 1

            nastepna_data = (date.today() + timedelta(days=dni_do_dodania)).isoformat()
            conn.execute(
                """
                UPDATE fiszki_powtorkowe
                SET poziom_opanowania = ?, nastepna_powtorka = ?
                WHERE id = ?
                """,
                (nowy_poziom, nastepna_data, fiszka_id),
            )
            conn.commit()
