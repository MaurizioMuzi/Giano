# run_test_pipeline.py
from datetime import date, datetime
from decimal import Decimal
import pprint

from core.batch_logger import BatchLogger
from processes.pdcfoavv_formazione_avviso.context import FormazioneAvvisoContext
from processes.pdcfoavv_formazione_avviso.steps import (
    StatoFormazioneStep,
    GestioneRipartenzeStep,
    ElaborazioneCurjoi1Step
)


# =============================================================================
# 1. SIMULATORE TABLE MAP (Restituisce i dizionari tal quali)
# =============================================================================
class MockTableMap:
    def __init__(self, table_name: str):
        self.table_name = table_name
        self.progArticolo = "progArticolo"

    def normalize(self, row: dict) -> dict:
        return dict(row)


# =============================================================================
# 2. QUERY BUILDER SIMULATO (Registra e compila la query)
# =============================================================================
class MockQueryBuilder:
    def __init__(self, table_name: str, engine):
        self.table_name = table_name
        self.engine = engine
        self._select_cols = []
        self._filters = []
        self._joins = []
        self._orders = []
        self._limit = None
        self._is_count = False

    def select(self, *cols):
        self._select_cols.extend(cols)
        return self

    def select_joined(self, *cols):
        self._select_cols.extend(cols)
        return self

    def select_raw(self, raw_expr):
        self._select_cols.append(raw_expr)
        return self

    def join(self, target_map, alias_self="A", alias_target="B"):
        self._joins.append((target_map.table_name, alias_self, alias_target))
        return self

    def on(self, left, right):
        return self

    def filter_by(self, col, op, val):
        self._filters.append((col, op, val))
        return self

    def filter_by_joined(self, col, op, val):
        self._filters.append((f"JOINED.{col}", op, val))
        return self

    def order_by(self, *cols):
        self._orders.extend(cols)
        return self

    def order_by_desc(self, *cols):
        self._orders.extend([f"{c} DESC" for c in cols])
        return self

    def order_by_joined(self, *cols):
        self._orders.extend([f"JOINED.{c}" for c in cols])
        return self

    def limit(self, n):
        self._limit = n
        return self

    def with_uncommitted_read(self):
        return self

    def distinct(self):
        return self

    def count(self):
        self._is_count = True
        return self

    def group_by(self, *cols):
        return self

    def having_raw(self, expr):
        return self

    def count_subquery(self, alias):
        self._is_count = True
        return self

    def exists(self, target_map, alias):
        return self

    def correlate(self, l, r, tm):
        return self

    def correlate_mismatch(self, *cols, parent_table_map=None, operator="<>"):
        return self

    def where_exists(self, sub):
        return self

    def compile_select(self):
        return {
            "type": "SELECT",
            "table": self.table_name,
            "columns": self._select_cols,
            "filters": self._filters,
            "orders": self._orders,
            "limit": self._limit,
            "is_count": self._is_count
        }

    def compile_insert(self, data):
        return {
            "type": "INSERT",
            "table": self.table_name,
            "data": data
        }

    def compile_update(self, data):
        return {
            "type": "UPDATE",
            "table": self.table_name,
            "filters": self._filters,
            "data": data
        }


# =============================================================================
# 3. SPY ENGINE (Database In-Memory che raccoglie query ed esegue risposte coerenti)
# =============================================================================
class SpyDatabaseEngine:
    def __init__(self):
        self.queries_executed = []
        self.mutations_executed = []

        # Database virtuale con record preparati ad-hoc per soddisfare tutti i rami
        self.db = {
            "ADCFRT18": [
                {
                    "dcon": date(2026, 9, 22),
                    "diniinf": date(2026, 1, 1),
                    "dfininf": date(2026, 8, 31),
                    "dinifor": date(2026, 9, 1),
                    "dfinfor": date(2026, 12, 31),
                    "fstfor": "0",
                    "tmsini": None,
                    "tmsfin": None
                }
            ],
            "ADCTET17": [
                {
                    "sede": "0100",
                    "zona": "01",
                    "codCentro": "01",
                    "codServizio": "AV",
                    "dataPre": date(2026, 9, 20)
                }
            ],
            "ADCFRT01": [
                {
                    "gestione": "1",
                    "sede": "0100",
                    "zona": "01",
                    "codCentro": "01",
                    "annoAvviso": 2026,
                    "progAvviso": 101,
                    "numPartitaAvviso": 1,
                    "numEspAvviso": 1,
                    "codiceAtto": "ATTO-001",
                    "codiceFiscale": "RSSMRA80A01H501Z",
                    "statoAttivita": "0I",
                    "tipoAvviso": "1",
                    "flgValFiscale": "0",
                    "codAzienda": "",
                    "periodo": "2026",
                    "periodoBi": "",
                    "flgRateizzazione": "0",
                    "codEsattoria": "050",
                    "codEsattoriaAvviso": "350",
                    "timestampInsStato": datetime(2026, 9, 10, 10, 0, 0),
                    "timestampVarStato": datetime(2026, 9, 10, 10, 0, 0),
                    "dataInf": date(2026, 3, 1),
                    "dataNot": None,
                    "partitaIva": ""
                }
            ],
            "ADCFRT10": [
                {
                    "gestione": "1",
                    "codiceAtto": "ATTO-001",
                    "progArticolo": 1,
                    "statoArticolo": "0I",
                    "codTributoCnc": "8340",
                    "impTributo": Decimal("150.00"),
                    "impTributoCalc": Decimal("150.00"),
                    "impAggio": Decimal("10.00"),
                    "codCausale": "",
                    "codNaturaTrb": "N"
                },
                {
                    "gestione": "1",
                    "codiceAtto": "ATTO-001",
                    "progArticolo": 2,
                    "statoArticolo": "0I",
                    "codTributoCnc": "8340",
                    "impTributo": Decimal("250.00"),
                    "impTributoCalc": Decimal("250.00"),
                    "impAggio": Decimal("15.00"),
                    "codCausale": "",
                    "codNaturaTrb": "N"
                }
            ],
            "ADCFRT14": [
                {
                    "gestione": "1",
                    "codiceAtto": "ATTO-001",
                    "codiceAnag": "I",
                    "cognome": "ROSSI",
                    "nome": "MARIO",
                    "indAnagrafeTrib": "VIA ROMA 10",
                    "siglaProvAnagrafeTrib": "RM",
                    "comuneAnagrafeTrib": "H501",
                    "capAnagrafeTrib": "00100",
                    "locAnagrafeTrib": "ROMA",
                    "timestampInsStato": datetime(2026, 9, 10, 10, 0, 0)
                },
                {
                    "gestione": "1",
                    "codiceAtto": "ATTO-001",
                    "codiceAnag": "I",
                    "cognome": "ROSSI",
                    "nome": "MARIO",
                    "indAnagrafeTrib": "VIA VECCHIA 1",  # Difforme per testare l'aggiornamento
                    "siglaProvAnagrafeTrib": "RM",
                    "comuneAnagrafeTrib": "H501",
                    "capAnagrafeTrib": "00100",
                    "locAnagrafeTrib": "ROMA",
                    "timestampInsStato": datetime(2026, 9, 1, 9, 0, 0)
                }
            ],
            "ADCAVV02": [
                {"codEsattoria": "50", "codiceBelfiore": "H501", "flagValidita": "0"}
            ],
            "ADCAVV01": [
                {"codConcessione": "350", "annoAvviso": "2026", "progAvviso": 12}
            ],
            "ADCFRT62": [
                {"flagBlocco": "0", "timestampInsInfo": datetime(2026, 1, 1), "timestampVarInfo": None}
            ]
        }

    def dataset(self, table_name: str) -> MockQueryBuilder:
        return MockQueryBuilder(table_name, self)

    def get_table_map(self, table_name: str) -> MockTableMap:
        return MockTableMap(table_name)

    def fetch(self, compiled_query: dict, depth: int = 0) -> list:
        self.queries_executed.append(compiled_query)
        table = compiled_query["table"]
        filters = dict((k, v) for k, op, v in compiled_query["filters"]) if compiled_query.get("filters") else {}

        if compiled_query.get("is_count"):
            if table == "ADCTET17":
                return [{"COUNT": 1}]
            if table == "ADCFRT01":
                return [{"COUNT": 1}]
            return [{"COUNT": 0}]

        if table in self.db:
            data = list(self.db[table])
            for k, v in filters.items():
                if "." not in k:
                    data = [r for r in data if r.get(k) == v or v is None]
            limit = compiled_query.get("limit")
            return data[:limit] if limit else data

        return []

    def cursor_stream(self, compiled_query: dict, buffer_size: int = 500, depth: int = 0):
        self.queries_executed.append(compiled_query)
        table = compiled_query["table"]
        rows = list(self.db.get(table, []))

        # Join simulata in-memory tra ADCFRT01 e ADCFRT10
        if table == "ADCFRT01" and any("codTributoCnc" in str(c) for c in compiled_query.get("columns", [])):
            joined_rows = []
            for t01 in self.db["ADCFRT01"]:
                for t10 in self.db["ADCFRT10"]:
                    joined_rows.append({**t01, **t10})
            yield joined_rows
            return

        yield rows

    def execute_mutation(self, compiled_mutation: dict, depth: int = 0) -> int:
        self.mutations_executed.append(compiled_mutation)
        return 1


# =============================================================================
# 4. RUNNER DI VERIFICA COMPLETO
# =============================================================================
def test_full_pipeline():
    print("=" * 90)
    print(" AVVIO TEST END-TO-END PIPELINE FORMAZIONE AVVISO")
    print("=" * 90)

    engine = SpyDatabaseEngine()
    ctx = FormazioneAvvisoContext()

    # Parametri iniziali
    ctx.ws_cges = "1"
    ctx.ws_tipoavv = "1"
    ctx.ws_forzatura0 = "0"
    ctx.ws_forzatura1 = "1"
    ctx.ws_ispeavv = Decimal("6.90")

    # Step 1: Stato Formazione
    step1 = StatoFormazioneStep(engine)
    step1.execute(ctx)

    # Step 2: Gestione Ripartenze
    step2 = GestioneRipartenzeStep(engine)
    step2.execute(ctx)

    # Step 3: Elaborazione Principale (CURJOI-1 -> CURJOI-2A -> CURJOI-2 -> AGGIORNA-TABELLE)
    step3 = ElaborazioneCurjoi1Step(engine)
    step3.execute(ctx)

    # =========================================================================
    # 5. VERIFICA DEI PASSAGGI DATI E DELLE QUERY GENERATE
    # =========================================================================
    print("\n" + "=" * 90)
    print(" CONTROLLO STATO FINALE DEL CONTESTO (ctx)")
    print("=" * 90)
    print(f"  [>] DCON / Finestra Infasamento : {ctx.dcon} [{ctx.diniinf} .. {ctx.dfininf}]")
    print(f"  [>] Codice Belfiore estratto    : {ctx.ws_codcomune}")
    print(f"  [>] Codici Esattoria CESA/AVVISO: {ctx.ws_cesa} / {ctx.ws_cesaavv}")
    print(f"  [>] Coordinate Ruolo            : Anno={ctx.ws_annoruo} | Prog={ctx.ws_nprgruo} | Chk={ctx.ws_nchkruo}")
    print(f"  [>] IDENTIFICATIVO COMPLETO (20): {ctx.ws_idavvruo}")
    print(f"  [>] Totale Tributi Cumulato     : {ctx.ws_itrbavv}")
    print(f"  [>] Totale Aggio Cumulato       : {ctx.ws_iaggavv}")
    print(f"  [>] Totale Articoli Plico       : {ctx.ws_nespart}")

    print("\n" + "=" * 90)
    print(f" QUERY GENERATE AUTOMATICAMENTE (Totale: {len(engine.queries_executed)})")
    print("=" * 90)
    for idx, q in enumerate(engine.queries_executed, start=1):
        filters_str = ", ".join([f"{f[0]} {f[1]} {f[2]}" for f in q.get("filters", [])])
        print(f"  {idx:02d}. SELECT su {q['table']:<10} | Filtri WHERE: [{filters_str}]")

    print("\n" + "=" * 90)
    print(f" MUTAZIONI GENERATE (INSERT / UPDATE) (Totale: {len(engine.mutations_executed)})")
    print("=" * 90)
    for idx, m in enumerate(engine.mutations_executed, start=1):
        if m["type"] == "INSERT":
            chiave_catt = m["data"].get("codiceAtto") or m["data"].get("identificativoAvviso") or "N/D"
            print(f"  {idx:02d}. INSERT -> {m['table']:<10} | Chiave Atto/Cartella: {chiave_catt}")
        elif m["type"] == "UPDATE":
            filtri = ", ".join([f"{f[0]}={f[2]}" for f in m.get("filters", [])])
            print(f"  {idx:02d}. UPDATE -> {m['table']:<10} | Filtri: [{filtri}] | Set: {list(m['data'].keys())}")

    # =========================================================================
    # 6. ASSERZIONI LOGICHE (Valida il successo)
    # =========================================================================
    print("\n" + "=" * 90)
    print(" ESITO COLLAUDO")
    print("=" * 90)

    tabelle_inserite = [m["table"] for m in engine.mutations_executed if m["type"] == "INSERT"]
    assert "ADCFRT01" in tabelle_inserite, "Errore: INSERT spese su ADCFRT01 non eseguita!"
    assert "ADCFRT10" in tabelle_inserite, "Errore: INSERT articolo spese su ADCFRT10 non eseguita!"
    assert "ADCFRT14" in tabelle_inserite, "Errore: INSERT recapito spese su ADCFRT14 non eseguita!"
    assert "ADCFRT03" in tabelle_inserite, "Errore: INSERT testata su ADCFRT03 non eseguita!"

    # Verifica importo finale (150 + 250 dagli articoli + 690 dalle spese = 1090.00)
    assert ctx.ws_itrbavv == Decimal("1090.00"), f"Errore: Totale tributi errato ({ctx.ws_itrbavv})"
    assert len(ctx.ws_idavvruo) == 20, f"Errore: Lunghezza identificativo avviso non conforme ({len(ctx.ws_idavvruo)})"

    print("  [SUCCESS] Flusso completato senza anomalie.")
    print("  [SUCCESS] Passaggio dati tra gli step confermato.")
    print("  [SUCCESS] Generazione automatica query e mutazioni validata.")
    print("=" * 90)


if __name__ == "__main__":
    test_full_pipeline()