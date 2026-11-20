# processes/firma_ruoli/steps/steps.py
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import List, Any, Iterator
from processes.firma_ruoli.context import FirmaRuoliContext
from core.batch_logger import BatchLogger


class ElaborazioneCicloPrincipaleStep:
    """
    Reingegnerizzazione del paragrafo CICLO-CURJOI-2:
    Join tra ADCFRT01 e ADCFRT10 con gestione rottura e valorizzazione IMP-COMODI-KEY.
    """

    def __init__(self, engine):
        self.engine = engine


    def execute_record(self, ctx: FirmaRuoliContext, depth: int = 1, is_last_credit: bool = False) -> None:

        ctx.ws_cesa = 0
        ctx.ws_arifruo = 0
        ctx.ws_nruo = 0

        BatchLogger.info("OPEN-CUR1", "Apertura cursore sulla tabella ADCFRT02", depth=depth)
        t02_map = self.engine.get_table_map("ADCFRT02")

        try:
            # OPEN CUR1 + FETCH CUR1
            rows = self._db_fetch_cur1(ctx, depth= depth +1)
            if not rows:
                BatchLogger.error(
                    "CUR1-VUOTO",
                    "Nessun record valido in ADCFRT02. Nssun ruolo da elaborare.",
                    depth=depth,
                    is_last=True
                )
                raise RuntimeError("ATTENZIONE: NESSUNE RUOLO DA ELABORARE.")

            row = t02_map.normalize(rows[0])


        except Exception as err:
            BatchLogger.error(
                "CUR01-ERR",
                f"Errore durante l'elaborazione del cursore CUR1: {err}",
                depth=depth
            )
            if hasattr(self.engine, "rollback"):
                self.engine.rollback()
            ctx.indic_errore = "X"
            raise err


    # =========================================================================
    # ACCESSI AL DATABASE CUR1 (ISOLATI CON TRY-EXCEPT PUNTUALI)
    # =========================================================================
    def _db_fetch_cur1(self, ctx: FirmaRuoliContext, t02_map: Any, depth: int) -> List[Any]:
        """Accesso atomico DB: lettura tabella ADCFRT02."""
        try:
            query = (
                self.engine.dataset("ADCFRT02")
                .select(
                    "codStRuolo", "codEsattoria", "annoRif", "numRuolo", "sede", "zona", "codCentro",
                    "tipoRuolo", "codRuoloCoa", "dataFormazione", "dataConsegna", "flgEuro", "impTributo",
                    "impSanzione", "impInteressi", "impAltro", "impAggioAnticipato", "impAggioTot",
                    "impCarico", "impArrotondamento", "impImponibile", "aliqIva", "impIva", "dataVisto",
                    "codDipendente", "dataInvioCNC", "numRecRuolo", "numRecR5B", "numRecR7A",
                    "numRecR7B", "numRecR7C", "numRecR7D", "numRecR7E", "numRecR7G", "anno_rif_invio",
                    "num_file_invio", "dataTimbro", "anno_rif_timbro", "num_file_timbro", "dataTransStato",
                    "tasso", "numRecR7L"
                )
                .filter_by("codStRuolo", "=", "P")
                .filter_by("codEsattoria", ">=", ctx.ws_cesa)
                .filter_by("annoRif", ">=", ctx.ws_arifruo)
                .filter_by("numRuolo",">", ctx.ws_nruo)
                .order_by("codEsattoria", "annoRif", "numRuolo")
                .with_uncommitted_read()
                .compile_select()
            )
            return self.engine.fetch(query, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "DB-CUR1-ERR",
                f"Errore DB durante l'apertura cursore CUR1.: {err}",
                depth=depth
            )

            ctx.indic_errore = "X"
            raise
