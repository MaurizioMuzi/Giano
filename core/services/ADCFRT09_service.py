# core/services/adcfrt09_service.py
from typing import List
from core.batch_logger import BatchLogger
from core.models.contex_PDC09WR1 import (
    AdCommarea,
    RigaTabella,
    codOperazAzione,
)


class ADCFRT09Service:
    """
    Reingegnerizzazione del sottoprogramma COBOL PDC09WR1 richiamato tramite COMMAREA.
    Gestisce le operazioni di persistenza (INSERT / UPDATE / DELETE) sulla tabella ADCFRT09.
    """

    def __init__(self, engine):
        self.engine = engine
        self.t09_map = self.engine.get_table_map("ADCFRT09")

    def call(self, commarea: AdCommarea, depth: int = 1) -> AdCommarea:
        """
        Punto di ingresso corrispondente a:
            CALL 'PDC09WR1' USING WS-AREA-PASS
        """
        try:
            self._operazioni_iniziali(commarea, depth=depth + 1)
            self._elaborazione(commarea, depth=depth + 1)
            self._operazioni_finali(commarea, depth=depth + 1)
        except Exception as ex:
            self._segnala_errore_critico(commarea, str(ex), depth=depth + 1)
        return commarea

    def _operazioni_iniziali(self, commarea: AdCommarea, depth: int) -> None:
        """Corrisponde al paragrafo OPERAZIONI-INIZIALI."""
        commarea.rc_esito = 0
        commarea.msg_errore = ""
        commarea.ad_output.codMessaggio = ""
        commarea.ad_output.numCelTot = 0
        commarea.ad_output.flgMre = " "
        # MOVE ZERO TO NLNGCEL OF AD OF COM-AREA
        commarea.ad_input.lunRiga = 0

    def _elaborazione(self, commarea: AdCommarea, depth: int) -> None:
        """Corrisponde ai paragrafi ELABORAZIONE e CICLO-ELABOR."""
        righe: List[RigaTabella] = commarea.ad_tabella.righe
        max_righe = min(len(righe), commarea.ad_input.numRighe or len(righe))

        for idx in range(max_righe):
            riga = righe[idx]
            azione = (riga.codOperaz or "").strip().upper()

            if azione == codOperazAzione.INSERIRE.value:
                self._insr_tab09(commarea, riga, depth=depth + 1)
                commarea.ad_output.numCelTot += 1
            elif azione == codOperazAzione.VARIARE.value:
                self._updt_tab09(commarea, riga, depth=depth + 1)
                commarea.ad_output.numCelTot += 1
            elif azione == codOperazAzione.CANCELLARE.value:
                self._delt_tab09(commarea, riga, depth=depth + 1)
                commarea.ad_output.numCelTot += 1
            else:
                self._segnala_log_002(commarea, riga, idx + 1, depth=depth + 1)
                break

            if commarea.rc_esito != 0:
                break

    def _insr_tab09(self, commarea: AdCommarea, riga: RigaTabella, depth: int) -> None:
        """Corrisponde al paragrafo INSR-TAB09."""
        try:
            data_insert = {
                "codEsattoria": riga.codEsattoria,
                "annoRiferimentoRuolo": riga.annoRif,
                "numRuolo": riga.numRuolo,
                "codTributoCnc": riga.codTributoCnc,
                "annoRiferimentoConcessione": riga.annoRifCont,
                "numRata": riga.numRate,
                "codRata": riga.codRata,
                "flgResiduo": riga.flgResiduo,
                "impTributo": riga.impTributo,
                "numArticoli": riga.numArticoli,
                "impAggioAnticipato": riga.impAggioAnt,
                "impAggioTotale": riga.impAggioTot,
                "impArrotondamento": riga.impArrotondamento,
                "impCarico": riga.impCarico,
            }
            query_ins = self.engine.dataset("ADCFRT09").compile_insert(data_insert)
            self.engine.execute_mutation(query_ins, depth=depth)
        except Exception as ex:
            self._segnala_log_001(commarea, "INSERT", str(ex), depth=depth)

    def _updt_tab09(self, commarea: AdCommarea, riga: RigaTabella, depth: int) -> None:
        """Corrisponde al paragrafo UPDT-TAB09."""
        try:
            dataset = self.engine.dataset("ADCFRT09")
            query_upd = (
                dataset
                .filter_by("codEsattoria", "=", riga.codEsattoria)
                .filter_by("annoRiferimentoRuolo", "=", riga.annoRif)
                .filter_by("numRuolo", "=", riga.numRuolo)
                .filter_by("codTributoCnc", "=", riga.codTributoCnc)
                .filter_by("annoRiferimentoConcessione", "=", riga.annoRifCont)
                .filter_by("numRata", "=", riga.numRate)
                .filter_by("codRata", "=", riga.codRata)
                .filter_by("flgResiduo", "=", riga.flgResiduo)
                .compile_update({
                    "impTributo": riga.impTributo,
                    "numArticoli": riga.numArticoli,
                    "impAggioAnticipato": riga.impAggioAnt,
                    "impAggioTotale": riga.impAggioTot,
                    "impArrotondamento": riga.impArrotondamento,
                    "impCarico": riga.impCarico,
                })
            )
            self.engine.execute_mutation(query_upd, depth=depth)
        except Exception as ex:
            self._segnala_log_001(commarea, "UPDATE", str(ex), depth=depth)

    def _delt_tab09(self, commarea: AdCommarea, riga: RigaTabella, depth: int) -> None:
        """Corrisponde al paragrafo DELT-TAB09."""
        try:
            dataset = self.engine.dataset("ADCFRT09")
            query_del = (
                dataset
                .filter_by("codEsattoria", "=", riga.codEsattoria)
                .filter_by("annoRiferimentoRuolo", "=", riga.annoRif)
                .filter_by("numRuolo", "=", riga.numRuolo)
                .filter_by("codTributoCnc", "=", riga.codTributoCnc)
                .filter_by("annoRiferimentoConcessione", "=", riga.annoRifCont)
                .filter_by("numRata", "=", riga.numRate)
                .filter_by("codRata", "=", riga.codRata)
                .filter_by("flgResiduo", "=", riga.flgResiduo)
                .compile_delete()
            )
            self.engine.execute_mutation(query_del, depth=depth)
        except Exception as ex:
            self._segnala_log_001(commarea, "DELETE", str(ex), depth=depth)

    def _operazioni_finali(self, commarea: AdCommarea, depth: int) -> None:
        """Corrisponde al paragrafo OPERAZIONI-FINALI."""
        # MOVE ZERO TO NCEL OF AD OF COM-AREA
        commarea.ad_input.numRighe = 0
        if commarea.rc_esito == 0:
            commarea.ad_output.flgMre = "K"
            commarea.ad_output.codMessaggio = "000000"

    def _segnala_log_001(self, commarea: AdCommarea, oper: str, errore: str, depth: int) -> None:
        """Corrisponde al paragrafo SEGNALA-LOG-001 (Errore DB SQL)."""
        commarea.rc_esito = 12
        commarea.ad_output.flgMre = "E"
        commarea.ad_output.codMessaggio = "EXX036"
        commarea.msg_errore = f"Errore DB durante {oper} su ADCFRT09: {errore}"
        BatchLogger.error("PDC09WR1", commarea.msg_errore, depth=depth)

    def _segnala_log_002(self, commarea: AdCommarea, riga: RigaTabella, indice: int, depth: int) -> None:
        """Corrisponde al paragrafo SEGNALA-LOG-002 (Valore errato in codOperaz)."""
        commarea.rc_esito = 8
        commarea.ad_output.flgMre = "E"
        commarea.ad_output.codMessaggio = "EXX036"
        commarea.msg_errore = f"Trovato valore errato in codOperaz = '{riga.codOperaz}' all'elemento {indice}"
        BatchLogger.error("PDC09WR1", commarea.msg_errore, depth=depth)

    def _segnala_errore_critico(self, commarea: AdCommarea, errore: str, depth: int) -> None:
        commarea.rc_esito = 16
        commarea.ad_output.flgMre = "E"
        commarea.ad_output.codMessaggio = "EXX036"
        commarea.msg_errore = f"Errore irreversibile: {errore}"
        BatchLogger.error("PDC09WR1-CRIT", commarea.msg_errore, depth=depth)