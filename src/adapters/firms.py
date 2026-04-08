"""FIRMSAdapter — NASA FIRMS thermal anomaly corroboration."""
from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timedelta
from pathlib import Path

from adapters.base import MissingCredentialsError, ReconAdapter, ReconHit

log = logging.getLogger("hanna.recon")


class FIRMSAdapter(ReconAdapter):
    """
    NASA FIRMS thermal-anomaly corroboration adapter.

    Queries FIRMS (Fire Information for Resource Management System) for
    satellite-detected thermal anomalies in a bounding box around known
    coordinates.  Coordinate sources (checked in order):
      1. FIRMS_LAT / FIRMS_LON env vars (manual override)
      2. STIX 2.1 *location* objects in recent Drop-Zone bundles

    Returns ReconHit(observable_type="thermal_anomaly") with raw FRP,
    brightness, sensor confidence, distance-from-origin, and satellite
    metadata.

    Env vars
    --------
    FIRMS_MAP_KEY    — NASA FIRMS API key  (required, free from NASA)
    FIRMS_LAT        — centre latitude     (optional)
    FIRMS_LON        — centre longitude    (optional)
    FIRMS_RADIUS_KM  — search radius, km   (default 25)
    HANNA_DROP_ZONE  — path to drop zone   (for STIX coordinate scan)
    """

    name = "firms"
    region = "global"

    _BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
    _SOURCES = ("VIIRS_NOAA20_NRT", "VIIRS_SNPP_NRT", "MODIS_NRT")
    _KM_TO_DEG = 1.0 / 111.0  # approx at equator

    # ── search entry-point ──

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        map_key = os.environ.get("FIRMS_MAP_KEY", "")
        if not map_key:
            raise MissingCredentialsError("FIRMS_MAP_KEY")

        coords = self._gather_coordinates()
        if not coords:
            log.info("FIRMS: no coordinates available for corroboration")
            return []

        hits: list[ReconHit] = []
        for lat, lon, origin in coords:
            bbox = self._bbox(lat, lon)
            for src in self._SOURCES:
                for row in self._query(map_key, src, bbox):
                    hit = self._row_to_hit(row, lat, lon, src, origin, target_name)
                    if hit:
                        hits.append(hit)
        return self._dedup(hits)

    # ── coordinate gathering ──

    def _gather_coordinates(self) -> list[tuple[float, float, str]]:
        coords: list[tuple[float, float, str]] = []
        lat_s = os.environ.get("FIRMS_LAT", "")
        lon_s = os.environ.get("FIRMS_LON", "")
        if lat_s and lon_s:
            try:
                coords.append((float(lat_s), float(lon_s), "env_override"))
            except ValueError:
                pass

        dz = os.environ.get("HANNA_DROP_ZONE", "")
        if dz:
            coords.extend(self._scan_drop_zone(Path(dz)))
        return coords[:10]

    def _scan_drop_zone(self, dz: Path) -> list[tuple[float, float, str]]:
        if not dz.is_dir():
            return []
        cutoff = datetime.now() - timedelta(hours=6)
        out: list[tuple[float, float, str]] = []
        for rpt in sorted(dz.glob("*/report.json"), reverse=True)[:20]:
            try:
                if datetime.fromtimestamp(rpt.stat().st_mtime) < cutoff:
                    continue
                with open(rpt, encoding="utf-8") as f:
                    bundle = json.load(f)
                for obj in bundle.get("objects", []):
                    if obj.get("type") == "location":
                        lat = obj.get("latitude")
                        lon = obj.get("longitude")
                        if lat is not None and lon is not None:
                            out.append((float(lat), float(lon),
                                        f"stix:{rpt.parent.name}"))
            except (json.JSONDecodeError, OSError, ValueError, KeyError):
                continue
        return out

    # ── FIRMS HTTP layer ──

    def _bbox(self, lat: float, lon: float) -> str:
        r = float(os.environ.get("FIRMS_RADIUS_KM", "25")) * self._KM_TO_DEG
        w = max(-180.0, lon - r)
        s = max(-90.0, lat - r)
        e = min(180.0, lon + r)
        n = min(90.0, lat + r)
        return f"{w:.4f},{s:.4f},{e:.4f},{n:.4f}"

    def _query(self, key: str, source: str, bbox: str,
              day_range: int = 2) -> list[dict[str, str]]:
        url = f"{self._BASE}/{key}/{source}/{bbox}/{day_range}"
        status, body = self._fetch(url)
        if status != 200 or not body or body.lstrip().startswith("<"):
            return []
        return self._parse_csv(body)

    @staticmethod
    def _parse_csv(text: str) -> list[dict[str, str]]:
        lines = text.strip().split("\n")
        if len(lines) < 2:
            return []
        hdr = [h.strip() for h in lines[0].split(",")]
        rows: list[dict[str, str]] = []
        for ln in lines[1:]:
            vals = ln.split(",")
            if len(vals) == len(hdr):
                rows.append(dict(zip(hdr, (v.strip() for v in vals))))
        return rows

    # ── Hit conversion ──

    def _row_to_hit(
        self, row: dict, o_lat: float, o_lon: float,
        source: str, origin: str, target_name: str,
    ) -> ReconHit | None:
        try:
            lat = float(row["latitude"])
            lon = float(row["longitude"])
        except (KeyError, ValueError, TypeError):
            return None

        dist = self._haversine(o_lat, o_lon, lat, lon)
        frp = self._safe_float(row.get("frp", "0"))

        # sensor confidence
        raw_c = row.get("confidence", "")
        if raw_c in ("h", "high"):
            sc = 0.9
        elif raw_c in ("n", "nominal"):
            sc = 0.7
        elif raw_c in ("l", "low"):
            sc = 0.4
        else:
            sc = min(1.0, self._safe_float(raw_c) / 100) if raw_c else 0.5

        radius = float(os.environ.get("FIRMS_RADIUS_KM", "25"))
        dist_decay = max(0.3, 1.0 - dist / radius)
        frp_bonus = min(0.15, frp / 200)
        conf = round(min(1.0, dist_decay * sc + frp_bonus), 2)

        return ReconHit(
            observable_type="thermal_anomaly",
            value=f"{lat:.5f},{lon:.5f}",
            source_module=self.name,
            source_detail=f"firms_{source.lower()}",
            confidence=conf,
            timestamp=datetime.now().isoformat(),
            raw_record={
                "latitude": lat, "longitude": lon,
                "frp": frp,
                "brightness": row.get("bright_ti4") or row.get("brightness") or "",
                "sensor_confidence": raw_c,
                "acq_date": row.get("acq_date", ""),
                "acq_time": row.get("acq_time", ""),
                "daynight": row.get("daynight", ""),
                "satellite": row.get("satellite", ""),
                "source": source,
                "distance_km": round(dist, 2),
                "origin_lat": o_lat, "origin_lon": o_lon,
                "origin_label": origin,
            },
            cross_refs=[target_name, origin],
        )

    # ── helpers ──

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        R = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(lat1))
             * math.cos(math.radians(lat2))
             * math.sin(dlon / 2) ** 2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    @staticmethod
    def _safe_float(v: str, default: float = 0.0) -> float:
        try:
            return float(v)
        except (ValueError, TypeError):
            return default

    def _dedup(self, hits: list[ReconHit], min_km: float = 0.5) -> list[ReconHit]:
        if not hits:
            return hits
        kept = [hits[0]]
        for h in hits[1:]:
            lat2 = h.raw_record.get("latitude", 0)
            lon2 = h.raw_record.get("longitude", 0)
            replaced = False
            for i, k in enumerate(kept):
                d = self._haversine(
                    k.raw_record.get("latitude", 0),
                    k.raw_record.get("longitude", 0),
                    lat2, lon2,
                )
                if d < min_km:
                    if h.confidence > k.confidence:
                        kept[i] = h
                    replaced = True
                    break
            if not replaced:
                kept.append(h)
        return kept
