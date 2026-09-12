# core/generic_repository.py
from typing import Optional, Dict, Any, List
from core.query_builder import EntityModel
from config.schema_mapper import TableMap


class GenericRepository:
    """
    Data Access Object universale collegato al BaseProcessModel.
    Gestisce qualsiasi tabella logica riutilizzando EntityModel e TableMap.
    """

    def __init__(self, process_context, logical_table_key: str):
        self.ctx = process_context
        self.logical_table_key = logical_table_key
        self.map: TableMap = self.ctx.get_table_map(logical_table_key)

    def _new_query(self) -> EntityModel:
        return self.ctx.dataset(self.logical_table_key)

    def find_one(self, filters: List[tuple], columns: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        """
        Estrae un singolo record normalizzato.
        :param filters: Lista di tuple nel formato (colonna_logica, operatore, valore)
        """
        q = self._new_query()
        if columns:
            q.select(*columns)
        for col, op, val in filters:
            q.filter_by(col, op, val)

        q.with_uncommitted_read()
        q.limit(1)

        rows = self.ctx.fetch(q.compile_select())
        if not rows:
            return None
        return self.map.normalize(rows[0])

    def find_all(self, filters: List[tuple], columns: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Estrae tutti i record normalizzati che soddisfano i criteri."""
        q = self._new_query()
        if columns:
            q.select(*columns)
        for col, op, val in filters:
            q.filter_by(col, op, val)

        q.with_uncommitted_read()
        rows = self.ctx.fetch(q.compile_select())
        return [self.map.normalize(r) for r in rows]

    def update_where(self, filters: List[tuple], set_values: Dict[str, Any]) -> int:
        """
        Esegue un'UPDATE parametrica sicura su qualsiasi tabella.
        """
        q = self._new_query()
        for col, op, val in filters:
            q.filter_by(col, op, val)

        compiled_upd = q.compile_update(set_values)
        return self.ctx.execute_mutation(compiled_upd)