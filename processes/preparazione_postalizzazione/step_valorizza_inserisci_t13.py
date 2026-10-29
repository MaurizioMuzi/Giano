# processes/preparazione_postalizzazione/step_valorizza_inserisci_t13.py
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from .context import PreparazionePostalizzazioneContext
from .descrizioni_config import TDS_OM, IT_OM, IT_AC
from core.batch_logger import BatchLogger

class DettaglioValorizzaT13:

    def __init__(self, engine):
        self.engine = engine

        self.record_avv13 = {}
        '''
        Corrispondente all'EVALUATE in COBOL: 
        ogni valore di tipo avviso associato a metodi che costruiscono la descrizione della partita in italiano o in tedesco
        '''
        self.despar_map = {
            "O": (self._descr_om_tds, self._descr_om_it), # Descrizione avviso da omissione o accertamento generico
            "2": (self._descr_om_tds, self._descr_om_it),
            "A": (self._descr_ac_tds, self._descr_ac_it), # Descrizione avviso accertamento da verbale ispettivo
            "P": (self._descr_a8_tds, self._descr_a8_it), # Descrizione avviso accertamento gestione 8 (Poseidone)
            "C": (self._descr_au_tds, self._descr_au_it), # Descrizione avviso accertamento unificato
            "D": (self._descr_as_tds, self._descr_as_it), # Descrizione avviso accertamento studi settore
            "E": (self._descr_af_tds, self._descr_af_it), # Descrizione avviso accertamento ufficio
            "I": (self._descr_ace_tds, self._descr_ace_it), # Descrizione avviso accertamento da verbale ispettivo ex-enpals
            "U": (self._descr_afe_tds, self._descr_afe_it), # Descrizione avviso accertamento ufficio ex-enpals
            "F": (self._descr_ap_tds, self._descr_ap_it), # Descrizione avviso ripetizione indebito (pensioni)
            "L": (self._descr_legale_tds, self._descr_legale_it), # Descrizione avviso accertamento ex-legale
            "H": (self._descr_art36_tds, self._descr_art36_it), # Descrizione avviso liquidazione automatica art36 bis
            "G": (self._descr_atti_tds, self._descr_atti_it), # Descrizione avviso atti di definizione
            "J": (self._descr_irre_tds, self._descr_irre_it), # Descrizione avviso comunicazione irregolarità
            "M": (self._descr_disc_tds, self._descr_disc_it), # Descrizione provvediemnto disconoscimento
            "V": (self._descr_vig_tds, self._descr_vig_it),
            "R": (self._descr_vnc_tds, self._descr_vnc_it)
        }
        '''
        Corrispondente all'EVALUATE in COBOL: utilizzato dal metodo "_descr_om_it"
        '''
        self._cges_map_it = {
            "1": self._it_1,
            "3": self._it_3_4,
            "4": self._it_3_4,
            "5": self._it_5_6,
            "6": self._it_5_6,
            "7": self._it_7,
            "8": self._it_8,
            "P": self._it_p,
            "G": self._it_g_h,
            "H": self._it_g_h,
            "I": self._it_i_m,
            "C": self._it_c,
            "M": self._it_i_m,
        }
        '''
        Corrispondente all'EVALUATE in COBOL: utilizzato dal metodo "_descr_om_tds"
        '''
        self._cges_map_td = {
            "1": self._td_1,
            "3": self._td_3_4,
            "4": self._td_3_4,
            "5": self._td_5_6,
            "6": self._td_5_6,
            "7": self._td_7,
            "8": self._td_8,
            "P": self._td_p,
            "G": self._td_g_h,
            "H": self._td_g_h,
            "I": self._td_i,
            "C": self._td_c,
            "M": self._td_m,
        }

    def execute_dettaglio(self, ctx: PreparazionePostalizzazioneContext, rowt01, is_last: bool = False, depth: int = 2) -> None:
        BatchLogger.info("VALORIZZAZIONE-ADCAVV13",
                             "Valorizzazione dati per l'inserimento nella tabella dettaglio addebiti (ADCAVV13)",
                             depth=depth)
        current_system_date = date.today()

        if ((ctx.ws_cges == "1" and ctx.tipoavv == "V")
                or (ctx.ws_cges == "D")):
            # estrazione valori per le descrizioni SPAR1 e SPAR2
            self._cerca_spar_vig(ctx, depth=depth)

        ctx.ws_spar1 = " "
        ctx.ws_spar2 = " "
        ctx.ws_spar1_tds = " "
        ctx.ws_spar2_tds = " "

        if (ctx.catt == ctx.idAvviso
            and ctx.ws_cges == "N"):
        # Rif COBOL: PERFORM VALO-DESPAR-SPS-TDS E VALO-DESPAR-SPS-IT

            if ctx.cesa == 21:
                # Valorizzazione descrizione partita per spese di notifica in tedesco
                ctx.ws_spar1_tds = "ZUSTELLUNGSGEBÜHREN FÜR DEN VORLIEGENDEN SCHULDBESCHEID "
                ctx.ws_spar1_tds = ctx.sattbi
        # Valorizzazione descrizione partita per spese di notifica italiano
            ctx.ws_spar1 = "SPESE DI NOTIFICA DEL PRESENTE AVVISO DI ADDEBITO "
            ctx.ws_spar2 = ctx.satt
        else:
            self._valorizza_descrizioni(ctx, depth+1)

        # Mappatura esclusiva sui nomi logici definiti in ADCAVV13.json
        self.record_avv13 = {
                "codiceAvviso": ctx.ws_codavv,
                "identificativoAvviso": ctx.idAvviso,
                "progPartita": ctx.nesp,
                "descrizione1": ctx.ws_spar1,
                "descrizione2": ctx.ws_spar1,
                "descrizioneTedesco1": ctx.ws_spar1_tds,
                "descrizioneTedesco2": ctx.ws_spar2_tds,
                "descrizioneSanzioni": "",
                "descrizioneSanzioniTedesco": ""
            }

        BatchLogger.info(
                "INSERT-T13",
                f"Inserimento record in ADCAVV13 (Codice avviso: {ctx.ws_codavv} e Progressivo partita: {ctx.nesp})",
                depth=depth
            )

        ins_tavv13 = self.engine.dataset("ADCAVV13").compile_insert(self.record_avv13)

        try:
            righe = self.engine.execute_mutation(ins_tavv13, depth=depth)
            BatchLogger.debug(
                    "INSERISCI-ADCAVV13",
                    f"Inserito record per avviso {ctx.ws_codavv} (Righe: {righe})",
                    depth=depth
            )
        except:
            ctx.indic_errore = "X"
            BatchLogger.error(
                    "INSERT-ADCAVV13",
                    f"Fallito inserimento record in ADCAVV13 (Codice avviso: {ctx.ws_codavv})",
                    depth=2, is_last=True
            )
            raise

    def _cerca_spar_vig(self, ctx: PreparazionePostalizzazioneContext, depth: int = 2) -> None:
        BatchLogger.info("SELECT-ADCAVV33", "Estrazione delle descrizioni partite su ADCAVV33", depth=depth)
        t33_map = self.engine.get_table_map("ADCAVV33")

        query_t33 = (
                self.engine.dataset("ADCAVV33")
                .select("codiceTribunale", "descrizionePartita1", "descrizionePartita2",
                        "descrizionePartita3", "descrizionePartita4")
                .filter_by("gestione", "=", ctx.ws_cges)
                .filter_by("codiceAtto", "=", ctx.catt)
                .with_uncommitted_read()
                .limit(1)
                .compile_select()
            )
        rows_t33 = self.engine.fetch(query_t33, depth=1)

        if rows_t33:
            row_t33 = t33_map.normalize(rows_t33[0])

        else:
            BatchLogger.error("SELECT-ADCAVV33", f"Nessun record attivo su ADCAVV33", depth=1, is_last=True)
            ctx.indic_errore = "X"
            return

    def _valorizza_descrizioni(self, ctx: PreparazionePostalizzazioneContext, depth: int) -> None:
        BatchLogger.info("VALORIZZAZIONE-DESCRIZIONI", "Valorizzazione delle descrizioni partite in italiano e tedesco",
                         depth=depth+1)

        tipoavv = (ctx.tipoavv or "").strip()
        metodi_descr = self.despar_map.get(tipoavv)

        if metodi_descr is not None:
            if tipoavv == "M":
                # verifica che il codice causale sia presente sulla tabella ADCAVV24
                self._ctrl_ccau_avv24()

            tds, it = metodi_descr

            if int(ctx.cesa or 0) == 21:
                #Costruisco la descrizione della partita in tedesco
                tds(ctx)
            # Costruisco sempre la descrizione della partita in italiano
            it(ctx)

    def _descr_om_it(self, ctx):

        ctx.ws_appo_inad = 0
        cfg = IT_OM

        metodo = self._cges_map_it.get(ctx.ws_cges)

        if metodo is not None:
            metodo(ctx, cfg)

        # --- parte dopo END-EVALUATE - valorizzazione spar2 ---
        inad_in_range = (ctx.ws_cges == "1" and 101<=ctx.ws_appo_inad<=299)
        caso_76_51 = (
            ctx.ws_cges == "1"
            and int(f"{ctx.ws_appo_inad:04d}"[0]) > 2
            and ctx.cseg in ("76", "51")
            and ctx.tipoavv == "2"
        )

        if (ctx.ws_cges == "I"
                or inad_in_range):
            ctx.ws_spar2 = " "

        elif caso_76_51:
            if ctx.satt[32:60].strip() != "":
                s = ctx.ws_spar2
                s = (
                    cfg.k3_ap[:6].ljust(6)
                    + (ctx.satt or "")[32:60].ljust(28)
                    + s[34:]

                )

                ctx.ws_spar2 = s
            else:
                ctx.ws_spar2 = ctx.satt

    def _it_1(self, ctx, cfg):
        ctx.ws_appo_inad = int(ctx.catt[10:14].strip() or 0)

        if ctx.tipoavv == "O":
            # Inadempienze comprese tra 101 e 299 = CREDITI GIASONE
            # campo SATT valorizzato: "CONTRIBUTO ADD.LE CIG INPS.SSSS.GG/MM/AAAA.NNNNNNN"
            if 101<=ctx.ws_appo_inad<=299:
                ctx.ws_spar1 = ctx.satt
            else:
                ctx.ws_spar1 = (
                        cfg.k1_omg1[:13].ljust(13)
                        + (ctx.catt or "")[10:14].ljust(4)
                        + ctx.ws_spar1[17:]
                )
        else:
            # Infasamento aziende CGES ('76' o '51') e inadempienza >=3000
            if (int(f"{ctx.ws_appo_inad:04d}"[0]) > 2
                and ctx.cseg in ("76", "51")):

                s = ctx.ws_spar1
                ctx.ws_spar1 = (
                        cfg.k1_omg1[:13].ljust(13)
                        + (ctx.catt or "")[10:14].ljust(4)
                        + s[17:18]
                        + '- '
                        + (ctx.satt or "")[0:32].ljust(32)
                        + s[52:]
                )
            else:
                # Inadempienza comprese tra 101 e 299
                if 101 <= ctx.ws_appo_inad <= 299:
                    ctx.ws_spar1 = ctx.satt
                else:
                    ctx.ws_spar1 = (
                            cfg.k1_omg1[:13].ljust(13)
                            + (ctx.catt or "")[10:14].ljust(4)
                            + ctx.ws_spar1[17:]
                    )

    def _it_3_4(self, ctx, cfg):

        ctx.ws_appo_catt = int((ctx.catt or "")[10:13].strip() or 0)
        ctx.ws_anno_catt = 1900 + ctx.ws_appo_catt

        anno = f"{ctx.ws_anno_catt:04d}"

        if (ctx.catt or "")[15:16] == "0":
            # Rata assente
                s = ctx.ws_spar1
                ctx.ws_spar1 = (
                        cfg.k2_omg3[:51].ljust(51)
                        + anno
                        + '-'
                        + (ctx.catt or "")[13:15].ljust(2)
                        + s[58:]
                )
        else:
            # Presenza della rata
            s = ctx.ws_spar1
            ctx.ws_spar1 = (
                    cfg.kf_omg3[:27].ljust(27)
                    + anno
                    + '-'
                    + (ctx.catt or "")[13:15].ljust(2)
                    + cfg.k3_omg3[:9].ljust(9)
                    + (ctx.catt or "")[15:16].ljust(1)
                    + s[44:]
            )

    def _it_5_6(self, ctx, cfg):
        catt = ctx.catt or ""

        if catt[7:11] == "0000":
            # Anno non presente: MOVE SPACES TO WS-SPAR1
            ctx.ws_spar1 = " " * len(ctx.ws_spar1)
            return

        # Anno presente: scritture comuni a tutti i rami
        s = ctx.ws_spar1
        s = cfg.k4_omg5[:10].ljust(10) + catt[7:11].ljust(4) + s[14:]

        if catt[11:12] != "0":
            if ctx.ws_cges == "5":
                s = s[:14] + cfg.k5_omg5[:7].ljust(7) + catt[11:12].ljust(1) + s[22:]
            else:
                # Gestione '6'
                ctx.ws_anno_catt = int(catt[7:11].strip() or 0)
                if ctx.ws_anno_catt > 2009:
                    s = s[:14] + cfg.k5_omg6[:6].ljust(6) + catt[11:12].ljust(1) + s[21:]

        ctx.ws_spar1 = s

    def _it_7(self, ctx, cfg):
        s = ctx.ws_spar1
        ctx.ws_spar1 = (
                cfg.ka_omg7[:6].ljust(6)
                + cfg.k6_omg7[:21].ljust(21)
                + (ctx.catt or "")[12:14].ljust(2)
                + '/'
                + (ctx.catt or "")[14:18].ljust(4)
                + cfg.k7_omg7[:6].ljust(6)
                + (ctx.sedorig or "")[:4].ljust(4)
                + s[44:]
        )

    def _it_8(self, ctx, cfg):
        ctx.ws_spar1 = (
                cfg.k8_omg8[:16].ljust(16)
                + (ctx.catt or "")[14:18].ljust(4)
                + cfg.k7_omg7[:6].ljust(6)
                + (ctx.sedorig or "")[:4].ljust(4)
                + ctx.ws_spar1[30:]
        )

    def _it_p(self, ctx, cfg):
        ctx.ws_spar1 = (
                cfg.k9_omgp[:10].ljust(10)
                + (ctx.catt or "")[:10].ljust(10)
                + cfg.ka_omgp[:6].ljust(6)
                + (ctx.catt or "")[10:14].ljust(4)
                + ctx.ws_spar1[30:]
        )

    def _it_g_h(self, ctx, cfg):
        ctx.ws_spar1 = (
                cfg.k9_omgp[:10].ljust(10)
                + (ctx.catt or "")[:9].ljust(9)
                + " "
                + cfg.kb_omge[:17].ljust(17)
                + ctx.ws_spar1[37:]
        )

    def _it_i_m(self, ctx, cfg):
        n = len(ctx.ws_spar1)
        ctx.ws_spar1 = (ctx.satt or "")[:n].ljust(n)

    def _it_c(self, ctx, cfg):
        ctx.ws_spar1 = (
                cfg.k1_omdm[:20].ljust(20)
                + (ctx.catt or "")[:12].ljust(12)
                + cfg.k2_omdm[:27].ljust(27)
                + (ctx.catt or "")[12:13].ljust(1)
                + cfg.k3_omdm[:1].ljust(1)
                + (ctx.catt or "")[13:18].ljust(4)
                + ctx.ws_spar1[65:]
        )

    def _descr_om_tds(self, ctx):

        ctx.ws_appo_inad = 0
        cfg = TDS_OM

        metodo = self._cges_map_td.get(ctx.ws_cges)

        if metodo is not None:
            metodo(ctx, cfg)

        # --- parte dopo END-EVALUATE - valorizzazione spar2 ---
        inad_in_range = (ctx.ws_cges == "1" and 101<=ctx.ws_appo_inad<=299)
        caso_76_51 = (
            ctx.ws_cges == "1"
            and int(f"{ctx.ws_appo_inad:04d}"[0]) > 2
            and ctx.cseg in ("76", "51")
            and ctx.tipoavv == "2"
        )

        if (ctx.ws_cges == "I"
                or inad_in_range):
            ctx.ws_spar2_tds = " "

        elif caso_76_51:
            if ctx.satt[32:60].strip() != "":
                s = ctx.ws_spar2_tds
                s = (
                    cfg.k3_ap[:7].ljust(7)
                    + s[7:8]
                    + (ctx.satt or "")[32:60].ljust(28)
                    + s[36:]
                     )
                ctx.ws_spar2_tds = s
            else:
                ctx.ws_spar2_tds = ctx.sattbi

    def _td_1(self, ctx, cfg):
        ctx.ws_appo_inad = int(ctx.catt[10:14].strip() or 0)

        if ctx.tipoavv == "O":
            # Inadempienze comprese tra 101 e 299 = CREDITI GIASONE
            # campo SATT valorizzato: "CONTRIBUTO ADD.LE CIG INPS.SSSS.GG/MM/AAAA.NNNNNNN"
            if 101<=ctx.ws_appo_inad<=299:
                ctx.ws_spar1_tds = ctx.sattbi
            else:
                ctx.ws_spar1_tds = (
                        cfg.k1_omg1[:21].ljust(21)
                        + (ctx.catt or "")[10:14].ljust(4)
                        + ctx.ws_spar1_tds[25:]
                )
        else:
            # Infasamento aziende CGES ('76' o '51') e inadempienza >=3000
            if (int(f"{ctx.ws_appo_inad:04d}"[0]) > 2
                and ctx.cseg in ("76", "51")
                and ctx.tipoavv == "2"):

                s = ctx.ws_spar1_tds
                ctx.ws_spar1_tds = (
                        cfg.k1_omg1[:21].ljust(21)
                        + (ctx.catt or "")[10:14].ljust(4)
                        + '-'
                        + (ctx.satt or "")[0:32].ljust(32)
                        + s[58:]
                )
            else:
                # Inadempienza comprese tra 101 e 299
                if 101 <= ctx.ws_appo_inad <= 299:
                    ctx.ws_spar1_tds = ctx.sattbi
                else:
                    ctx.ws_spar1_tds = (
                            cfg.k1_omg1[:21].ljust(21)
                            + (ctx.catt or "")[10:14].ljust(4)
                            + ctx.ws_spar1_tds[25:]
                    )

    def _td_3_4(self, ctx, cfg):

        ctx.ws_appo_catt = int((ctx.catt or "")[10:13].strip() or 0)
        ctx.ws_anno_catt = 1900 + ctx.ws_appo_catt

        anno = f"{ctx.ws_anno_catt:04d}"

        if (ctx.catt or "")[15:16] == "0":
            # Rata assente
                s = ctx.ws_spar1_tds
                ctx.ws_spar1_tds = (
                        cfg.k2_omg3[:51].ljust(51)
                        + anno
                        + '-'
                        + (ctx.catt or "")[13:15].ljust(2)
                        + s[58:]
                )
        else:
            # Presenza della rata
            s = ctx.ws_spar1_tds
            ctx.ws_spar1_tds = (
                    cfg.kf_omg3[:20].ljust(20)
                    + anno
                    + '-'
                    + (ctx.catt or "")[13:15].ljust(2)
                    + cfg.k3_omg3[:10].ljust(10)
                    + (ctx.catt or "")[15:16].ljust(1)
                    + s[39:]
            )

    def _td_5_6(self, ctx, cfg):
        catt = ctx.catt or ""

        if catt[7:11] == "0000":
            # Anno non presente: MOVE SPACES TO WS-SPAR1
            ctx.ws_spar1_tds = " " * len(ctx.ws_spar1_tds)
            return

        # Anno presente: scritture comuni a tutti i rami
        s = ctx.ws_spar1_tds
        s = cfg.k4_omg5[:8].ljust(8) + catt[7:11].ljust(4) + s[12:]

        if catt[11:12] != "0":
            if ctx.ws_cges == "5":
                s = s[:12] + cfg.k5_omg5[:11].ljust(11) + catt[11:12].ljust(1) + s[24:]
            else:
                # Gestione '6'
                ctx.ws_anno_catt = int(catt[7:11].strip() or 0)
                if ctx.ws_anno_catt > 2009:
                    s = s[:12] + cfg.k5_omg6[:6].ljust(6) + catt[11:12].ljust(1) + s[19:]

        ctx.ws_spar1_tds = s

    def _td_7(self, ctx, cfg):
        s = ctx.ws_spar1_tds
        ctx.ws_spar1_tds = (
                cfg.ka_omg7[:6].ljust(6)
                + cfg.k6_omg7[:22].ljust(22)
                + (ctx.catt or "")[12:14].ljust(2)
                + '/'
                + (ctx.catt or "")[14:18].ljust(4)
                + cfg.k7_omg7[:12].ljust(12)
                + (ctx.sedorig or "")[:4].ljust(4)
                + s[51:]
        )

    def _td_8(self, ctx, cfg):
        ctx.ws_spar1_tds = (
                cfg.k8_omg8[:16].ljust(16)
                + (ctx.catt or "")[14:18].ljust(4)
                + cfg.k7_omg7[:12].ljust(12)
                + (ctx.sedorig or "")[:4].ljust(4)
                + ctx.ws_spar1_tds[36:]
        )

    def _td_p(self, ctx, cfg):
        ctx.ws_spar1_tds = (
                cfg.k9_omgp[:9].ljust(9)
                + (ctx.catt or "")[:10].ljust(10)
                + cfg.ka_omgp[:6].ljust(6)
                + (ctx.catt or "")[10:14].ljust(4)
                + ctx.ws_spar1_tds[29:]
        )

    def _td_g_h(self, ctx, cfg):
        ctx.ws_spar1_tds = (
                cfg.k9_omgp[:9].ljust(9)
                + (ctx.catt or "")[:9].ljust(9)
                + " "
                + cfg.kb_omge[:19].ljust(19)
                + ctx.ws_spar1_tds[38:]
        )

    def _td_i(self, ctx, cfg):
        n = len(ctx.ws_spar1_tds)
        ctx.ws_spar1_tds = (ctx.sattbi or "")[:n].ljust(n)

    def _td_c(self, ctx, cfg):
        ctx.ws_spar1_tds = (
                cfg.k1_omdm[:21].ljust(21)
                + (ctx.catt or "")[:12].ljust(12)
                + cfg.k2_omdm[:23].ljust(23)
                + (ctx.catt or "")[12:13].ljust(1)
                + cfg.k3_omdm[:1].ljust(1)
                + (ctx.catt or "")[13:18].ljust(4)
                + ctx.ws_spar1_tds[62:]
        )

    def _td_m(self, ctx, cfg):
        ctx.ws_spar1_tds = cfg.k1_omredec

    def _descr_ac_it(self, ctx):

        cfg = IT_AC

        satt = ctx.satt or ""

        if not satt[:28].strip():
                s1 = ctx.ws_spar1
                s1 = cfg.k1_ac[:17].ljust(17) + s1[17:]

                if satt[28:36].strip() != "00010101":
                    s1 = s1[:17] + cfg.k4_ac[:5].ljust(5) + s1[22:]
                    s1 = s1[:22] + self._gira_data(satt[28:36]) +s1[32:]

                ctx.ws_spar1 = s1

                s2 = ctx.ws_spar2
                s2 = cfg.k5_ac[:14].ljust(14) + s2[14:]
                s2 = s2[:14] + self._gira_data(satt[36:44]) + s2[24:]
                ctx.ws_spar2 = s2
        else:
            return