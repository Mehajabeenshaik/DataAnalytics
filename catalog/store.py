"""
File-based, versioned store for the metric catalog.

Layout (no external DB required):
    data/catalog/
      current/
        metrics.yaml          # only approved metrics (the live catalog)
      proposals/
        <uuid>.yaml           # pending/approved/rejected proposals
      history/
        v001/
          metrics.yaml
          meta.json
        v002/
          ...

Every save of the approved catalog writes a new immutable snapshot under
history/ (a simple git-like version trail) so any change is auditable and
reversible.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import yaml

from .models import MetricDefinition, MetricProposal


class CatalogStore:
    """Low-level persistence for the metric catalog.

    This class is intentionally dumb — it only knows how to read/write YAML
    files and maintain the version history. All business logic (seeding,
    approval, rejection, LLM-visible filtering) lives in CatalogService.
    """

    def __init__(self, root: Path | str = Path("data/catalog")):
        self.root = Path(root)
        self.current = self.root / "current"
        self.proposals_dir = self.root / "proposals"
        self.history = self.root / "history"
        self.current.mkdir(parents=True, exist_ok=True)
        self.proposals_dir.mkdir(parents=True, exist_ok=True)
        self.history.mkdir(parents=True, exist_ok=True)

    # ── Approved catalog (current + history) ──────────────────────────────

    def load_approved(self) -> dict[str, MetricDefinition]:
        """Load the live approved catalog as {name: MetricDefinition}."""
        path = self.current / "metrics.yaml"
        if not path.exists():
            return {}
        raw = yaml.safe_load(path.read_text()) or {}
        return {k: MetricDefinition(**v) for k, v in raw.items()}

    def save_approved(
        self,
        metrics: dict[str, MetricDefinition],
        bump_version: bool = True,
        note: str | None = None,
    ) -> None:
        """Persist the approved catalog and (optionally) snapshot history."""
        data = {k: v.model_dump(mode="json") for k, v in metrics.items()}
        (self.current / "metrics.yaml").write_text(
            yaml.dump(data, sort_keys=False), encoding="utf-8"
        )
        if bump_version:
            self._write_history(metrics, note=note)

    def _write_history(
        self,
        metrics: dict[str, MetricDefinition],
        note: str | None = None,
    ) -> None:
        """Write an immutable snapshot of the current catalog to history/."""
        versions = sorted(self.history.glob("v*"))
        next_ver = f"v{len(versions) + 1:03d}"
        ver_dir = self.history / next_ver
        ver_dir.mkdir()

        data = {k: v.model_dump(mode="json") for k, v in metrics.items()}
        (ver_dir / "metrics.yaml").write_text(
            yaml.dump(data, sort_keys=False), encoding="utf-8"
        )

        meta = {
            "version": next_ver,
            "timestamp": datetime.utcnow().isoformat(),
            "count": len(metrics),
            "note": note,
        }
        (ver_dir / "meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )

    def list_versions(self) -> list[dict]:
        """Return metadata for every history snapshot, newest first."""
        versions = sorted(self.history.glob("v*"), reverse=True)
        result = []
        for ver_dir in versions:
            meta_path = ver_dir / "meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            else:
                meta = {"version": ver_dir.name, "count": 0}
            result.append(meta)
        return result

    # ── Proposals ─────────────────────────────────────────────────────────

    def save_proposal(self, proposal: MetricProposal) -> None:
        """Persist a proposal to proposals/<uuid>.yaml."""
        path = self.proposals_dir / f"{proposal.proposal_id}.yaml"
        path.write_text(
            yaml.dump(proposal.model_dump(mode="json"), sort_keys=False),
            encoding="utf-8",
        )

    def load_proposal(self, proposal_id: str) -> MetricProposal | None:
        """Load a single proposal by id, or None if it doesn't exist."""
        path = self.proposals_dir / f"{proposal_id}.yaml"
        if not path.exists():
            return None
        return MetricProposal(**yaml.safe_load(path.read_text()))

    def list_proposals(self) -> list[MetricProposal]:
        """Load every proposal file (any status)."""
        result = []
        for p in self.proposals_dir.glob("*.yaml"):
            try:
                result.append(MetricProposal(**yaml.safe_load(p.read_text())))
            except Exception:
                # Skip corrupt/partial proposal files rather than crashing.
                continue
        return result

    def list_pending(self) -> list[MetricProposal]:
        """Return only proposals still awaiting human review."""
        return [p for p in self.list_proposals() if p.status == "pending"]