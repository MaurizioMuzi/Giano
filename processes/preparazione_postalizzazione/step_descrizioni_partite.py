# processes/preparazione_postalizzazione/step_descrizioni_partite.py
from core.batch_logger import BatchLogger
from .import descrizioni_config as C

DATA_VUOTA = "00010101"


# ------------------------------------------------------------------ helper
def gira_data(data8: str) -> str:
    """GIRA-DATA: 'AAAAMMGG' -> 'GG/MM/AAAA' (WS-DATA-ALFA). Nessuna validazione, come il COBOL."""
    d = (data8 or "").ljust(8)
    return f"{d[6:8]}/{d[4:6]}/{d[0:4]}"


def num(s) -> int:
    """MOVE alfanumerico -> numerico: contenuto non numerico vale 0."""
    s = str(s or "").strip()
    return int(s) if s.isdigit() else 0


class Area:
    """Campo PIC X(n) con reference modification. Persiste tra le righe, come la WORKING-STORAGE."""

    def __init__(self, lung: int):
        self.lung = lung
        self.v = " " * lung

    def put(self, pos: int, lung: int, valore) -> None:
        """MOVE valore TO AREA(pos:lung): tronca/riempie a 'lung', il resto resta invariato."""
        t = "" if valore is None else str(valore)
        self.v = self.v[:pos - 1] + t[:lung].ljust(lung) + self.v[pos - 1 + lung:]

    def move(self, valore) -> None:
        """MOVE valore TO AREA (tutto il campo)."""
        t = "" if valore is None else str(valore)
        self.v = t[:self.lung].ljust(self.lung)

    def spaces(self) -> None:
        self.v = " " * self.lung


class Lingua:
    """Tutto ciò che distingue IT da TDS: suffisso costanti, aree di lavoro, valori finali."""

    def __init__(self, sfx: str, lung1: int, lung2: int):
        self.sfx = sfx                       # "IT" oppure "TD"
        self.s1, self.s2 = Area(lung1), Area(lung2)   # WS-SPAR1 / WS-SPAR2 (e -TDS)
        self.out1 = self.out2 = ""           # SPAR1 / SPAR2 (SPAR-TDS1 / 2) di CDCAVV13

    @property
    def it(self) -> bool:
        return self.sfx == "IT"

    def k(self, nome: str) -> str:
        """Costante COBOL con suffisso di lingua: L.k('K1_OMG1') -> K1_OMG1IT / K1_OMG1TD."""
        return getattr(C, nome + self.sfx)

    def att(self, ctx) -> str:
        """SATT per l'italiano, SATTBI per il tedesco."""
        return (ctx.satt if self.it else ctx.sattbi) or ""

    def reset(self) -> None:
        """MOVE SPACES alle aree di lavoro e ai valori finali (inizio riga)."""
        self.s1.spaces()
        self.s2.spaces()
        self.out1 = " " * self.s1.lung
        self.out2 = " " * self.s2.lung

    def chiudi(self) -> None:
        """MOVE WS-SPAR1 TO SPAR1 / MOVE WS-SPAR2 TO SPAR2."""
        self.out1, self.out2 = self.s1.v, self.s2.v


# Lunghezze reali dei PIC di WS-SPAR1 / WS-SPAR2 (e -TDS): DA SOSTITUIRE
LUNG_SPAR1_IT = LUNG_SPAR2_IT = LUNG_SPAR1_TD = LUNG_SPAR2_TD = 75


def crea_lingue(ctx) -> None:
    """Da chiamare una volta sola a inizio batch."""
    ctx.it = Lingua("IT", LUNG_SPAR1_IT, LUNG_SPAR2_IT)
    ctx.tds = Lingua("TD", LUNG_SPAR1_TD, LUNG_SPAR2_TD)


CGES_LEGALE = {"1", "3", "4", "5", "6", "7", "8", "P", "G", "H", "I"}


class Descrizioni:
    # ------------------------------------------------------------ mappe
    def __init__(self, engine):
        self.engine = engine
        self._init_descrizioni()

    def _init_descrizioni(self):
        # tipoavv -> (metodo TDS, metodo IT)
        self.despar_map = {
            "O": (self._descr_om_tds, self._descr_om_it),
            "2": (self._descr_om_tds, self._descr_om_it),
            "A": (self._descr_ac_tds, self._descr_ac_it),
            "P": (self._descr_a8_tds, self._descr_a8_it),
            "C": (self._descr_au_tds, self._descr_au_it),
            "D": (self._descr_as_tds, self._descr_as_it),
            "E": (self._descr_af_tds, self._descr_af_it),
            "I": (self._descr_ace_tds, self._descr_ace_it),
            "U": (self._descr_afe_tds, self._descr_afe_it),
            "F": (self._descr_ap_tds, self._descr_ap_it),
            "L": (self._descr_legale_tds, self._descr_legale_it),
            "H": (self._descr_art36_tds, self._descr_art36_it),
            "G": (self._descr_atti_tds, self._descr_atti_it),
            "J": (self._descr_irre_tds, self._descr_irre_it),
            "M": (self._descr_disc_tds, self._descr_disc_it),
            "V": (self._descr_vig_tds, self._descr_vig_it),
            "R": (self._descr_vmc_tds, self._descr_vmc_it),
        }
        # cges -> (handler TDS, handler IT); firma (ctx, L, area)
        self._cges_map = {
            "1": (self._cges_1, self._cges_1),
            "3": (self._td_3_4, self._it_3_4), "4": (self._td_3_4, self._it_3_4),
            "5": (self._td_5_6, self._it_5_6), "6": (self._td_5_6, self._it_5_6),
            "7": (self._td_7, self._it_7),
            "8": (self._td_8, self._it_8),
            "P": (self._td_p, self._it_p),
            "G": (self._td_g_h, self._it_g_h), "H": (self._td_g_h, self._it_g_h),
            "I": (self._cges_i, self._cges_i),
            "C": (self._td_c, self._it_c),
            "M": (self._td_m, self._it_m),
        }

    # ------------------------------------------------------------ dispatcher per tipoavv
    def valorizza(self, ctx, depth: int) -> None:
        tipoavv = (ctx.tipoavv or "").strip()
        metodi = self.despar_map.get(tipoavv)

        if metodi is not None:                       # WHEN OTHER: CONTINUE
            if tipoavv == "M":
                self._ctrl_ccau_avv24(ctx, depth)
            tds, it = metodi
            if int(ctx.cesa or 0) == 21:
                tds(ctx)
            it(ctx)

    def _dispatch_cges(self, ctx, L: Lingua, a: Area, legale: bool = False) -> None:
        cges = ctx.ws_cges
        if legale:
            if cges not in CGES_LEGALE:
                return
            if cges == "1":
                self._legale_1(ctx, L, a)
                return
            if cges in ("3", "4") and (ctx.catt or "")[10:11] == "9":
                a.spaces()                            # non è un anno
                return
        h = self._cges_map.get(cges)
        if h is not None:
            h[1 if L.it else 0](ctx, L, a)

    # ================================================================== OMISSIONE
    def _descr_om_it(self, ctx):
        ctx.ws_appo_inad = 0                         # MOVE ZEROES TO WS-APPO-INAD
        self._descr_om(ctx, ctx.it)

    def _descr_om_tds(self, ctx):
        self._descr_om(ctx, ctx.tds)

    def _descr_om(self, ctx, L: Lingua):                      # MOVE CGES TO WS-CGES
        self._dispatch_cges(ctx, L, L.s1)
        L.out1 = L.s1.v                              # MOVE WS-SPAR1 TO SPAR1

        satt = ctx.satt or ""
        appo, cges = ctx.ws_appo_inad, ctx.ws_cges
        if cges == "I" or (cges == "1" and 101 <= appo <= 299):
            L.out2 = " " * L.s2.lung
        elif (cges == "1" and appo // 1000 > 2
              and ctx.cseg in ("76", "51") and ctx.tipoavv == "2"):
            if satt[32:60].strip():
                if L.it:
                    L.s2.put(1, 6, C.K3_APIT)
                    L.s2.put(7, 28, satt[32:60])
                else:
                    L.s2.put(1, 7, C.K3_APTD)
                    L.s2.put(9, 28, satt[32:60])
                L.out2 = L.s2.v
            elif L.it:
                L.out2 = L.s2.v                      # IT: MOVE fuori dall'IF
            # TDS: SPAR-TDS2 non viene toccato
        else:
            L.out2 = L.att(ctx)

    # ---- WHEN '1' (IT e TDS, stessa struttura)
    def _cges_1(self, ctx, L, a):
        catt = ctx.catt or ""
        appo = num(catt[10:14])
        ctx.ws_appo_inad = appo
        k1 = L.k("K1_OMG1")
        n = len(k1)

        def descr():
            a.put(1, n, k1)
            a.put(n + 1, 4, catt[10:14])

        in_range = 101 <= appo <= 299
        if ctx.tipoavv == "O":
            a.move(L.att(ctx)) if in_range else descr()
        elif (appo // 1000 > 2 and ctx.cseg in ("76", "51")
              and (L.it or ctx.tipoavv == "2")):
            descr()
            if L.it:
                a.put(19, 2, "- ")                   # la pos. 18 resta com'era
                a.put(21, 32, (ctx.satt or "")[:32])
            else:
                a.put(26, 1, "-")
                a.put(27, 32, (ctx.sattbi or "")[:32])
        else:
            a.move(L.att(ctx)) if in_range else descr()

    def _legale_1(self, ctx, L, a):
        k1 = L.k("K1_OMG1")
        a.put(1, len(k1), k1)
        a.put(len(k1) + 1, 4, (ctx.catt or "")[10:14])

    def _cges_i(self, ctx, L, a):
        a.move(L.att(ctx))

    # ---- WHEN '3' '4'
    def _it_3_4(self, ctx, L, a):
        catt = ctx.catt or ""
        anno = f"{1900 + num(catt[10:13]):04d}"
        if catt[15:16] == "0":                       # RATA ASSENTE
            a.put(1, 51, L.k("K2_OMG3")); a.put(52, 4, anno)
            a.put(56, 1, "-"); a.put(57, 2, catt[13:15])
        else:                                        # PRESENZA DELLA RATA
            a.put(1, 27, L.k("KF_OMG3")); a.put(28, 4, anno)
            a.put(32, 1, "-"); a.put(33, 2, catt[13:15])
            a.put(35, 9, L.k("K3_OMG3")); a.put(44, 1, catt[15:16])

    def _td_3_4(self, ctx, L, a):
        catt = ctx.catt or ""
        anno = f"{1900 + num(catt[10:13]):04d}"
        if catt[15:16] == "0":
            a.put(1, 51, L.k("K2_OMG3")); a.put(52, 4, anno)
            a.put(56, 1, "-"); a.put(57, 2, catt[13:15])
        else:
            a.put(1, 20, L.k("KF_OMG3")); a.put(21, 4, anno)
            a.put(25, 1, "-"); a.put(26, 2, catt[13:15])
            a.put(28, 10, L.k("K3_OMG3")); a.put(38, 1, catt[15:16])

    # ---- WHEN '5' '6'
    def _it_5_6(self, ctx, L, a):
        catt = ctx.catt or ""
        if catt[7:11] == "0000":
            a.spaces(); return
        a.put(1, 10, L.k("K4_OMG5")); a.put(11, 4, catt[7:11])
        if catt[11:12] != "0":
            if ctx.ws_cges == "5":
                a.put(15, 7, L.k("K5_OMG5")); a.put(22, 1, catt[11:12])
            elif num(catt[7:11]) > 2009:             # gestione '6'
                a.put(15, 6, L.k("K5_OMG6")); a.put(21, 1, catt[11:12])

    def _td_5_6(self, ctx, L, a):
        catt = ctx.catt or ""
        if catt[7:11] == "0000":
            a.spaces(); return
        a.put(1, 8, L.k("K4_OMG5")); a.put(9, 4, catt[7:11])
        if catt[11:12] != "0":
            if ctx.ws_cges == "5":
                a.put(13, 11, L.k("K5_OMG5")); a.put(24, 1, catt[11:12])
            elif num(catt[7:11]) > 2009:
                a.put(13, 6, L.k("K5_OMG6"))
                a.put(14, 1, catt[11:12])            # sovrascrive la pos. 14, come il COBOL

    # ---- WHEN '7'
    def _it_7(self, ctx, L, a):
        catt = ctx.catt or ""
        a.put(1, 6, L.k("KA_OMG7")); a.put(7, 21, L.k("K6_OMG7"))
        a.put(28, 2, catt[12:14]); a.put(30, 1, "/"); a.put(31, 4, catt[14:18])
        a.put(35, 6, L.k("K7_OMG7")); a.put(41, 4, ctx.sedorig)

    def _td_7(self, ctx, L, a):
        catt = ctx.catt or ""
        a.put(1, 6, L.k("KA_OMG7")); a.put(7, 22, L.k("K6_OMG7"))
        a.put(29, 2, catt[12:14]); a.put(31, 1, "/"); a.put(32, 4, catt[14:18])
        a.put(36, 12, L.k("K7_OMG7")); a.put(48, 4, ctx.sedorig)

    # ---- WHEN '8'
    def _it_8(self, ctx, L, a):
        a.put(1, 16, L.k("K8_OMG8")); a.put(17, 4, (ctx.catt or "")[14:18])
        a.put(21, 6, L.k("K7_OMG7")); a.put(27, 4, ctx.sedorig)

    def _td_8(self, ctx, L, a):
        a.put(1, 16, L.k("K8_OMG8")); a.put(17, 4, (ctx.catt or "")[14:18])
        a.put(21, 12, L.k("K7_OMG7")); a.put(33, 4, ctx.sedorig)

    # ---- WHEN 'P'
    def _it_p(self, ctx, L, a):
        catt = ctx.catt or ""
        a.put(1, 10, L.k("K9_OMGP")); a.put(11, 10, catt[:10])
        a.put(21, 6, L.k("KA_OMGP")); a.put(27, 4, catt[10:14])

    def _td_p(self, ctx, L, a):
        catt = ctx.catt or ""
        a.put(1, 9, L.k("K9_OMGP")); a.put(10, 10, catt[:10])
        a.put(20, 6, L.k("KA_OMGP")); a.put(26, 4, catt[10:14])

    # ---- WHEN 'G' 'H'
    def _it_g_h(self, ctx, L, a):
        a.put(1, 10, L.k("K9_OMGP")); a.put(11, 9, (ctx.catt or "")[:9])
        a.put(20, 1, " "); a.put(21, 17, L.k("KB_OMGE"))

    def _td_g_h(self, ctx, L, a):
        a.put(1, 9, L.k("K9_OMGP")); a.put(10, 9, (ctx.catt or "")[:9])
        a.put(19, 1, " "); a.put(20, 19, L.k("KB_OMGE"))

    # ---- WHEN 'C' (domestici)
    def _it_c(self, ctx, L, a):
        catt = ctx.catt or ""
        a.put(1, 20, L.k("K1_OMDM")); a.put(21, 12, catt[:12])
        a.put(33, 27, L.k("K2_OMDM")); a.put(60, 1, catt[12:13])
        a.put(61, 1, L.k("K3_OMDM")); a.put(62, 4, catt[13:17])

    def _td_c(self, ctx, L, a):
        catt = ctx.catt or ""
        a.put(1, 21, L.k("K1_OMDM")); a.put(22, 12, catt[:12])
        a.put(34, 23, L.k("K2_OMDM")); a.put(57, 1, catt[12:13])
        a.put(58, 1, C.K3_OMDMIT)                    # il COBOL TDS usa K3-OMDMIT
        a.put(59, 4, catt[13:17])

    # ---- WHEN 'M' (REDEC)
    def _it_m(self, ctx, L, a):
        a.move(ctx.satt)

    def _td_m(self, ctx, L, a):
        a.move(C.K1_OMREDECTD)

    # ================================================================== LEGALE
    def _descr_legale_it(self, ctx):
        self._descr_legale(ctx, ctx.it)

    def _descr_legale_tds(self, ctx):
        self._descr_legale(ctx, ctx.tds)

    def _descr_legale(self, ctx, L: Lingua):
        ctx.ws_cges = ctx.cges
        self._dispatch_cges(ctx, L, L.s2, legale=True)    # scrive su WS-SPAR2
        L.out2 = L.s2.v
        L.out1 = " " * L.s1.lung if ctx.ws_cges == "I" else L.att(ctx)

    # ================================================================== ACCERTAMENTO DA VERBALE (A)
    def _descr_ac_it(self, ctx):
        L = ctx.it
        s1, s2 = L.s1, L.s2
        satt = ctx.satt or ""
        data_ok = satt[28:36] != DATA_VUOTA

        if not satt[:28].strip():                    # ASSENZA DI PROTOCOLLO
            s1.put(1, 17, C.K1_ACIT)
            if data_ok:
                s1.put(18, 5, C.K4_ACIT); s1.put(23, 10, gira_data(satt[28:36]))
            s2.put(1, 14, C.K5_ACIT); s2.put(15, 10, gira_data(satt[36:44]))
        elif satt[44:54].strip():                    # protocollo con NIU
            s1.put(1, 17, C.K1_ACIT); s1.put(18, 5, C.K6_ACIT)
            s1.put(23, 10, satt[44:54]); s1.put(33, 7, C.K3_ACTD)
            s1.put(40, 28, satt[:28])
            if data_ok:
                s2.put(1, 4, C.K6_ACIT_1); s2.put(5, 10, gira_data(satt[28:36]))
            s2.put(15, 15, C.K2_ACIT); s2.put(30, 10, gira_data(satt[36:44]))
        else:                                        # PRESENZA DI PROTOCOLLO
            s1.put(1, 24, C.K3_ACIT); s1.put(25, 28, satt[:28])
            if data_ok:
                s1.put(53, 5, C.K4_ACIT); s1.put(58, 10, gira_data(satt[28:36]))
            s2.put(1, 14, C.K5_ACIT); s2.put(15, 10, gira_data(satt[36:44]))
        L.chiudi()

    def _descr_ac_tds(self, ctx):
        L = ctx.tds
        s1, s2 = L.s1, L.s2
        satt = ctx.satt or ""
        data_ok = satt[28:36] != DATA_VUOTA

        if not satt[:28].strip():                    # ASSENZA DI PROTOCOLLO
            s1.put(1, 20, C.K1_ACTD_VB)
            if data_ok:
                s1.put(21, 5, C.K4_ACTD); s1.put(26, 10, gira_data(satt[28:36]))
            s2.put(1, 14, C.K2_ACTD); s2.put(15, 10, gira_data(satt[36:44]))
        elif satt[44:54].strip():                    # protocollo con NIU
            s1.put(1, 20, C.K1_ACTD_VB); s1.put(21, 5, C.K6_ACIT)
            s1.put(26, 10, satt[44:54]); s1.put(36, 7, C.K3_ACTD)
            if satt[0:4] == "INPS":
                s1.put(43, 4, "NISF"); s1.put(47, 24, satt[4:28])
            if data_ok:
                s2.put(1, 5, C.K4_ACTD); s2.put(6, 10, gira_data(satt[28:36]))
            s2.put(16, 14, C.K2_ACTD); s2.put(30, 10, gira_data(satt[36:44]))
        else:                                        # PRESENZA DI PROTOCOLLO
            s1.put(1, 30, C.K3_ACTD_VB); s1.put(31, 28, satt[:28])
            if data_ok:
                s1.put(59, 5, C.K4_ACTD); s1.put(64, 10, gira_data(satt[28:36]))
            s2.put(1, 14, C.K2_ACTD); s2.put(15, 10, gira_data(satt[36:44]))
        L.chiudi()

    # ================================================================== POSEIDONE (P)
    def _descr_a8_it(self, ctx):
        L = ctx.it
        s1, s2 = L.s1, L.s2
        satt = ctx.satt or ""
        s1.put(1, 16, C.P1_ACIT)
        if not satt[:28].strip():
            s1.put(17, 5, C.K4_ACIT); s1.put(22, 10, gira_data(satt[28:36]))
        else:
            s1.put(17, 7, C.K3_ACTD); s1.put(24, 28, satt[:28])
            s1.put(52, 5, C.K4_ACIT); s1.put(57, 10, gira_data(satt[28:36]))
        if satt[36:44] != DATA_VUOTA:
            s2.put(1, 14, C.K8_ACIT); s2.put(15, 10, gira_data(satt[36:44]))
        L.chiudi()

    def _descr_a8_tds(self, ctx):
        L = ctx.tds
        s1, s2 = L.s1, L.s2
        satt = ctx.satt or ""
        s1.put(1, 17, C.P1_ACTD)
        if not satt[:28].strip():
            s1.put(18, 5, C.K4_ACTD); s1.put(23, 10, gira_data(satt[28:36]))
        else:
            s1.put(18, 7, C.K3_ACTD); s1.put(25, 28, satt[:28])
            s1.put(53, 5, C.K4_ACTD); s1.put(58, 10, gira_data(satt[28:36]))
        if satt[36:44] != DATA_VUOTA:
            s2.put(1, 14, C.K2_ACTD); s2.put(15, 10, gira_data(satt[36:44]))
        L.chiudi()

    # ================================================================== ACCERTAMENTO UNIFICATO (C) / STUDI DI SETTORE (D)
    def _descr_au_it(self, ctx):
        L = ctx.it
        s1 = L.s1
        s1.put(1, 45, C.K1_AUIT); s1.put(46, 5, C.K2_AUIT); s1.put(51, 4, (ctx.satt or "")[:4])
        self._au_as_riga2_it(ctx, L)

    def _descr_as_it(self, ctx):
        L = ctx.it
        s1 = L.s1
        s1.put(1, 51, C.K1_ASIT); s1.put(52, 6, C.KA_OMGPIT); s1.put(58, 4, (ctx.satt or "")[:4])
        self._au_as_riga2_it(ctx, L)

    def _au_as_riga2_it(self, ctx, L):
        satt = ctx.satt or ""
        s2 = L.s2
        s2.put(1, 3, C.K3_AUIT_1); s2.put(4, 12, satt[4:16]); s2.put(16, 15, C.K2_ACIT)
        s2.put(31, 10, gira_data(satt[16:24]))
        if satt[24:40].strip():
            s2.put(41, 18, C.K4_ATTIIT); s2.put(59, 1, " "); s2.put(60, 16, satt[24:40])
        L.chiudi()

    def _descr_au_tds(self, ctx):
        L = ctx.tds
        L.s1.put(1, 47, C.K1_AUTD); L.s1.put(48, 5, C.K2_AUTD); L.s1.put(53, 4, (ctx.satt or "")[:4])
        self._au_as_riga2_tds(ctx, L, spazio=False)

    def _descr_as_tds(self, ctx):
        L = ctx.tds
        L.s1.put(1, 41, C.K1_ASTD); L.s1.put(42, 1, " ")
        L.s1.put(43, 5, C.K2_AUTD); L.s1.put(48, 4, (ctx.satt or "")[:4])
        self._au_as_riga2_tds(ctx, L, spazio=True)

    def _au_as_riga2_tds(self, ctx, L, spazio: bool):
        satt = ctx.satt or ""
        s2 = L.s2
        s2.put(1, 4, C.K3_AUTD_1); s2.put(5, 12, satt[4:16])
        if spazio:                                   # studi di settore: spazio in più
            s2.put(17, 1, " "); s2.put(18, 14, C.K2_ACTD); s2.put(32, 10, gira_data(satt[16:24]))
            base = 42
        else:
            s2.put(17, 14, C.K2_ACTD); s2.put(31, 10, gira_data(satt[16:24]))
            base = 41
        if satt[24:40].strip():
            s2.put(base, 12, C.K4_ATTITD); s2.put(base + 12, 16, satt[24:40])
        L.chiudi()

    # ================================================================== ACCERTAMENTO D'UFFICIO (E)
    def _descr_af_it(self, ctx):
        L = ctx.it
        s1, s2 = L.s1, L.s2
        satt = ctx.satt or ""
        data_ok = satt[28:36] != DATA_VUOTA

        s1.put(1, 14, C.K1_AFIT); s1.put(15, 1, C.K2_AFIT); s1.put(16, 7, C.K3_AFIT)
        if not satt[:28].strip():
            if data_ok:
                s1.put(23, 5, C.K4_ACIT); s1.put(28, 10, gira_data(satt[28:36]))
        else:
            s1.put(23, 7, C.K3_ACTD); s1.put(30, 28, satt[:28])
            if data_ok:
                s1.put(58, 5, C.K4_ACIT); s1.put(63, 10, gira_data(satt[28:36]))
        s2.put(1, 14, C.K5_ACIT); s2.put(15, 10, gira_data(satt[36:44]))
        L.chiudi()

    def _descr_af_tds(self, ctx):
        L = ctx.tds
        s1, s2 = L.s1, L.s2
        satt = ctx.satt or ""
        data_ok = satt[28:36] != DATA_VUOTA

        s1.put(1, 26, C.K1_AFTD)
        if not satt[:28].strip():
            if data_ok:
                s1.put(27, 5, C.K4_ACTD); s1.put(32, 10, gira_data(satt[28:36]))
            s2.put(1, 14, C.K2_ACTD); s2.put(15, 10, gira_data(satt[36:44]))
        else:
            s1.put(27, 7, C.K3_ACTD); s1.put(34, 28, satt[:28])
            if data_ok:                              # DATA VERBALE PRESENTE
                s2.put(1, 4, "VOM "); s2.put(5, 10, gira_data(satt[28:36]))
                s2.put(15, 14, C.K2_ACTD); s2.put(29, 10, gira_data(satt[36:44]))
            else:                                    # DATA VERBALE ASSENTE
                s2.put(1, 14, C.K2_ACTD); s2.put(15, 10, gira_data(satt[36:44]))
        L.chiudi()

    # ================================================================== EX-ENPALS (I, U)
    def _riga2_enpals(self, L, satt, k_del, k_not, presenza: bool):
        """Riga 2 comune a ACE/AFE: [DEL gg/mm/aaaa] NOTIFICATO IL gg/mm/aaaa."""
        s2 = L.s2
        if presenza and satt[40:48] != DATA_VUOTA:
            s2.put(1, 5, k_del); s2.put(6, 10, gira_data(satt[40:48])); s2.put(16, 1, " ")
            s2.put(17, 14, k_not); s2.put(31, 10, gira_data(satt[48:56]))
        else:
            s2.put(1, 14, k_not); s2.put(15, 10, gira_data(satt[48:56]))

    def _descr_ace_it(self, ctx):
        L = ctx.it
        s1 = L.s1
        satt = ctx.satt or ""
        if not satt[:40].strip():
            s1.put(1, 17, C.K1_ACIT)
            if satt[40:48] != DATA_VUOTA:
                s1.put(18, 5, C.K4_ACIT); s1.put(23, 10, gira_data(satt[40:48]))
            self._riga2_enpals(L, satt, C.K4_ACIT, C.K5_ACIT, presenza=False)
        else:
            s1.put(1, 24, C.K3_ACIT); s1.put(25, 40, satt[:40])
            self._riga2_enpals(L, satt, C.K4_ACIT, C.K5_ACIT, presenza=True)
        L.chiudi()

    def _descr_ace_tds(self, ctx):
        L = ctx.tds
        s1 = L.s1
        satt = ctx.satt or ""
        if not satt[:40].strip():
            s1.put(1, 18, C.K1_ACTD)
            if satt[40:48] != DATA_VUOTA:
                s1.put(19, 5, C.K4_ACTD); s1.put(24, 10, gira_data(satt[40:48]))
            self._riga2_enpals(L, satt, C.K4_ACTD, C.K2_ACTD, presenza=False)
        else:
            s1.put(1, 18, C.K1_ACTD); s1.put(19, 7, C.K3_ACTD); s1.put(26, 40, satt[:40])
            self._riga2_enpals(L, satt, C.K4_ACTD, C.K2_ACTD, presenza=True)
        L.chiudi()

    def _descr_afe_it(self, ctx):
        L = ctx.it
        s1 = L.s1
        satt = ctx.satt or ""
        s1.put(1, 14, C.K1_AFIT); s1.put(15, 1, C.K2_AFIT); s1.put(16, 7, C.K3_AFIT)
        if not satt[:40].strip():
            if satt[40:48] != DATA_VUOTA:
                s1.put(23, 5, C.K4_ACIT); s1.put(28, 10, gira_data(satt[40:48]))
            self._riga2_enpals(L, satt, C.K4_ACIT, C.K5_ACIT, presenza=False)
        else:
            s1.put(23, 7, C.K3_ACTD); s1.put(30, 40, satt[:40])
            self._riga2_enpals(L, satt, C.K4_ACIT, C.K5_ACIT, presenza=True)
        L.chiudi()

    def _descr_afe_tds(self, ctx):
        L = ctx.tds
        s1 = L.s1
        satt = ctx.satt or ""
        s1.put(1, 26, C.K1_AFTD)
        if not satt[:40].strip():
            if satt[40:48] != DATA_VUOTA:
                s1.put(27, 5, C.K4_ACTD); s1.put(32, 10, gira_data(satt[40:48]))
            self._riga2_enpals(L, satt, C.K4_ACTD, C.K2_ACTD, presenza=False)
        else:
            s1.put(27, 7, C.K3_ACTD); s1.put(34, 40, satt[:40])
            self._riga2_enpals(L, satt, C.K4_ACTD, C.K2_ACTD, presenza=True)
        L.chiudi()

    # ================================================================== PENSIONI (F)
    @staticmethod
    def _non_vuoto_non_lowvalue(porz: str) -> bool:
        return bool(porz.strip()) and porz != "\x00" * len(porz)

    def _descr_ap_it(self, ctx):
        L = ctx.it
        satt = ctx.satt or ""
        L.s1.put(1, 12, C.K1_APIT); L.s1.put(13, 10, ctx.cazi)
        porz = satt[:28]
        if self._non_vuoto_non_lowvalue(porz):
            L.s1.put(23, 3, " - "); L.s1.put(26, 40, C.K2_APIT)
            L.s2.put(1, 6, C.K3_APIT); L.s2.put(7, 28, porz)
            L.s2.put(35, 14, C.K5_ACIT); L.s2.put(49, 10, gira_data(satt[28:36]))
        L.chiudi()

    def _descr_ap_tds(self, ctx):
        L = ctx.tds
        sattbi = ctx.sattbi or ""
        L.s1.put(1, 17, C.K1_APTD); L.s1.put(18, 10, ctx.cazi)
        porz = sattbi[:28]
        if self._non_vuoto_non_lowvalue(porz):
            L.s1.put(28, 1, "-"); L.s1.put(29, 47, C.K2_APTD)
            L.s2.put(1, 7, C.K3_APTD); L.s2.put(8, 1, " "); L.s2.put(9, 28, porz)
            L.s2.put(37, 1, " "); L.s2.put(38, 14, C.K2_ACTD)
            L.s2.put(52, 10, gira_data(sattbi[28:36]))
        L.chiudi()

    # ================================================================== ART. 36 BIS (H)
    def _descr_art36_it(self, ctx):
        L = ctx.it
        satt = ctx.satt or ""
        L.s1.put(1, 51, C.K1_36IT); L.s1.put(52, 5, C.K2_AUIT); L.s1.put(57, 4, satt[:4])
        L.s2.put(1, 4, C.K2_36IT_1); L.s2.put(5, 12, satt[4:16]); L.s2.put(17, 15, C.K2_ACIT)
        L.s2.put(32, 10, gira_data(satt[16:24]))
        if satt[24:40].strip():                      # il COBOL IT controlla (25:16) ma sposta (33:16)
            L.s2.put(42, 18, C.K4_ATTIIT); L.s2.put(60, 16, satt[32:48])
        L.chiudi()

    def _descr_art36_tds(self, ctx):
        L = ctx.tds
        satt = ctx.satt or ""
        L.s1.put(1, 53, C.K1_36TD); L.s1.put(54, 6, C.KA_OMGPTD); L.s1.put(60, 4, satt[:4])
        L.s2.put(1, 8, C.K2_36TD_1); L.s2.put(9, 12, satt[4:16]); L.s2.put(21, 1, ",")
        L.s2.put(22, 14, C.K2_ACTD); L.s2.put(36, 10, gira_data(satt[16:24]))
        if satt[32:48].strip():
            L.s2.put(46, 2, ", "); L.s2.put(48, 12, C.K4_ATTITD); L.s2.put(60, 16, satt[32:48])
        L.chiudi()

    # ================================================================== ATTI DI DEFINIZIONE (G)
    def _descr_atti_it(self, ctx):
        L = ctx.it
        satt = ctx.satt or ""
        L.s1.put(1, 42, C.K1_ATTIIT); L.s1.put(43, 7, C.K2_ATTIIT); L.s1.put(50, 4, satt[:4])
        L.s1.put(54, 6, C.K3_ATTIIT); L.s1.put(60, 12, satt[4:16])
        L.s2.put(1, 14, C.K5_ACIT); L.s2.put(15, 10, gira_data(satt[16:24]))
        if satt[24:40].strip():
            L.s2.put(25, 18, C.K4_ATTIIT); L.s2.put(43, 1, " "); L.s2.put(44, 16, satt[24:40])
        L.chiudi()

    def _descr_atti_tds(self, ctx):
        L = ctx.tds
        satt = ctx.satt or ""
        L.s1.put(1, 44, C.K1_ATTITD); L.s1.put(45, 7, C.K2_ATTITD); L.s1.put(52, 4, satt[:4])
        L.s1.put(56, 7, C.K3_ATTITD); L.s1.put(63, 12, satt[4:16])
        L.s2.put(1, 14, C.K2_ACTD); L.s2.put(15, 10, gira_data(satt[16:24]))
        if satt[24:40].strip():
            L.s2.put(25, 3, " - "); L.s2.put(28, 12, C.K4_ATTITD); L.s2.put(40, 16, satt[24:40])
        L.chiudi()

    # ================================================================== COMUNICAZIONE IRREGOLARITA' (J)
    def _descr_irre_it(self, ctx):
        L = ctx.it
        satt = ctx.satt or ""
        L.s1.put(1, 24, C.K1_IRREIT); L.s1.put(25, 6, satt[:6]); L.s1.put(31, 5, C.K2_IRREIT)
        L.s1.put(36, 10, gira_data(satt[6:14]))
        if satt[14:30].strip():                      # altrimenti WS-SPAR2 conserva il valore precedente
            L.s2.put(1, 18, C.K4_ATTIIT_1); L.s2.put(19, 16, satt[14:30])
        L.chiudi()

    def _descr_irre_tds(self, ctx):
        L = ctx.tds
        satt = ctx.satt or ""
        L.s1.put(1, 15, C.K1_IRRETD); L.s1.put(16, 6, satt[:6]); L.s1.put(22, 5, C.K2_IRRETD)
        L.s1.put(27, 10, gira_data(satt[6:14]))
        if satt[14:30].strip():
            L.s2.put(1, 12, C.K4_ATTITD); L.s2.put(13, 16, satt[14:30])
        L.chiudi()

    # ================================================================== DISCONOSCIMENTO (M)
    def _descr_disc_it(self, ctx):
        L = ctx.it
        satt = ctx.satt or ""
        L.s1.spaces(); L.s2.spaces()
        L.s1.put(1, 12, C.K1_APIT); L.s1.put(13, 10, ctx.cazi); L.s1.put(23, 50, C.KM_DISC_IT)
        if ctx.ws_count1 == 0:
            L.s2.put(1, 6, C.K3_APIT); L.s2.put(7, 3, C.K3_AUIT_1); L.s2.put(10, 28, satt[:28])
        elif ctx.ws_count1 > 0:
            L.s2.put(1, 28, satt[:28])
        if satt[28:36] != DATA_VUOTA:
            L.s2.put(38, 14, C.K5_ACIT); L.s2.put(52, 10, gira_data(satt[28:36]))
        L.chiudi()

    def _descr_disc_tds(self, ctx):
        L = ctx.tds
        sattbi = ctx.sattbi or ""
        L.s1.spaces(); L.s2.spaces()
        L.s1.put(1, 18, C.K1_APTD); L.s1.put(19, 10, ctx.cazi); L.s1.put(29, 37, C.KM_DISC_TDS)
        if ctx.ws_count1 == 0:
            L.s2.put(1, 6, C.K3_APIT); L.s2.put(7, 3, C.K3_AUIT_1); L.s2.put(10, 28, sattbi[:28])
        elif ctx.ws_count1 > 0:
            L.s2.put(1, 28, sattbi[:28])
        if sattbi[28:36] != DATA_VUOTA:
            L.s2.put(38, 14, C.K5_ACIT); L.s2.put(52, 10, gira_data(sattbi[28:36]))
        L.chiudi()

    # ================================================================== VIG (V)
    def _descr_vig_it(self, ctx):
        L = ctx.it
        satt = ctx.satt or ""
        L.s1 = satt
        L.s2.spaces()
        L.chiudi()

    def _descr_vig_tds(self, ctx):
        L = ctx.tds
        L.s1 = ctx.desc_partita_3
        L.s2 = ctx.desc_partita_4
        L.chiudi()

    # ================================================================== AVVISO RECUPERO VARI (R)
    def _descr_vmc_it(self, ctx):
        L = ctx.it
        satt = ctx.satt or ""
        L.s1 = satt
        L.s2.spaces()
        L.chiudi()

    def _descr_vmc_tds(self, ctx):
        L = ctx.tds
        sattbi = ctx.sattbi or ""
        L.s1.put(1, 17, C.K1_RVMCTD); L.s1.put(18, 11, sattbi[24:35]); L.s1.put(29, 3, "vom")
        L.s1.put(33, len(sattbi[39:]), sattbi[39:])
        L.s2.spaces()
        L.chiudi()

    def _ctrl_ccau_avv24(self, ctx, depth):
        BatchLogger.debug(
            "CTRL-CCAU-AVV24",
            f"Verifica che codice causale è presente su ADCAVV24",
            depth=depth
        )
        t24 = self.engine.get_table_map("ADCAVV24")

        query_t24 = (
            self.engine.dataset("ADCAVV24")
            .select("gestione", "codiceAtto", "progrCausale", "codiceCausale", "identificativoAvviso",
                    "codiceAvviso", "timestampIns"
                    )
            .count()
            .filter_by("codiceCausale","IN", ("21", "22"))
            .filter_by("gestione", "=", ctx.ws_cges)
            .filter_by("codiceAtto", "=", ctx.catt)
            .with_uncommitted_read()
            .compile_select()
        )
        rows_t24 = self.engine.fetch(query_t24, depth=depth)

        if not rows_t24:
            BatchLogger.error("COUNT-ADCAVV24",
                              f"Nessun codice causale trovato su ADCAVV24 con CGES= {ctx.ws_cges} e CATT = {ctx.catt}",
                              depth=1, is_last=True)
            ctx.indic_errore = "X"
            return

        ctx.ws_count1 = t24.normalize(rows_t24[0])
