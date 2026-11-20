# processes/invio_ruoli_AdER/steps/steps.py
import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import List, Any, Iterator

from processes.invio_ruoli_AdER.context import InvioRuoliAdREContext
from core.batch_logger import BatchLogger
from core.record_formatter import RecordFormatter
from core.file_writer import FileWriter

from .step_gestione_R3A import GestioneR3AStep
from .step_calcola_ruoli import CalcolaRuoliStep


_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_RECORDS_DIR = os.path.join(_ROOT_DIR, "config", "mappings", "record")
_DEFAULT_OUTPUT_DIR = os.path.join(_ROOT_DIR, "output")


class ElaborazioneCicloPrincipaleStep:
    """
    Reingegnerizzazione del paragrafo CICLO-T02:
    Gestione rottura concessione (CESA/FEUR), apertura/chiusura flussi e valorizzazione record.
    """

    def __init__(self, engine):
        self.engine = engine
        self.step_R3A = GestioneR3AStep(engine)
        self.step_cruoli = CalcolaRuoliStep(engine)

    def execute_record(self, ctx: InvioRuoliAdREContext, depth: int = 0, is_last_credit: bool = False) -> None:
        BatchLogger.info("CICLO-T02", "CICLO-T02 (Scansione Concessioni e Ruoli ADCFRT02)", depth=depth)

        t02_map = self.engine.get_table_map("ADCFRT02")
        tce_map = self.engine.get_table_map("ADCFRTCE")

        formatter = RecordFormatter(_RECORDS_DIR)
        ctx.writer = FileWriter(formatter, encoding="cp1252", line_ending="\r\n")

        ctx.indic_nessun_dato = " "
        almeno_un_record = False
        is_first_row = True

        try:
            for chunk in self._db_stream_cur02(ctx, tce_map, depth=depth + 1):
                for raw_row in chunk:
                    almeno_un_record = True
                    row_t02 = t02_map.normalize(raw_row)
                    ctx.ws_cesa = row_t02.get("codEsattoria")
                    ctx.ws_dinv = row_t02.get("dataInvioCNC")
                    ctx.ws_dcon = row_t02.get("dataConsegna")
                    ctx.ws_feur = row_t02.get("flgEuro")
                    ctx.ws_sede = row_t02.get("sede")
                    ctx.ws_zona = row_t02.get("zona")
                    ctx.ws_centro = row_t02.get("codCentro")
                    ctx.ws_cruo = row_t02.get("codRuoloCoa")

                    is_nuova_concessione = (
                        is_first_row
                        or ctx.ws_cesa != ctx.ws_cesa_t02
                        or ctx.ws_feur != ctx.ws_feur_t02
                    )

                    if is_nuova_concessione:
                        if not is_first_row and ctx.writer.is_open:
                            self._chiudi_concessione(ctx, depth=depth + 1)

                        is_first_row = False
                        ctx.ws_cesa_t02 = ctx.ws_cesa
                        ctx.ws_feur_t02 = ctx.ws_feur

                        # Reset totalizzatori R3Z e chiavi ruolo alla rottura concessione
                        self._reset_totali_R3Z(ctx)
                        ctx.ws_arifruo_t02 = None
                        ctx.ws_nruo_t02 = None
                        ctx.ws_cesa_t02_2 = None

                        dinv_str = str(ctx.ws_dinv or "").strip()[:10]
                        if dinv_str in ("01.01.0001", "0001-01-01", ""):
                            BatchLogger.info(
                                "CONCESSIONE",
                                f"Apertura flusso concessione CESA={ctx.ws_cesa_t02} | FEUR={ctx.ws_feur_t02}",
                                depth=depth + 1
                            )

                            # 1. Estrazione del max numero invio su ADCTET11 e costruzione ws_id_file
                            self._db_fetch_max_t11(ctx, depth=depth + 2)

                            if ctx.indic_errore != "X":
                                output_dir = getattr(ctx, "output_dir", None) or _DEFAULT_OUTPUT_DIR
                                now_apertura = datetime.now()
                                file_name = now_apertura.strftime("CNC.INCNCVL.D%y%m%d.T%H%M%S")
                                ctx.current_output_file = os.path.join(output_dir, file_name)

                                # 2. Apertura del nuovo file fisico
                                ctx.writer.open(ctx.current_output_file)

                                # 3. Valorizzazione e scrittura del record di testa R3A
                                self.step_R3A.execute_controllo_flusso(
                                    ctx=ctx,
                                    row_t02=row_t02,
                                    depth=depth + 2
                                )
                                ctx.ws_prg_file += 1

                    # 4. Elaborazione ordinaria del singolo record/ruolo (CALCOLA-RUOLI)
                    if ctx.writer is not None and ctx.writer.is_open:
                        self._somma_importi_R3Z(ctx=ctx, row_t02=row_t02)
                        self.step_cruoli.execute(ctx, row_t02, depth=depth + 1)
                        if ctx.indic_errore == "X":
                            break

                if ctx.indic_errore == "X":
                    break

            # 5. Controllo fine cursore
            if not almeno_un_record:
                ctx.indic_nessun_dato = "X"
                BatchLogger.warn(
                    "CUR02-VUOTO",
                    "Nessun record presente in ADCFRT02 - NON CI SONO PIU' CONCESSIONI DA ELABORARE",
                    depth=depth + 1,
                    is_last=True
                )
            elif ctx.writer.is_open:
                self._chiudi_concessione(ctx, depth=depth + 1)

        except Exception as err:
            if getattr(ctx, "writer", None) and ctx.writer.is_open:
                ctx.writer.close()

            BatchLogger.error(
                "STREAM-CUR02-ERR",
                f"Errore durante l'elaborazione del cursore CUR02: {err}",
                depth=depth + 1
            )
            if hasattr(self.engine, "rollback"):
                self.engine.rollback()
            ctx.indic_errore = "X"
            raise err

    # =========================================================================
    # ACCESSI AL DATABASE CURJOI-2
    # =========================================================================
    def _db_stream_cur02(self, ctx: InvioRuoliAdREContext, tce_map: Any, depth: int) -> Iterator[List[Any]]:
        """Accesso atomico DB: cursore streaming per ADCFRT02 in join con ADCFRTCE."""
        try:
            query = (
                self.engine.dataset("ADCFRT02")
                .join(tce_map, alias_self="A", alias_target="B")
                .on("codEsattoria", "codEsattoria")
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
                .filter_by("codStRuolo", "IN", ("F", "X"))
                # .filter_by("dataVisto", "<=", ctx.sk_data_firma)
                .order_by("codEsattoria", "flgEuro", "annoRif", "numRuolo", "dataVisto")
                .with_uncommitted_read()
                .compile_select()
            )
            return self.engine.cursor_stream(query, buffer_size=500, depth=depth)
        except Exception as err:
            BatchLogger.error(
                "DB-STREAM-CUR02-ERR",
                f"Errore DB durante l'apertura cursore CUR02: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            return iter([])

    def _db_fetch_max_t11(self, ctx: Any, depth: int) -> int:
        """Accesso atomico DB: recupera MAX(num_flusso) da ADCTET11."""
        data_con = GestioneR3AStep._to_date(ctx.ws_dcon)
        ws_afil = str(data_con.year) if data_con else str(date.today().year)

        try:
            query = (
                self.engine.dataset("ADCTET11")
                .select("MAX:num_flusso")
                .filter_by("ambito", "=", ctx.ws_cesa_t02)
                .filter_by("tipo_flusso", "=", "IR")
                .filter_by("anno_flusso", "=", ws_afil)
                .with_uncommitted_read()
                .limit(1)
                .compile_select()
            )
            rows = self.engine.fetch(query, depth=depth)

            ws_ctr_max = None
            if rows:
                first_row = rows[0]
                if isinstance(first_row, dict):
                    ws_ctr_max = next(iter(first_row.values()), None)
                elif isinstance(first_row, (list, tuple)):
                    ws_ctr_max = first_row[0] if first_row else None
                else:
                    ws_ctr_max = first_row

            ws_ctr_nfil = 1 if ws_ctr_max is None else int(ws_ctr_max) + 1
            ctx.ws_ctr_nfil = ws_ctr_nfil

            cesa_str = str(ctx.ws_cesa_t02 or 0).zfill(3)
            afil_str = ws_afil.zfill(4)
            nfil_str = str(ws_ctr_nfil).zfill(5)
            ctx.ws_id_file = f"RVT00002{cesa_str}{afil_str}{nfil_str}"

            return ws_ctr_nfil

        except Exception as err:
            BatchLogger.error(
                "DB-FETCH-MAX-T11-ERR",
                f"Errore DB durante recupero MAX(num_flusso) da ADCTET11 [CESA={ctx.ws_cesa_t02}, ANNO={ws_afil}]: {err}",
                depth=depth
            )
            ctx.indic_errore = "X"
            return 0

    def _reset_totali_R3Z(self, ctx: InvioRuoliAdREContext) -> None:
        ctx.ws_itrb = Decimal("0")
        ctx.ws_isan = Decimal("0")
        ctx.ws_iint = Decimal("0")
        ctx.ws_ialt = Decimal("0")
        ctx.ws_iaggant = Decimal("0")
        ctx.ws_iaggtot = Decimal("0")
        ctx.ws_iarr = Decimal("0")
        ctx.ws_iiva = Decimal("0")
        ctx.ws_icrc = Decimal("0")
        ctx.ws_tot_r3z_r5a = 0
        ctx.ws_prg_file = 0

    def _somma_importi_R3Z(self, ctx: InvioRuoliAdREContext, row_t02: dict) -> None:
        ctx.ws_itrb += self._parse_decimal(row_t02.get("impTributo"))
        ctx.ws_isan += self._parse_decimal(row_t02.get("impSanzione"))
        ctx.ws_iint += self._parse_decimal(row_t02.get("impInteressi"))
        ctx.ws_ialt += self._parse_decimal(row_t02.get("impAltro"))
        ctx.ws_iaggant += self._parse_decimal(row_t02.get("impAggioAnticipato"))
        ctx.ws_iaggtot += self._parse_decimal(row_t02.get("impAggioTot"))
        ctx.ws_iarr += self._parse_decimal(row_t02.get("impArrotondamento"))
        ctx.ws_iiva += self._parse_decimal(row_t02.get("impIva"))
        ctx.ws_icrc += self._parse_decimal(row_t02.get("impCarico"))

    def _parse_decimal(self, value) -> Decimal:
        if value is None:
            return Decimal("0")
        val_str = str(value).strip()
        if not val_str:
            return Decimal("0")
        try:
            return Decimal(val_str)
        except (InvalidOperation, ValueError):
            return Decimal("0")

    def _chiudi_concessione(self, ctx: InvioRuoliAdREContext, depth: int) -> None:
        """Valorizza e scrive R3Z, chiude il file fisico ed esegue gli aggiornamenti DB."""
        # self.step_R3Z.execute(ctx, depth=depth + 1)

        if ctx.writer is not None:
            tot_rec = ctx.writer.total_records
            dettaglio = dict(ctx.writer.counts)
            file_chiuso = ctx.current_output_file
            ctx.writer.close()

            BatchLogger.info(
                "CHIUSURA-CONCESSIONE",
                f"Chiusa concessione CESA={ctx.ws_cesa_t02} | File={file_chiuso} | Record scritti={tot_rec} | Dettaglio={dettaglio}",
                depth=depth,
                is_last=True
            )
        # TODO: INSERT TAB11 e UPDATE TAB02 'S'