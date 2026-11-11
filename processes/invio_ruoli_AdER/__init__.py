# processes/invio_ruoli_AdER/__init__.py
"""
Package dedicato alla reingegnerizzazione del programma COBOL batch PDCINCRE.
"""

from .processor import InvioRuoliAdREEngineProcessor

__all__ = ["InvioRuoliAdREEngineProcessor"]