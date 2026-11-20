# processes/invio_ruoli_AdER/steps/step_gestione_R5B.py
from decimal import Decimal
from typing import Any, Iterator, List

from core.batch_logger import BatchLogger
from processes.invio_ruoli_AdER.context import InvioRuoliAdREContext


class GestioneR5BStep:
    """
    Reingegnerizzazione del paragrafo COBOL IMPOSTA-CAMPI-R5B / CICLO-T09:
    Estrae 1..N righe da ADCFRT09 per la chiave ruolo (CESA, ARIFRUO, NRUO)
    e scrive un record posizionale R5B per ciascuna riga estratta.
    """

    def __init__(self, engine):
        self.engine = engine

    def execute_controllo_flusso(self, ctx: InvioRuoliAdREContext, row_t02: dict, depth: int = 2) -> None:
        ctx.indic_prima_volta_T09 = "X"
        t09_map = self.engine.get_table_map("ADCFRT09")
        anno_num_ruolo = f"{str(ctx.ws_arifruo_t02 or 0).zfill(4)}{str(ctx.ws_nruo_t02 or 0).zfill(6)}"

        almeno_un_record = False
        r5b_emessi_ruolo = 0

        try:
            for chunk in self._db_stream_cur09(ctx, depth=depth + 1):
                for raw_row in chunk:
                    almeno_un_record = True
                    ctx.indic_prima_volta_T09 = " "

                    row_t09 = t09_map.normalize(raw_row)
                    ctx.ws_cesa_t09 = row_t09.get("codEsattoria")
                    ctx.ws_arifruo_t09 = row_t09.get("annoRif")
                    ctx.ws_nruo_t09 = row_t09.get("numRuolo")
                    ctx.ws_ctrbcnc_t09 = row_t09.get("codTributoCnc")
                    ctx.ws_arifcon_t09 = row_t09.get("annoRifCont")
                    ctx.ws_nrat_t09 = row_t09.get("numRate")
                    ctx.ws_crat_t09 = row_t09.get("codRata")
                    ctx.ws_fres_t09 = row_t09.get("flgResiduo")
                    ctx.ws_itrb_t09 = row_t09.get("impTributo") or 0
                    ctx.ws_nart_t09 = row_t09.get("numArticoli") or 0
                    ctx.ws_iaggant_t09 = row_t09.get("impAggioAnt") or 0
                    ctx.ws_iaggtot_t09 = row_t09.get("impAggioTot") or 0
                    ctx.ws_iarr_t09 = row_t09.get("impArrotondamento") or 0
                    ctx.ws_icrc_t09 = row_t09.get("impCarico") or 0

                    # Incremento contatori R3Z e progressivo fisico record di file
                    #ctx.ws_tot_r3z_r5b += 1
                    ctx.ws_prg_file += 1
                    r5b_emessi_ruolo += 1

                    # Composizione WS-UFFICIO (CSED + CZON + CCOP = 6 char)
                    sede_raw = str(row_t02.get("sede") or "").strip()
                    zona_raw = str(row_t02.get("zona") or "").strip()
                    cop_raw = str(row_t02.get("codCentro") or "").strip()

                    sedeap = sede_raw.zfill(2)[-2:] if sede_raw.isdigit() else sede_raw.ljust(2, "0")[:2]
                    zonap = zona_raw.zfill(2)[-2:] if zona_raw.isdigit() else zona_raw.ljust(2, "0")[:2]
                    copap = cop_raw.zfill(2)[-2:] if cop_raw.isdigit() else cop_raw.ljust(2, "0")[:2]
                    ws_ufficio = f"{sedeap}{zonap}{copap}"

                    # Composizione TIPO-IMPOSTA ("I0" + CGES = 3 char)
                    cgesap = ctx.ws_cges
                    ci0ap = "I0"
                    ws_tipoImposta = f"{ci0ap}{cgesap}"

                    # valorizzazione codice ente beneficiario - tipo ufficio beneficiario - codice ufficio beneficiario
                    cod_ente_ben = ""
                    tipo_uff_ben = ""
                    cod_uff_ben = ""
                    flag_ass_iva = ""

                    if ctx.ws_fres_t09 == "Z" or ctx.ws_fres_t09 == "A":
                        cod_ente_ben = 4
                        tipo_uff_ben = ""
                        cod_uff_ben = ""
                        flag_ass_iva = "1"
                    else:
                        cod_ente_ben = 2
                        tipo_uff_ben = "0"
                        cod_uff_ben = ""
                        flag_ass_iva = "2"

                    # valorizzazione numero rate - cadenza rate
                    num_rate = 1
                    cadenza_rate = "000"

                    if ctx.ws_cruo == 2:
                        num_rate = ctx.ws_nrat_t09
                        cadenza_rate = ctx.ws_crat_t09

                    # Nota: allinea le chiavi del payload ai nomi campo definiti in R5B.json
                    payload = {
                        "progRecord": ctx.ws_prg_file,
                        "codEnteImpos": 2,
                        "codAmbito": ctx.ws_cesa_t02,
                        "annoNumRuolo": anno_num_ruolo,
                        "tipoUfficio": "0",
                        "codUfficio": ws_ufficio,
                        "annoImposta": ctx.ws_arifcon_t09,
                        "tipoImposta": ws_tipoImposta,
                        "codTrb": ctx.ws_ctrbcnc_t09,
                        "numRate": num_rate,
                        "cadenzaRate": cadenza_rate,
                        "somImpImposta": ctx.ws_itrb_t09,
                        "somAggAnt": ctx.ws_iaggant_t09,
                        "somImpAgg": ctx.ws_iaggtot_t09,
                        "somCarTrb": ctx.ws_icrc_t09,
                        "competResidui": " ",
                        "capo": 0,
                        "capitolo": 0,
                        "articolo": 0,
                        "codEnteBenef": cod_ente_ben,
                        "tipoUffBenef": tipo_uff_ben,
                        "codUffBenef": cod_uff_ben,
                        "flagAssIva": flag_ass_iva
                    }

                    if ctx.writer is not None:
                        ctx.writer.write("R5B", payload)

            if not almeno_un_record:
                BatchLogger.warn(
                    "CUR09-VUOTO",
                    f"Nessun record R5B trovato su ADCFRT09 per ruolo "
                    f"[CESA={ctx.ws_cesa_t02}, ARIFRUO={ctx.ws_arifruo_t02}, NRUO={ctx.ws_nruo_t02}]",
                    depth=depth,
                    is_last=True
                )
            else:
                BatchLogger.info(
                    "RECORD-R5B",
                    f"Scritti {r5b_emessi_ruolo} record R5B | RUOLO={anno_num_ruolo} | PRG_FINO_A={ctx.ws_prg_file}",
                    depth=depth,
                    is_last=True
                )

        except Exception as err:
            BatchLogger.error(
                "GESTIONE-R5B-ERR",
                f"Errore durante l'elaborazione dei record R5B per ruolo "
                f"[CESA={ctx.ws_cesa_t02}, ARIFRUO={ctx.ws_arifruo_t02}, NRUO={ctx.ws_nruo_t02}]: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            raise err

    def _db_stream_cur09(self, ctx: InvioRuoliAdREContext, depth: int) -> Iterator[List[Any]]:
        """
        Accesso atomico DB: cursore streaming su ADCFRT09 per (CESA, ARIFRUO, NRUO).
        """
        try:
            query_t09 = (
                self.engine.dataset("ADCFRT09")
                .select(
                    "codEsattoria", "annoRif", "numRuolo", "codTributoCnc",
                    "annoRifCont", "numRate", "codRata", "flgResiduo",
                    "impTributo", "numArticoli", "impAggioAnt", "impAggioTot",
                    "impArrotondamento", "impCarico"
                )
                .filter_by("codEsattoria", "=", ctx.ws_cesa_t02)
                .filter_by("annoRif", "=", ctx.ws_arifruo_t02)
                .filter_by("numRuolo", "=", ctx.ws_nruo_t02)
                .order_by(
                    "codEsattoria", "annoRif", "numRuolo", "codTributoCnc",
                    "annoRifCont", "numRate", "codRata", "flgResiduo"
                )
                .with_uncommitted_read()
                .compile_select()
            )
            return self.engine.cursor_stream(query_t09, buffer_size=500, depth=depth)

        except Exception as err:
            BatchLogger.error(
                "DB-STREAM-CUR09-ERR",
                f"Errore DB durante l'apertura cursore CUR09 su ADCFRT09 "
                f"[CESA={ctx.ws_cesa_t02}, ARIFRUO={ctx.ws_arifruo_t02}, NRUO={ctx.ws_nruo_t02}]: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            return iter([])