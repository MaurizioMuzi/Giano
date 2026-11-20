# processes/invio_ruoli_AdER/steps/step_gestione_R5A.py
from datetime import datetime, date
from typing import Optional, Any, Dict
from decimal import Decimal

from core.batch_logger import BatchLogger
from processes.invio_ruoli_AdER.context import InvioRuoliAdREContext


class GestioneR5AStep:
    def __init__(self, engine):
        self.engine = engine

    def execute_controllo_flusso(self, ctx: InvioRuoliAdREContext, row_t02: dict, depth: int = 3) -> None:
        anno_num_ruolo = f"{str(ctx.ws_arifruo_t02 or 0).zfill(4)}{str(ctx.ws_nruo_t02 or 0).zfill(6)}"

        # 1. Lettura ADCFRT01 per recupero dati relativi a CGES, CATT e chiave avviso
        self._db_fetch_cges_t01(ctx, depth=depth + 1)
        if ctx.indic_errore == "X":
            return

        # 2. Lettura ADCFRT10 per recupero data fine calcolo (DFINCAL)
        self._db_fetch_fincal_t10(ctx, depth=depth + 1)
        if ctx.indic_errore == "X":
            return

        dt_fincal = self._to_date(ctx.ws_dataFineCalc)
        ctx.ws_dt_fincal = int(dt_fincal.strftime("%Y%m%d")) if dt_fincal else 0

        # 3. Lettura ADCAVV12 per recupero dati della comunicazione (DLETT, dirigente, ecc.)
        self._db_fetch_comunicazioni(ctx, depth=depth + 1)
        if ctx.indic_errore == "X":
            return

        dt_lett = self._to_date(ctx.ws_dlett)
        ctx.ws_dtvisto = int(dt_lett.strftime("%Y%m%d")) if dt_lett else 0

        # Composizione WS-UFFICIO (CSED + CZON + CCOP = 6 char)
        sede_raw = str(row_t02.get("sede") or "").strip()
        zona_raw = str(row_t02.get("zona") or "").strip()
        cop_raw = str(row_t02.get("codCentro") or "").strip()

        sedeap = sede_raw.zfill(2)[-2:] if sede_raw.isdigit() else sede_raw.ljust(2, "0")[:2]
        zonap = zona_raw.zfill(2)[-2:] if zona_raw.isdigit() else zona_raw.ljust(2, "0")[:2]
        copap = cop_raw.zfill(2)[-2:] if cop_raw.isdigit() else cop_raw.ljust(2, "0")[:2]
        ws_ufficio = f"{sedeap}{zonap}{copap}"

        # 4. Lettura CDCFRT09 per recupero dati relativi ai non ceduti
        self._db_fetch_noceduti_t09(ctx, depth=depth + 1)
        if ctx.indic_errore == "X":
            return

        fres_t09 = str(getattr(ctx, "ws_fres_t09", "") or "").strip()
        tipo_iscriz = "5" if fres_t09 in ("Z", "A") else "4"

        # Incremento progressivi record R5A e file
        ctx.ws_tot_r3z_r5a += 1
        ctx.ws_prg_file += 1

        payload = {
            "progRecord": ctx.ws_prg_file,
            "codEnteImpos": 2,
            "codAmbito": ctx.ws_cesa_t02,
            "annoNumRuolo": anno_num_ruolo,
            "tipoUfficio": "0",
            "codUfficio": ws_ufficio,
            "specieRuolo": "1",
            "tipoIscriz": tipo_iscriz,
            "flagCartel": "8",
            "tasso": 0,
            "dtVisto": ctx.ws_dtvisto,
            "cognomeRespProc": ctx.ws_scogn_dir or "",
            "nomeRespProc": ctx.ws_snom_dir or "",
            "dataFineCalcolo": ctx.ws_dt_fincal,
            "codConv": 0,
            "dtVarConv": 0,
            "numDtRiscos": "0" * 36,
            "dtScad1Rata": 0,
            "flagEscAgo": 0,
            "codAmbitoAvvisi": 0,
            "annoNumAvvisi": 0
        }

        # Esempio chiusura execute_controllo_flusso in step_gestione_R5A.py (depth: int = 2)
        if ctx.writer is not None:
            ctx.writer.write("R5A", payload)
            BatchLogger.info(
                "RECORD-R5A",
                f"Scritto record R5A | PRG={ctx.ws_prg_file} | RUOLO={anno_num_ruolo} | TIPO_ISCR={tipo_iscriz}",
                depth=depth,
                is_last=True
            )

    def _db_fetch_cges_t01(self, ctx: InvioRuoliAdREContext, depth: int) -> Optional[Dict[str, Any]]:
        """
        Accesso atomico DB: recupera gestione, codiceAtto, codEsattoriaAvviso,
        annoCarico, numCarico e numChkCarico da ADCFRT01 per (CESA, ARIFRUO, NRUO).
        """
        t01_map = self.engine.get_table_map("ADCFRT01")

        try:
            query_t01 = (
                self.engine.dataset("ADCFRT01")
                .select(
                    "gestione",
                    "codiceAtto",
                    "codEsattoriaAvviso",
                    "annoCarico",
                    "numCarico",
                    "numChkCarico"
                )
                .filter_by("codEsattoria", "=", ctx.ws_cesa_t02)
                .filter_by("annoRifRuolo", "=", ctx.ws_arifruo_t02)
                .filter_by("numRuolo", "=", ctx.ws_nruo_t02)
                .with_uncommitted_read()
                .limit(1)
                .compile_select()
            )
            rows = self.engine.fetch(query_t01, depth=depth)

            if not rows:
                ctx.row_t01 = {}
                ctx.ws_cges = None
                ctx.ws_catt = ""
                ctx.ws_cesaavv = 0
                ctx.ws_acar = 0
                ctx.ws_ncar = 0
                ctx.ws_nchkcar = 0
                return None

            row_t01 = t01_map.normalize(rows[0])
            ctx.row_t01 = row_t01
            ctx.ws_cges = row_t01.get("gestione")
            ctx.ws_catt = row_t01.get("codiceAtto") or ""
            ctx.ws_cesaavv = row_t01.get("codEsattoriaAvviso") or 0
            ctx.ws_acar = row_t01.get("annoCarico") or 0
            ctx.ws_ncar = row_t01.get("numCarico") or 0
            ctx.ws_nchkcar = row_t01.get("numChkCarico") or 0

            return row_t01

        except Exception as err:
            BatchLogger.error(
                "DB-FETCH-CGES-T01-ERR",
                f"Errore DB durante recupero dati da ADCFRT01 "
                f"[CESA={ctx.ws_cesa_t02}, ARIFRUO={ctx.ws_arifruo_t02}, NRUO={ctx.ws_nruo_t02}]: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            return None

    def _db_fetch_fincal_t10(self, ctx: InvioRuoliAdREContext, depth: int) -> Optional[Dict[str, Any]]:
        """
        Accesso atomico DB: recupera DFINCAL (dataFineCalc) da ADCFRT10 per (CGES, CATT).
        """
        t10_map = self.engine.get_table_map("ADCFRT10")

        try:
            query_t10 = (
                self.engine.dataset("ADCFRT10")
                .select("dataFineCalc")
                .filter_by("gestione", "=", ctx.ws_cges)
                .filter_by("codiceAtto", "=", ctx.ws_catt)
                .with_uncommitted_read()
                .limit(1)
                .compile_select()
            )
            rows = self.engine.fetch(query_t10, depth=depth)

            if not rows:
                ctx.row_t10 = {}
                ctx.ws_dataFineCalc = None
                ctx.indic_errore = "X"
                BatchLogger.error(
                    "DB-FETCH-DFINCAL-T10-NOTFOUND",
                    f"Nessun record trovato su ADCFRT10 [ARCHIVIO=ADCFRT10 | FUNZIONE=SELECT | "
                    f"SQLCODE=100 | CGES={ctx.ws_cges}, CATT={ctx.ws_catt}]",
                    depth=depth
                )
                return None

            row_t10 = t10_map.normalize(rows[0])
            ctx.row_t10 = row_t10
            ctx.ws_dataFineCalc = row_t10.get("dataFineCalc")

            return row_t10

        except Exception as err:
            BatchLogger.error(
                "DB-FETCH-DFINCAL-T10-ERR",
                f"Errore DB durante recupero dati da ADCFRT10 "
                f"[CGES={ctx.ws_cges}, CATT={ctx.ws_catt}]: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            return None

    def _db_fetch_comunicazioni(self, ctx: InvioRuoliAdREContext, depth: int) -> Optional[dict[str, Any]]:
        """
        Accesso atomico DB: recupera le informazioni di comunicazione da ADCAVV12
        per la chiave (DCON, IDAVV, CSTALET = '2').
        """
        tv12_map = self.engine.get_table_map("ADCAVV12")

        cesaavv = str(int(ctx.ws_cesaavv or 0)).zfill(3)[-3:]
        acar = str(int(ctx.ws_acar or 0)).zfill(4)[-4:]
        ncar = str(int(ctx.ws_ncar or 0)).zfill(8)[-8:]
        nchkcar = str(int(ctx.ws_nchkcar or 0)).zfill(2)[-2:]
        nzero = "000"

        idavv = f"{cesaavv}{acar}{ncar}{nchkcar}{nzero}"
        ctx.ws_idavv12 = idavv
        dcon_date = self._to_date(ctx.ws_dcon)

        try:
            query_tv12 = (
                self.engine.dataset("ADCAVV12")
                .select(
                    "dataLettera",
                    "flgRateizzazione",
                    "statoLettera",
                    "impAvviso",
                    "identificativoAvviso",
                    "nomeDirSede",
                    "cognomeDirSede",
                    "pec",
                    "codRav"
                )
                .filter_by("dcon", "=", dcon_date)
                .filter_by("identificativoAvviso", "=", ctx.ws_idavv12)
                .filter_by("statoLettera", "=", "2")
                .with_uncommitted_read()
                .limit(1)
                .compile_select()
            )
            rows = self.engine.fetch(query_tv12, depth=depth)

            if not rows:
                ctx.row_tv12 = {}
                ctx.ws_dlett = None
                ctx.ws_snom_dir = None
                ctx.ws_scogn_dir = None
                return None

            row_tv12 = tv12_map.normalize(rows[0])
            ctx.row_tv12 = row_tv12
            ctx.ws_dlett = row_tv12.get("dataLettera")
            ctx.ws_frateiz = row_tv12.get("flgRateizzazione")
            ctx.ws_cstalet = row_tv12.get("statoLettera")
            ctx.ws_itotdeb = row_tv12.get("impAvviso") or Decimal("0")
            ctx.ws_identificativoAvviso = row_tv12.get("identificativoAvviso")
            ctx.ws_snom_dir = row_tv12.get("nomeDirSede")
            ctx.ws_scogn_dir = row_tv12.get("cognomeDirSede")
            ctx.ws_sindpec = row_tv12.get("pec")
            ctx.ws_codRav = row_tv12.get("codRav")

            return row_tv12

        except Exception as err:
            BatchLogger.error(
                "DB-FETCH-COMUNICAZIONI-TV12-ERR",
                f"Errore DB durante recupero comunicazioni da ADCAVV12 "
                f"[DCON={dcon_date}, IDAVV={ctx.ws_idavv12}, CSTALET=2]: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            return None

    def _db_fetch_noceduti_t09(self, ctx: InvioRuoliAdREContext, depth: int) -> Optional[Dict[str, Any]]:
        """
        Accesso atomico DB: recupera codEsattoria, annoRif, numRuolo e flgResiduo
        da ADCFRT09 per la chiave ruolo corrente (CESA, ARIFRUO, NRUO).
        """
        t09_map = self.engine.get_table_map("ADCFRT09")

        try:
            query_t09 = (
                self.engine.dataset("ADCFRT09")
                .select(
                    "codEsattoria",
                    "annoRif",
                    "numRuolo",
                    "flgResiduo"
                )
                .filter_by("codEsattoria", "=", ctx.ws_cesa_t02)
                .filter_by("annoRif", "=", ctx.ws_arifruo_t02)
                .filter_by("numRuolo", "=", ctx.ws_nruo_t02)
                .order_by("codEsattoria", "annoRif", "numRuolo")
                .with_uncommitted_read()
                .limit(1)
                .compile_select()
            )
            rows = self.engine.fetch(query_t09, depth=depth)

            if not rows:
                ctx.row_t09 = {}
                ctx.ws_fres_t09 = ""
                return None

            row_t09 = t09_map.normalize(rows[0])
            ctx.row_t09 = row_t09
            ctx.ws_cesa_t09 = row_t09.get("codEsattoria")
            ctx.ws_arifruo_t09 = row_t09.get("annoRif") or 0
            ctx.ws_nruo_t09 = row_t09.get("numRuolo") or 0
            ctx.ws_fres_t09 = row_t09.get("flgResiduo") or ""

            return row_t09

        except Exception as err:
            BatchLogger.error(
                "DB-FETCH-NOCEDUTI-T09-ERR",
                f"Errore DB durante recupero dati da ADCFRT09 "
                f"[CESA={ctx.ws_cesa_t02}, ARIFRUO={ctx.ws_arifruo_t02}, NRUO={ctx.ws_nruo_t02}]: {err}",
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