# processes/invio_ruoli_AdER/steps/step_gestione_R3A.py
from datetime import datetime, date
from typing import Optional, Any

from core.batch_logger import BatchLogger
from processes.invio_ruoli_AdER.context import InvioRuoliAdREContext


class GestioneR3AStep:
    def __init__(self, engine):
        self.engine = engine

    def execute_controllo_flusso(self, ctx: InvioRuoliAdREContext, row_t02: dict, depth: int = 3) -> None:
        data_con = self._to_date(ctx.ws_dcon)
        oggi = date.today()

        # Se ws_id_file non fosse già stato valorizzato da _db_fetch_max_t11, lo calcolo qui
        if not ctx.ws_id_file:
            ws_afil = str(data_con.year) if data_con else str(oggi.year)
            cesa_str = str(ctx.ws_cesa_t02 or 0).zfill(3)
            afil_str = ws_afil.zfill(4)
            nfil_str = str(ctx.ws_ctr_nfil or 0).zfill(5)
            ctx.ws_id_file = f"RVT00002{cesa_str}{afil_str}{nfil_str}"

        # Determinazione data creazione effettiva
        if data_con is not None and oggi >= data_con:
            data_con_db = self._db_fetch_dist_t02(ctx, depth=depth + 1)
            if ctx.indic_errore == "X":
                return
            dt_creazione = data_con_db if data_con_db is not None else oggi
        else:
            dt_creazione = oggi

        # [PUNTO 4] Manteniamo date pulite (o interi AAAAMMGG se R3A.json usa logical_type="int")
        # Passando l'oggetto date direttamente a RecordFormatter:
        # - se R3A.json ha logical_type="int", lo formatta in AAAAMMGG (es. 20261117)
        # - se R3A.json ha logical_type="date", lo formatta in GGMMAAAA (es. 17112026)
        dt_consegna = data_con if data_con is not None else oggi

        ctx.ws_dt_x = int(dt_creazione.strftime("%Y%m%d"))
        ctx.ws_data_creazione = ctx.ws_dt_x
        ctx.ws_data_consegna = int(dt_consegna.strftime("%Y%m%d"))

        payload = {
            "codEnteImpos": 2,
            "codAmbito": ctx.ws_cesa_t02,
            "idFile": ctx.ws_id_file,
            "dataCreazione": dt_creazione,
            "dataConsegna": dt_consegna,
            "codDivOp": "EUR" if ctx.ws_feur_t02 == "1" else "ITL",
        }

        if ctx.writer is not None:
            ctx.writer.write("R3A", payload)
            BatchLogger.info(
                "RECORD-R3A",
                f"Scritto record R3A | ID_FILE={ctx.ws_id_file} | DIVISA={payload['codDivOp']}",
                depth=depth,
                is_last=True
            )

    def _db_fetch_dist_t02(self, ctx: Any, depth: int) -> Optional[date]:
        """
        Accesso atomico DB: recupera DISTINCT(dataConsegna - 1 DAY) da ADCFRT02
        e restituisce la data risultante (oppure None se non trovata).
        """
        ds = self.engine.dataset("ADCFRT02")
        dcon_expr = ds.expr().date_sub_days("dataConsegna", days=1, alias="DCON_MENO_1").compile()

        try:
            query_t02 = (
                ds.distinct()
                .select_raw(dcon_expr)
                .filter_by("dataConsegna", "=", ctx.ws_dcon)
                .with_uncommitted_read()
                .limit(1)
                .compile_select()
            )
            rows = self.engine.fetch(query_t02, depth=depth)

            if not rows:
                return None

            first_row = rows[0]
            raw_val = (
                first_row.get("DCON_MENO_1")
                if isinstance(first_row, dict)
                else first_row[0]
            )
            if raw_val is None and isinstance(first_row, dict):
                raw_val = next(iter(first_row.values()), None)

            return self._to_date(raw_val)

        except Exception as err:
            BatchLogger.error(
                "DB-FETCH-DIST-T02-ERR",
                f"Errore DB durante recupero DISTINCT(dataConsegna - 1 DAY) da ADCFRT02 [DCON={ctx.ws_dcon}]: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            return None

    @staticmethod
    def _to_date(val) -> Optional[date]:
        if val is None:
            return None
        if isinstance(val, datetime):
            return val.date()
        if isinstance(val, date):
            return val
        s = str(val).strip()
        if not s or s in ("0", "00000000", "01.01.0001", "0001-01-01"):
            return None
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y%m%d"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Formato data non riconosciuto: {val}")