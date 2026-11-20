# processes/firma_ruoli/__init__.py
"""
Package dedicato alla reingegnerizzazione del programma COBOL batch PDCFRPRO.
"""

from .processor import FirmaRuoliEngineProcessor

__all__ = ["FirmaRuoliEngineProcessor"]