# processes/formazione_avviso/step_statistiche.py
from typing import List, Any
from core.batch_logger import BatchLogger
from .context import FormazioneAvvisoContext


class StatisticheStep:
    """
    Reingegnerizza il cursore CURT17 e la stampa del report statistico a fine elaborazione:
      DECLARE CURT17 CURSOR FOR
      SELECT COUNT(*), CDAS FROM ADCTET17 GROUP BY CDAS WITH UR FOR FETCH ONLY
    """

    def __init__(self, engine):
        self.engine = engine


    def execute(self, ctx: FormazioneAvvisoContext, depth: int = 1) -> None:
        BatchLogger.info("CURT17-STAT", "Elaborazione statistiche finali per stato servizio (CURT17)", depth=depth)

        try:
            rows = self._db_fetch_statistiche_curt17(depth=depth + 1)

            if not rows:
                BatchLogger.info("CURT17-STAT", "Nessun dato statistico disponibile su ADCTET17", depth=depth + 1)
                return

            BatchLogger.info("STAT-REP", "===================================================", depth=depth + 1)
            BatchLogger.info("STAT-REP", "TOTALE DELLE SEDI ELABORATE PER LA FORMAZIONE RUOLI", depth=depth + 1)
            BatchLogger.info("STAT-REP", "===================================================", depth=depth + 1)
            BatchLogger.info("STAT-REP", "TOT.    C.STATO", depth=depth + 1)
            BatchLogger.info("STAT-REP", "----------------", depth=depth + 1)

            for row in rows:
                tot_conta = row.get("TOT_CONTA") or row.get("COUNT") or list(row.values())[0]
                cdas_val = row.get("codServizio") or row.get("CDAS") or list(row.values())[1]

                det_line = f"{str(tot_conta).ljust(7)} {str(cdas_val).ljust(8)}"
                BatchLogger.info("STAT-DET", det_line, depth=depth + 1)

            BatchLogger.info("STAT-REP", "----------------", depth=depth + 1, is_last=True)

        except Exception as err:
            BatchLogger.error(
                "CURT17-STAT",
                f"Errore critico durante l'elaborazione del report statistico CURT17: {err}",
                depth=depth
            )

            ctx.indic_errore = "X"
            return -1


    # =========================================================================
    # ACCESSI AL DATABASE (ISOLATI CON TRY-EXCEPT PUNTUALI)
    # =========================================================================
    def _db_fetch_statistiche_curt17(self, depth: int) -> List[Any]:
        """Accesso atomico DB: esecuzione query raggruppata su ADCTET17 (CURT17)."""
        try:
            query_curt17 = (
                self.engine.dataset("ADCTET17")
                .select_raw("COUNT(*) AS TOT_CONTA")
                .select("codServizio")
                .group_by("codServizio")
                .with_uncommitted_read()
                .compile_select()
            )
            return self.engine.fetch(query_curt17, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "DB-FETCH-CURT17-ERR",
                f"Errore DB durante la fetch di raggruppamento per statistiche su ADCTET17: {err}",
                depth=depth
            )

            ctx.indic_errore = "X"
            return -1