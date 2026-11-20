# processes/firma_ruoli/context.py
import decimal
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional, Dict, Any, List, ClassVar
from decimal import Decimal

@dataclass
class Ar:
    LENGTH: ClassVar[int] = 113  # LENGTH OF AR (COPY CDCAR01)
    """Area di richiesta (COPY CDCAR01), passata a PDCXXCRE."""
    # --- AR-INPUT ---
    cdas: str = ""          # X(02)
    csed: str = ""          # X(02)
    czon: str = ""          # X(02)
    ccop: str = ""          # X(02)
    cdip: str = ""          # X(10)
    cambapp: str = ""       # X(01)
    rtrnims: str = ""       # X(08)
    cunilgc: str = ""       # X(10)
    cpgmges: str = ""       # X(08)
    nlnginp: int = 0        # 9(07)
    ntottab: int = 0        # 9(02)

    # --- AR-OUTPUT ---
    frcrdas: str = ""       # X(01)
    ntab: str = ""          # X(02)
    cmsg: str = ""          # X(06)
    htmslog: str = ""       # X(26)
    nlngout: int = 0        # 9(07)

    # --- AR-SERVIZIO ---
    fsgndbg: str = ""       # X(01)
    ar_errcode: int = 0     # 9(8) COMP  (4 byte, binario)
    if_massivo: str = ""    # X(01)
    ar_user_token: int = 0  # S9(8) COMP
    ar_pipe_token: int = 0  # S9(8) COMP

    # --- livelli 88 di FRCRDAS ---
    @property
    def frcrdas_tutto_ok(self) -> bool:
        return self.frcrdas == "0"

    @property
    def frcrdas_warning(self) -> bool:
        return self.frcrdas == "1"

    @property
    def frcrdas_critical(self) -> bool:
        return self.frcrdas == "2"

    # --- livelli 88 di FSGNDBG ---
    @property
    def fsgndbg_ko(self) -> bool:
        return self.fsgndbg == "0"

    @property
    def fsgndbg_ok(self) -> bool:
        return self.fsgndbg == "1"

    # --- livelli 88 di IF-MASSIVO ---
    @property
    def if_massivo_si(self) -> bool:
        return self.if_massivo == "S"

    @property
    def if_massivo_no(self) -> bool:
        return self.if_massivo in ("", " ")

    # --- REDEFINES AR-ERRCODE -> AR-ERRCODE1 ---
    @property
    def ar_sqlcode(self) -> bytes:
        """AR-SQLCODE X(03): primi 3 byte di AR-ERRCODE (big-endian)."""
        return self.ar_errcode.to_bytes(4, "big")[:3]

    @property
    def ar_filler1(self) -> bytes:
        """AR-FILLER1 X(01): quarto byte di AR-ERRCODE."""
        return self.ar_errcode.to_bytes(4, "big")[3:]


@dataclass
class FirmaRuoliContext:
    """
    Working-Storage Section specifica per il processo PDCFRPRO.
    Mantiene lo stato condiviso, i parametri di input e i registri runtime.
    """
    # Parametri CLI / Batch
    sk_data_invio: Optional[date] = None
    sk_data_firma: Optional[date] = None
    data_elaborazione: Optional[date] = None
    data_limite_formazione: Optional[date] = None
    sede_filter: Optional[str] = None
    size_commit: int = 1000

    # Date di sistema
    data_sql_com: str = ""                     # WS-DATA-SQL-COM (AAAAMMGG)
    data_estr_ini: Optional[date] = None       # CURRENT DATE - 1
    data_estr_fin: Optional[date] = None       # CURRENT DATE + 1

    # Area di richiesta (COM-AREA.WS-CDCAR01.AR)
    ar: Ar = field(default_factory=Ar)


    # =========================================================================
    # REGISTRI CONTATORI E DIAGNOSTICA SPECIFICI PDCFORUO
    # =========================================================================
    # WS-CTR-NRUO e WS-CTR-RIGHE
    ws_ctr_nruo: int = 0
    ws_ctr_righe: int = 0
    ws_nart: int = 0

    # WS-NOME-TAB (Diagnostica / SQL Error Logging)
    ws_nome_tab: str = ""

    # WS-INDICI (Puntatori / Indici di scorrimento tabelle ed elenchi)
    ws_indici: Dict[str, int] = field(default_factory=lambda: {
        "ind_tab": 0,
        "ind_riga": 0,
        "ind_art": 0
    })

    # =========================================================================
    # CAMPI DI LAVORO (WORKING-STORAGE: WS-COMODI / IMP-COMODI-KEY)
    # =========================================================================
    ws_cesa: int = 0
    ws_arifruo: int = 0
    ws_nruo: int = 0


    @property
    def dinf_cdcfrt01(self) -> date:
        if self.sk_data_firma is None:
            return date(9999, 12, 31)
        return self.sk_data_firma