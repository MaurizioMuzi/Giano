# core/models/ad_commarea.py
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import List, Optional


# =========================================================================
# ENUM / LIVELLI 88 COBOL
# =========================================================================

class codVersPagPaginazione(IntEnum):
    """Corrisponde ai livelli 88 su CAMPO5 PIC 9(01)."""
    NO_PAGINA = 0
    PAGINA_AVANTI = 1
    PAGINA_INDIETRO = 2
    PAGINA_PRIMA = 3
    PAGINA_ULTIMA = 4


class codOperazAzione(str, Enum):
    INSERIRE = "C"
    VARIARE = "U"
    CANCELLARE = "D"

# =========================================================================
# ENUM / LIVELLI 88 COBOL - STRUTTURA AR (AREA RICHIESTA - TEST)
# =========================================================================

class frcrDasStatoEsito(str, Enum):
    """Corrisponde ai livelli 88 su FRCRDAS PIC X(01) in AR-OUTPUT."""
    TUTTO_OK = "0"
    WARNING = "1"
    CRITICAL = "2"


class fsgnDbgStatoServizio(str, Enum):
    """Corrisponde ai livelli 88 su FSGNDBG PIC X(01) in AR-SERVIZIO."""
    KO = "0"
    OK = "1"


class ifMassivoFlag(str, Enum):
    """Corrisponde ai livelli 88 su IF-MASSIVO PIC X(01) in AR-SERVIZIO."""
    SI = "S"
    NO = " "

# =========================================================================
# LIVELLI DI DETTAGLIO E SOTTO-STRUTTURE
# =========================================================================

@dataclass
class AdcampiKeyFiltri:
    """15 campiKey (Filtri per intervalli di selezione)."""
    codEsattoria_da: int = 0
    codEsattoria_a: int = 0
    annoRif_da: int = 0
    annoRif_a: int = 0
    numRuolo_da: int = 0
    numRuolo_a: int = 0
    filler: str = ""


@dataclass
class AdInput:
    """10 AD-INPUT."""
    numTab: str = ""
    lunRiga: int = 0
    numRighe: int = 0
    flgMod: int = 0
    codVersPag: int = codVersPagPaginazione.NO_PAGINA.value
    campiKey: AdcampiKeyFiltri = field(default_factory=AdcampiKeyFiltri)


@dataclass
class AdOutput:
    """10 AD-OUTPUT."""
    codMessaggio: str = ""
    numCelTot: int = 0
    flgMre: str = ""


@dataclass
class RigaTabella:
    """Elemento ripetuto 15 RIGA-TAB OCCURS 40."""
    codEsattoria: int = 0
    annoRif: int = 0
    numRuolo: int = 0
    codTributoCnc: str = ""
    annoRifCont: int = 0
    numRate: int = 0
    codRata: str = ""
    flgResiduo: str = ""
    impTributo: int = 0
    numArticoli: int = 0
    impAggioAnt: int = 0
    impAggioTot: int = 0
    impArrotondamento: int = 0
    impCarico: int = 0
    codOperaz: str = codOperazAzione.INSERIRE.value


@dataclass
class AdTabella:
    """10 AD-TABELLA."""
    righe: List[RigaTabella] = field(default_factory=list)

# =========================================================================
# LIVELLI DI DETTAGLIO E SOTTO-STRUTTURE - STRUTTURA AR (TEST)
# =========================================================================

@dataclass
class ArInput:
    """10 AR-INPUT (Posizioni 1 - 54, Lun: 54 byte)."""
    codServizio: str = ""
    sede: str = ""
    zona: str = ""
    codCentro: str = ""
    codDipendente: str = ""
    cambAppl: str = ""
    rtrNims: str = ""
    cuniLgc: str = ""
    cpgMges: str = ""
    nlngInp: int = 0
    ntotTab: int = 0

@dataclass
class ArOutput:
    """10 AR-OUTPUT (Posizioni 55 - 96, Lun: 42 byte)."""
    frcrDas: str = frcrDasStatoEsito.TUTTO_OK.value
    nTab: str = ""
    cMsg: str = ""
    htmsLog: str = ""
    nlngOut: int = 0


@dataclass
class ArServizio:
    """10 AR-SERVIZIO (Posizioni 97 - 113, Lun: 17 byte)."""
    fsgnDbg: str = fsgnDbgStatoServizio.KO.value

    ar_errore: int = 0
    ar_sqlCode: str = ""
    ar_filler1: str = ""

    ifMassivo: str = ifMassivoFlag.NO.value
    ar_user_token: int = 0
    ar_pipe_token: int = 0
    filler: str = ""

# =========================================================================
# STRUTTURE RADICE COMMAREA / AREA RICHIESTA
# =========================================================================

@dataclass
class AreaRichiestaTest:
    """
    05 AR. (AREA RICHIESTA - NOME: TEST, LUNGHEZZA: 113 BYTE).
    """
    ar_input: ArInput = field(default_factory=ArInput)
    ar_output: ArOutput = field(default_factory=ArOutput)
    ar_servizio: ArServizio = field(default_factory=ArServizio)

# =========================================================================
# STRUTTURA RADICE DELLA COMMAREA
# =========================================================================

@dataclass
class AdCommarea:
    """05 AD (Radice della struttura di comunicazione)."""
    ad_input: AdInput = field(default_factory=AdInput)
    ad_output: AdOutput = field(default_factory=AdOutput)
    ad_tabella: AdTabella = field(default_factory=AdTabella)

    # Esito chiamata (standard di ritorno di livello applicativo)
    rc_esito: int = 0
    msg_errore: str = ""