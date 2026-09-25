import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from .models import Workflow


class WorkflowStore:
    """JSON-backed workflow persistence."""

    def __init__(self, path: Path | str | None = None) -> None:
        if path is None:
            path = Path(__file__).resolve().parents[1] / "data" / "workflows.json"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._items: dict[str, Workflow] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if not isinstance(payload, list):
            return
        for item in payload:
            self._items[item["id"]] = Workflow.model_validate(item)

    def _persist(self) -> None:
        data = [workflow.model_dump(mode="json") for workflow in self._items.values()]
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temp_path.replace(self.path)

    def create(self, workflow: Workflow) -> Workflow:
        self._items[workflow.id] = workflow
        self._persist()
        return workflow

    def try_get(self, workflow_id: str) -> Workflow | None:
        return self._items.get(workflow_id)

    def get(self, workflow_id: str) -> Workflow:
        workflow = self.try_get(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return workflow

    def save(self, workflow: Workflow) -> Workflow:
        workflow.updated_at = datetime.now(timezone.utc)
        self._items[workflow.id] = workflow
        self._persist()
        return workflow

    def list_all(self) -> list[Workflow]:
        return list(self._items.values())
