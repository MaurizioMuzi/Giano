# run_test_pipeline_new.py
import sys
from datetime import date, datetime
from decimal import Decimal

from core.batch_logger import BatchLogger
from processes.formazione_avviso.context import FormazioneAvvisoContext
from processes.formazione_avviso.steps import (
    StatoFormazioneStep,
    GestioneRipartenzeStep,
    ElaborazioneCurjoi1Step
)


class MockTableMap:
    def __init__(self, table_name: str):
        self.table_name = table_name
        self.progArticolo = "progArticolo"

    def normalize(self, row: dict) -> dict:
        return dict(row)


class MockQueryBuilder:
    """Compilatore SQL diagnostico: trasforma le chiamate fluenti in codice SQL DB2 reale."""

    def __init__(self, table_name: str, engine):
        self.table_name = table_name
        self.engine = engine
        self._select_cols = []
        self._filters = []
        self._joins = []
        self._orders = []
        self._limit = None
        self._is_distinct = False
        self._is_count = False
        self._subquery_alias = None
        self._group_by_cols = []
        self._having_clauses = []
        self._where_exists_subquery = None

    def select(self, *cols):
        self._select_cols.extend(cols)
        return self

    def select_joined(self, *cols):
        self._select_cols.extend([f"B.{c}" for c in cols])
        return self

    def select_raw(self, raw_expr):
        self._select_cols.append(raw_expr)
        return self

    def join(self, target_map, alias_self="A", alias_target="B"):
        self._joins.append({
            "target": target_map.table_name,
            "alias_self": alias_self,
            "alias_target": alias_target,
            "on": []
        })
        return self

    def on(self, left, right):
        if self._joins:
            self._joins[-1]["on"].append((left, right))
        return self

    def filter_by(self, col, op, val):
        self._filters.append((col, op, val))
        return self

    def filter_by_joined(self, col, op, val):
        self._filters.append((f"B.{col}", op, val))
        return self

    def order_by(self, *cols):
        self._orders.extend(cols)
        return self

    def order_by_desc(self, *cols):
        self._orders.extend([f"{c} DESC" for c in cols])
        return self

    def order_by_joined(self, *cols):
        self._orders.extend([f"B.{c}" for c in cols])
        return self

    def limit(self, n):
        self._limit = n
        return self

    def with_uncommitted_read(self):
        return self

    def distinct(self):
        self._is_distinct = True
        return self

    def count(self):
        self._is_count = True
        return self

    def group_by(self, *cols):
        self._group_by_cols.extend(cols)
        return self

    def having_raw(self, expr):
        self._having_clauses.append(expr)
        return self

    def count_subquery(self, alias):
        self._is_count = True
        self._subquery_alias = alias
        return self

    def exists(self, target_map, alias):
        return self

    def correlate(self, l, r, tm):
        return self

    def correlate_mismatch(self, *cols, parent_table_map=None, operator="<>"):
        return self

    def where_exists(self, sub):
        self._where_exists_subquery = "EXISTS (SELECT 1 FROM ADCFRT01 B WHERE B.CFIS = A.CFIS)"
        return self

    def _format_value(self, val):
        if val is None:
            return "NULL"
        if isinstance(val, (int, float, Decimal)):
            return str(val)
        if isinstance(val, (date, datetime)):
            return f"'{val}'"
        if isinstance(val, (list, tuple)):
            items = ", ".join([self._format_value(v) for v in val])
            return f"({items})"
        return f"'{val}'"

    def compile_select(self) -> dict:
        distinct_str = "DISTINCT " if self._is_distinct else ""
        if self._is_count:
            cols_str = "COUNT(*)"
        elif self._select_cols:
            cols_str = ", ".join(self._select_cols)
        else:
            cols_str = "*"

        sql_parts = [f"SELECT {distinct_str}{cols_str}"]

        if self._joins:
            alias_from = self._joins[0]["alias_self"]
            sql_parts.append(f"FROM {self.table_name} {alias_from}")
            for j in self._joins:
                target = j["target"]
                alias_target = j["alias_target"]
                on_conditions = " AND ".join([f"{alias_from}.{l} = {alias_target}.{r}" for l, r in j["on"]])
                sql_parts.append(f"INNER JOIN {target} {alias_target} ON {on_conditions}")
        else:
            sql_parts.append(f"FROM {self.table_name}")

        where_conds = []
        for col, op, val in self._filters:
            where_conds.append(f"{col} {op} {self._format_value(val)}")
        if self._where_exists_subquery:
            where_conds.append(self._where_exists_subquery)

        if where_conds:
            sql_parts.append("WHERE " + " AND ".join(where_conds))

        if self._group_by_cols:
            sql_parts.append("GROUP BY " + ", ".join(self._group_by_cols))
        if self._having_clauses:
            sql_parts.append("HAVING " + " AND ".join(self._having_clauses))

        if self._orders:
            sql_parts.append("ORDER BY " + ", ".join(self._orders))

        if self._limit:
            sql_parts.append(f"FETCH FIRST {self._limit} ROWS ONLY")
        sql_parts.append("WITH UR")

        sql_text = " ".join(sql_parts)
        if self._subquery_alias:
            sql_text = f"SELECT COUNT(*) FROM ({sql_text}) AS {self._subquery_alias}"

        params = tuple(val for _, _, val in self._filters if val is not None)

        return {
            "type": "SELECT",
            "table": self.table_name,
            "sql": sql_text,
            "params": params,
            "filters": self._filters,
            "columns": self._select_cols,
            "is_count": self._is_count
        }

    def compile_insert(self, data: dict) -> dict:
        cols = ", ".join(data.keys())
        vals = ", ".join([self._format_value(v) for v in data.values()])
        sql_text = f"INSERT INTO {self.table_name} ({cols}) VALUES ({vals})"
        params = tuple(data.values())
        return {
            "type": "INSERT",
            "table": self.table_name,
            "sql": sql_text,
            "params": params,
            "data": data
        }

    def compile_update(self, data: dict) -> dict:
        set_clause = ", ".join([f"{k} = {self._format_value(v)}" for k, v in data.items()])
        where_conds = [f"{col} {op} {self._format_value(val)}" for col, op, val in self._filters]
        where_clause = " WHERE " + " AND ".join(where_conds) if where_conds else ""
        sql_text = f"UPDATE {self.table_name} SET {set_clause}{where_clause}"
        params = tuple(list(data.values()) + [val for _, _, val in self._filters if val is not None])
        return {
            "type": "UPDATE",
            "table": self.table_name,
            "sql": sql_text,
            "params": params,
            "filters": self._filters,
            "data": data
        }


class SpyDatabaseEngine:
    """Database in-memory per validazione end-to-end e allineamento perfetto dell'albero dei log."""

    def __init__(self):
        self.queries_executed = []
        self.mutations_executed = []

        self.t01_master = {
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
            "flgEuro": "1",
            "dataRifCon": 0,
            "dataFallimento": None,
            "flgCessione": "",
            "flgDecadenza": "",
            "sedeOrigine": "0100",
            "timestampInsStato": datetime(2026, 9, 10, 10, 0, 0),
            "timestampVarStato": datetime(2026, 9, 10, 10, 0, 0),
            "dataInf": date(2026, 3, 1),
            "dataNot": None,
            "partitaIva": "12345678901",
            "codDipendente": "OP01",
            "descrizioneAtto": "PARTITA ORDINARIA",
            "annoEmissione": 2026,
            "numEmissione": 1,
            "numInail": "00000000",
            "codSegnalazione": "",
            "meseInizioPeriodo": 1,
            "meseFinePeriodo": 12,
            "numRate": 1,
            "annoRifRuolo": 2026,
            "numRuolo": 1,
            "codEsattoriaDel": "",
            "annoCarico": "",
            "numCarico": "",
            "numChkCarico": "",
            "dataTransizioneStato": None,
            "flgIscrizione": "",
            "codCausale": "",
            "codFasAmm": "",
            "statoAzienda": "",
            "dataStatoAzienda": "0001-01-01",
            "descrizioneAttoBi": "",
            "flgSanzioni": "",
            "flgCessioneRuolo": "",
            "codiceErrore": "",
            "flgSanzioniAdr": ""
        }

        self.t10_articoli = [
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
                "codNaturaTrb": "N",
                "numTotRate": 1,
                "codRata": "",
                "flgResiduo": "",
                "impInteressi": Decimal("0"),
                "impAggioTot": Decimal("10.00"),
                "impAggioAnt": Decimal("0"),
                "impArrotondamento": Decimal("0"),
                "numIdDecre": 0,
                "tasso": Decimal("0"),
                "impCapitale": Decimal("150.00"),
                "dataFineCalc": None,
                "codFasAmm": "F"
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
                "codNaturaTrb": "N",
                "numTotRate": 1,
                "codRata": "",
                "flgResiduo": "",
                "impInteressi": Decimal("0"),
                "impAggioTot": Decimal("15.00"),
                "impAggioAnt": Decimal("0"),
                "impArrotondamento": Decimal("0"),
                "numIdDecre": 0,
                "tasso": Decimal("0"),
                "impCapitale": Decimal("250.00"),
                "dataFineCalc": None,
                "codFasAmm": "F"
            }
        ]

        self.t14_anagrafica = [
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
                "indirizzo": "VIA ROMA 10",
                "numeroCivico": "10",
                "letteraCivico": "",
                "numeroChilometro": "",
                "cap": "00100",
                "localita": "ROMA",
                "siglaProvincia": "RM",
                "partitaIva": "12345678901",
                "codiceFiscale": "RSSMRA80A01H501Z",
                "sesso": "M",
                "dataNascita": date(1980, 1, 1),
                "comuneNascita": "ROMA",
                "provinciaNascita": "RM",
                "comuneDomicilio": "ROMA",
                "dataValidDoc": date(2026, 1, 1),
                "pec": "",
                "timestampInsStato": datetime(2026, 9, 10, 10, 0, 0)
            },
            {
                "gestione": "1",
                "codiceAtto": "ATTO-001",
                "codiceAnag": "I",
                "cognome": "ROSSI",
                "nome": "MARIO",
                "indAnagrafeTrib": "VIA VECCHIA 1",
                "siglaProvAnagrafeTrib": "RM",
                "comuneAnagrafeTrib": "H501",
                "capAnagrafeTrib": "00100",
                "locAnagrafeTrib": "ROMA",
                "indirizzo": "VIA VECCHIA 1",
                "numeroCivico": "1",
                "letteraCivico": "",
                "numeroChilometro": "",
                "cap": "00100",
                "localita": "ROMA",
                "siglaProvincia": "RM",
                "partitaIva": "12345678901",
                "codiceFiscale": "RSSMRA80A01H501Z",
                "sesso": "M",
                "dataNascita": date(1980, 1, 1),
                "comuneNascita": "ROMA",
                "provinciaNascita": "RM",
                "comuneDomicilio": "ROMA",
                "dataValidDoc": date(2026, 1, 1),
                "pec": "",
                "timestampInsStato": datetime(2026, 9, 1, 9, 0, 0)
            }
        ]

    def dataset(self, table_name: str) -> MockQueryBuilder:
        return MockQueryBuilder(table_name, self)

    def get_table_map(self, table_name: str) -> MockTableMap:
        return MockTableMap(table_name)

    def fetch(self, q: dict, depth: int = 0) -> list:
        self.queries_executed.append(q)
        tbl = q["table"]

        BatchLogger.debug("DB-SELECT", f"SQL: {q['sql']}", depth=depth)
        if q.get("params"):
            BatchLogger.debug("PARAMS", str(q["params"]), depth=depth + 1)

        result_rows = []

        if q.get("is_count"):
            if tbl == "ADCTET17":
                result_rows = [{"COUNT": 1}]
            elif tbl == "ADCFRT01":
                sql_low = str(q.get("sql", "")).lower()
                if "maxprg" in sql_low or "having" in sql_low or "count_subquery" in str(q).lower():
                    result_rows = [{"COUNT": 0}]
                elif "where_exists" in sql_low or "exists" in sql_low or "codicefiscale" in sql_low:
                    result_rows = [{"COUNT": 1}]
                else:
                    result_rows = [{"COUNT": 1}]
            else:
                result_rows = [{"COUNT": 0}]

        elif tbl == "ADCFRT18":
            result_rows = [{
                "dcon": date(2026, 9, 22),
                "diniinf": date(2026, 1, 1),
                "dfininf": date(2026, 8, 31),
                "dinifor": date(2026, 9, 1),
                "dfinfor": date(2026, 12, 31),
                "fstfor": "0",
                "tmsini": None,
                "tmsfin": None
            }]
        elif tbl == "ADCAVV02":
            result_rows = [{"codEsattoria": "50", "codiceBelfiore": "H501", "flagValidita": "0"}]
        elif tbl == "ADCAVV01":
            result_rows = [{"progAvviso": 12, "codConcessione": "350", "annoAvviso": "2026"}]
        elif tbl == "ADCFRT62":
            result_rows = [{"flagBlocco": "0", "timestampInsInfo": datetime(2026, 1, 1), "timestampVarInfo": None}]
        elif tbl == "ADCFRT01" and any("indAnagrafeTrib" in str(c) for c in q.get("columns", [])):
            result_rows = [{**self.t14_anagrafica[0], **self.t01_master}]
        elif tbl == "ADCFRT01":
            result_rows = [dict(self.t01_master)]
        elif tbl == "ADCFRT10":
            result_rows = [dict(self.t10_articoli[0])]
        elif tbl == "ADCFRT14":
            result_rows = [dict(self.t14_anagrafica[0])]

        BatchLogger.debug("RESULT", f"Estratte {len(result_rows)} riga/righe", depth=depth + 1, is_last=True)
        return result_rows

    def cursor_stream(self, q: dict, buffer_size: int = 500, depth: int = 0):
        self.queries_executed.append(q)
        tbl = q["table"]

        BatchLogger.debug("DB-CURSOR-OPEN", f"SQL: {q['sql']}", depth=depth)
        if q.get("params"):
            BatchLogger.debug("PARAMS", str(q["params"]), depth=depth + 1)

        result_stream = []

        if tbl == "ADCTET17":
            result_stream = [{
                "sede": "0100",
                "zona": "01",
                "codCentro": "01",
                "codServizio": "AV",
                "dataPre": date(2026, 9, 20)
            }]
        elif tbl == "ADCFRT01" and "DISTINCT" in q.get("sql", ""):
            result_stream = [{
                "gestione": "1",
                "sede": "0100",
                "zona": "01",
                "annoAvviso": 2026,
                "progAvviso": 101
            }]
        elif tbl == "ADCFRT01" and any("codTributoCnc" in str(c) for c in q.get("columns", [])):
            for art in self.t10_articoli:
                result_stream.append({**self.t01_master, **art})
        elif tbl == "ADCFRT01" and any("indAnagrafeTrib" in str(c) or "indirizzo" in str(c) for c in q.get("columns", [])):
            for anag in self.t14_anagrafica:
                result_stream.append({**self.t01_master, **anag})
        elif tbl == "ADCFRT01":
            result_stream = [dict(self.t01_master)]
        elif tbl == "ADCFRT10":
            result_stream = [dict(a) for a in self.t10_articoli]

        yield result_stream
        BatchLogger.debug("RESULT", f"Cursore DB2 chiuso. Record totali letti nello stream: {len(result_stream)}", depth=depth + 1, is_last=True)

    def execute_mutation(self, mut: dict, depth: int = 0) -> int:
        self.mutations_executed.append(mut)
        BatchLogger.debug("DB-MUTATION", f"[DB2] SQL: {mut['sql']}", depth=depth)
        if mut.get("params"):
            BatchLogger.debug("PARAMS", str(mut["params"]), depth=depth + 1)
        BatchLogger.debug("RESULT", "Righe impattate: 1", depth=depth + 1, is_last=True)
        return 1


def imposta_comodi_mock(ctx: FormazioneAvvisoContext, t01: dict, t10: dict) -> None:
    """Configura le variabili di Working-Storage di rottura come da specifica COBOL."""
    ctx.ws_cges = t01.get("gestione")
    ctx.ws_sede = t01.get("sede")
    ctx.ws_zona = t01.get("zona")
    ctx.ws_annoavv = t01.get("annoAvviso")
    ctx.ws_progavv = t01.get("progAvviso")
    ctx.ws_nparavv = t01.get("numPartitaAvviso")
    ctx.ws_tipoavv = t01.get("tipoAvviso")
    ctx.ws_cfis = t01.get("codiceFiscale")
    ctx.ws_cazi = t01.get("codAzienda")
    ctx.ws_periodo = t01.get("periodo")
    ctx.ws_periobi = t01.get("periodoBi")
    ctx.ws_frateiz = t01.get("flgRateizzazione")
    ctx.ws_cgesavv = t01.get("gestione")
    ctx.ws_sedeavv = t01.get("sede")


def test_full_pipeline():
    BatchLogger.setup_logger()
    engine = SpyDatabaseEngine()
    ctx = FormazioneAvvisoContext()

    ctx.ws_forzatura0 = "0"
    ctx.ws_forzatura1 = "1"
    ctx.ws_ispeavv = Decimal("6.90")
    ctx.imp_comodi_key = lambda row_t01, row_t10: imposta_comodi_mock(ctx, row_t01, row_t10)

    # 1. STEP 1: STATO-FORMAZIONE
    step1 = StatoFormazioneStep(engine)
    step1.execute(ctx)

    # 2. STEP 2: GESTIONE-RIPARTENZE
    step2 = GestioneRipartenzeStep(engine)
    step2.execute(ctx)

    # 3. STEP 3: PIPELINE PRINCIPALE CURJOI-1 / CURJOI-2
    step3 = ElaborazioneCurjoi1Step(engine)
    step3.execute(ctx)

    # =========================================================================
    # RIEPILOGHI FINALI E VERIFICHE DI CONTROLLO
    # =========================================================================
    sys.stdout.write("\n" + "=" * 115 + "\n")
    sys.stdout.write(f" [A] TUTTE LE QUERY 'SELECT' COMPILATE IN AUTOMATICO ({len(engine.queries_executed)} totali)\n")
    sys.stdout.write("=" * 115 + "\n")
    for idx, q in enumerate(engine.queries_executed, start=1):
        sys.stdout.write(f"\n  [{idx:02d}] TABELLA: {q['table']}\n")
        sys.stdout.write(f"       SQL: {q['sql']}\n")
    sys.stdout.flush()

    sys.stdout.write("\n" + "=" * 115 + "\n")
    sys.stdout.write(f" [B] TUTTE LE MUTAZIONI 'UPDATE' / 'INSERT' GENERATE ({len(engine.mutations_executed)} totali)\n")
    sys.stdout.write("=" * 115 + "\n")
    for idx, m in enumerate(engine.mutations_executed, start=1):
        sys.stdout.write(f"\n  [{idx:02d}] TIPO: {m['type']} | TABELLA: {m['table']}\n")
        sys.stdout.write(f"       SQL: {m['sql']}\n")
    sys.stdout.flush()

    # Estrazione importo caricato in ADCFRT03 per validazione contabile sicura
    tributi_inseriti_t03 = None
    for m in engine.mutations_executed:
        if m["table"] == "ADCFRT03":
            tributi_inseriti_t03 = m["data"].get("impCaricoCartella")

    sys.stdout.write("\n" + "=" * 115 + "\n")
    sys.stdout.write(" [C] VERIFICA DEI PASSAGGI DATI CHIAVE SUL CONTESTO (ctx)\n")
    sys.stdout.write("=" * 115 + "\n")
    sys.stdout.write(f"  - Belfiore estratto da CNTRL-TAB14   : {getattr(ctx, 'ws_codcomune', 'N/D')}\n")
    sys.stdout.write(f"  - Codice Esattoria Base / Avviso (+300): {getattr(ctx, 'ws_cesa', 'N/D')} / {getattr(ctx, 'ws_cesaavv', 'N/D')}\n")
    sys.stdout.write(f"  - Coordinate Carico Ruolo             : Anno={getattr(ctx, 'ws_annoruo', 'N/D')} | Prog={getattr(ctx, 'ws_nprgruo', 'N/D')} | Chk={getattr(ctx, 'ws_nchkruo', 'N/D')}\n")
    sys.stdout.write(f"  - IDENTIFICATIVO FINALE A 20 CRT      : {getattr(ctx, 'ws_idavvruo', 'N/D')}\n")
    sys.stdout.write(f"  - Totale Tributi Validato (da T03)    : {tributi_inseriti_t03}\n")
    sys.stdout.flush()

    tabelle_inserite = [m["table"] for m in engine.mutations_executed if m["type"] == "INSERT"]
    assert "ADCFRT01" in tabelle_inserite, "Manca INSERT spese su ADCFRT01"
    assert "ADCFRT10" in tabelle_inserite, "Manca INSERT spese su ADCFRT10"
    assert "ADCFRT14" in tabelle_inserite, "Manca INSERT spese su ADCFRT14"
    assert "ADCFRT03" in tabelle_inserite, "Manca INSERT testata su ADCFRT03"

    assert tributi_inseriti_t03 == Decimal("1090.00"), f"Totale tributi incongruo: {tributi_inseriti_t03} (atteso: 1090.00)"
    assert len(getattr(ctx, 'ws_idavvruo', '')) == 20, f"Lunghezza ID cartella non conforme"

    sys.stdout.write("\n  >>> TUTTE LE QUERY E LE MUTAZIONI SONO STATE COMPILATE ED ESEGUITE CON SUCCESSO! <<<\n")
    sys.stdout.write("=" * 115 + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    test_full_pipeline()