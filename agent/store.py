"""
Incident storage, behind a small interface so the same agent code runs
against a local JSON file (zero cloud dependencies, for the hackathon demo
and local dev) or against Firestore (for the real GCP deployment).

Select the backend with the STORE_BACKEND env var: "local" (default) or
"firestore".
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import List, Optional

from .models import Incident, Runbook

_LOCK = threading.Lock()


class IncidentStore:
    """Interface. See LocalJSONStore and FirestoreStore below."""

    def save_incident(self, incident: Incident) -> None:
        raise NotImplementedError

    def get_incident(self, incident_id: str) -> Optional[Incident]:
        raise NotImplementedError

    def list_incidents(self) -> List[Incident]:
        raise NotImplementedError

    def find_by_source_event_id(self, source_event_id: str) -> Optional[Incident]:
        raise NotImplementedError

    def save_runbook(self, runbook: Runbook) -> None:
        raise NotImplementedError

    def list_runbooks(self) -> List[Runbook]:
        raise NotImplementedError


class LocalJSONStore(IncidentStore):
    """
    Zero-dependency store used for local development and the hackathon
    demo. Everything lives in agent/data/db.json. Not for production use
    (no concurrency guarantees beyond a process-local lock), but it means
    `docker-compose up` works with no GCP project at all.
    """

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path or os.getenv("LOCAL_DB_PATH", "agent/data/db.json"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"incidents": {}, "runbooks": {}})

    def _read(self) -> dict:
        with open(self.path) as f:
            return json.load(f)

    def _write(self, data: dict) -> None:
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def save_incident(self, incident: Incident) -> None:
        with _LOCK:
            data = self._read()
            data["incidents"][incident.id] = json.loads(incident.model_dump_json())
            self._write(data)

    def get_incident(self, incident_id: str) -> Optional[Incident]:
        data = self._read()
        raw = data["incidents"].get(incident_id)
        return Incident(**raw) if raw else None

    def list_incidents(self) -> List[Incident]:
        data = self._read()
        incidents = [Incident(**v) for v in data["incidents"].values()]
        return sorted(incidents, key=lambda i: i.created_at, reverse=True)

    def find_by_source_event_id(self, source_event_id: str) -> Optional[Incident]:
        data = self._read()
        for raw in data["incidents"].values():
            if raw.get("source_event_id") == source_event_id:
                return Incident(**raw)
        return None

    def save_runbook(self, runbook: Runbook) -> None:
        with _LOCK:
            data = self._read()
            data["runbooks"][runbook.id] = json.loads(runbook.model_dump_json())
            self._write(data)

    def list_runbooks(self) -> List[Runbook]:
        data = self._read()
        runbooks = [Runbook(**v) for v in data["runbooks"].values()]
        return sorted(runbooks, key=lambda r: r.created_at, reverse=True)


class FirestoreStore(IncidentStore):
    """
    Production backend. Requires google-cloud-firestore and a GCP project
    with Firestore in Native mode enabled. This is what the dashboard's
    real-time listeners read from once deployed.
    """

    def __init__(self, project: Optional[str] = None):
        from google.cloud import firestore  # imported lazily: optional dep

        self.client = firestore.Client(project=project or os.getenv("GCP_PROJECT"))
        self.incidents = self.client.collection("incidents")
        self.runbooks = self.client.collection("runbooks")

    def save_incident(self, incident: Incident) -> None:
        self.incidents.document(incident.id).set(json.loads(incident.model_dump_json()))

    def get_incident(self, incident_id: str) -> Optional[Incident]:
        doc = self.incidents.document(incident_id).get()
        return Incident(**doc.to_dict()) if doc.exists else None

    def list_incidents(self) -> List[Incident]:
        docs = self.incidents.order_by("created_at", direction="DESCENDING").stream()
        return [Incident(**d.to_dict()) for d in docs]

    def find_by_source_event_id(self, source_event_id: str) -> Optional[Incident]:
        docs = self.incidents.where("source_event_id", "==", source_event_id).limit(1).stream()
        doc = next(iter(docs), None)
        return Incident(**doc.to_dict()) if doc else None

    def save_runbook(self, runbook: Runbook) -> None:
        self.runbooks.document(runbook.id).set(json.loads(runbook.model_dump_json()))

    def list_runbooks(self) -> List[Runbook]:
        docs = self.runbooks.order_by("created_at", direction="DESCENDING").stream()
        return [Runbook(**d.to_dict()) for d in docs]


def get_store() -> IncidentStore:
    backend = os.getenv("STORE_BACKEND", "local")
    if backend == "firestore":
        return FirestoreStore()
    return LocalJSONStore()
