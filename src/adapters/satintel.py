"""SatIntelAdapter — Satellite Intelligence + EXIF GEOINT."""
from __future__ import annotations

import json
import os
import struct
from datetime import datetime
from pathlib import Path
from typing import Any

from adapters.base import ReconAdapter, ReconHit


class SatIntelAdapter(ReconAdapter):
    """
    Satellite Intelligence + EXIF GEOINT adapter.

    Capabilities:
      - EXIF GPS coordinate extraction from local image files
      - Reverse geocoding of extracted coordinates
      - Satellite overpass time queries (for imagery request planning)

    Env vars:
      SATINTEL_IMAGE_DIR — directory with target photos to analyze EXIF
    """

    name = "satintel"
    region = "global"

    def search(
        self,
        target_name: str,
        known_phones: list[str],
        known_usernames: list[str],
    ) -> list[ReconHit]:
        hits: list[ReconHit] = []

        # 1. Scan local images for EXIF GPS data
        image_dir = os.environ.get("SATINTEL_IMAGE_DIR", "")
        scanned_source = False
        if image_dir:
            scanned_source = True
            hits.extend(self._scan_exif_gps(Path(image_dir), target_name))
        else:
            # Default scan locations
            from config import PROFILES_DIR
            for default_dir in [
                PROFILES_DIR,
            ]:
                if default_dir.exists():
                    scanned_source = True
                    hits.extend(self._scan_exif_gps(default_dir, target_name))

        if not scanned_source:
            self._record_noop("no image corpus available for SatIntel EXIF scan")
            return hits

        # 2. For any found coordinates, do reverse geocoding
        coord_hits = [h for h in hits if h.observable_type == "coordinates"]
        if not coord_hits and not hits:
            self._record_noop("no EXIF GPS coordinates found for SatIntel")
            return hits
        for ch in coord_hits:
            lat, lon = ch.raw_record.get("lat"), ch.raw_record.get("lon")
            if lat and lon:
                geo_hits = self._reverse_geocode(lat, lon, ch.raw_record.get("source_file", ""))
                hits.extend(geo_hits)

        return hits

    def _scan_exif_gps(self, directory: Path, target_name: str) -> list[ReconHit]:
        """Extract GPS coordinates from EXIF data in image files."""
        hits: list[ReconHit] = []
        image_extensions = {".jpg", ".jpeg", ".tiff", ".tif", ".heic", ".png"}

        try:
            files = list(directory.rglob("*"))
        except PermissionError:
            return hits

        for fpath in files[:500]:
            if fpath.suffix.lower() not in image_extensions:
                continue
            if not fpath.is_file():
                continue

            coords = self._extract_gps_from_jpeg(fpath)
            if coords:
                lat, lon = coords
                hits.append(ReconHit(
                    observable_type="coordinates",
                    value=f"{lat:.6f},{lon:.6f}",
                    source_module=self.name,
                    source_detail=f"exif_gps:{fpath.name}",
                    confidence=0.8,
                    timestamp=datetime.now().isoformat(),
                    raw_record={
                        "lat": lat, "lon": lon,
                        "source_file": str(fpath),
                        "file_name": fpath.name,
                    },
                ))

        return hits

    @staticmethod
    def _extract_gps_from_jpeg(filepath: Path) -> tuple[float, float] | None:
        """
        Extract GPS coordinates from JPEG EXIF without external libraries.
        Reads raw EXIF APP1 segment and parses IFD0 → GPS IFD.
        """
        try:
            with open(filepath, "rb") as f:
                # Check JPEG SOI marker
                if f.read(2) != b'\xff\xd8':
                    return None

                # Find APP1 (EXIF) marker
                while True:
                    marker = f.read(2)
                    if len(marker) < 2:
                        return None
                    if marker == b'\xff\xe1':  # APP1
                        break
                    if marker[0:1] != b'\xff':
                        return None
                    seg_len = struct.unpack('>H', f.read(2))[0]
                    f.seek(seg_len - 2, 1)

                seg_len = struct.unpack('>H', f.read(2))[0]
                exif_data = f.read(seg_len - 2)

                # Check "Exif\x00\x00" header
                if not exif_data.startswith(b'Exif\x00\x00'):
                    return None

                tiff_data = exif_data[6:]
                if tiff_data[:2] == b'MM':
                    endian = '>'
                elif tiff_data[:2] == b'II':
                    endian = '<'
                else:
                    return None

                ifd0_offset = struct.unpack(f'{endian}I', tiff_data[4:8])[0]

                gps_offset = SatIntelAdapter._find_tag_in_ifd(
                    tiff_data, ifd0_offset, 0x8825, endian
                )
                if not gps_offset:
                    return None

                return SatIntelAdapter._parse_gps_ifd(tiff_data, gps_offset, endian)

        except (OSError, struct.error, IndexError, ValueError):
            return None

    @staticmethod
    def _find_tag_in_ifd(data: bytes, ifd_offset: int, target_tag: int, endian: str) -> int | None:
        """Find a specific tag value in an IFD."""
        try:
            num_entries = struct.unpack(f'{endian}H', data[ifd_offset:ifd_offset + 2])[0]
            for i in range(num_entries):
                entry_offset = ifd_offset + 2 + i * 12
                tag = struct.unpack(f'{endian}H', data[entry_offset:entry_offset + 2])[0]
                if tag == target_tag:
                    value = struct.unpack(f'{endian}I', data[entry_offset + 8:entry_offset + 12])[0]
                    return value
        except (struct.error, IndexError):
            pass
        return None

    @staticmethod
    def _parse_gps_ifd(data: bytes, gps_offset: int, endian: str) -> tuple[float, float] | None:
        """Parse GPS IFD entries to extract lat/lon."""
        try:
            num_entries = struct.unpack(f'{endian}H', data[gps_offset:gps_offset + 2])[0]
            gps_tags: dict[int, Any] = {}

            for i in range(num_entries):
                entry_offset = gps_offset + 2 + i * 12
                tag = struct.unpack(f'{endian}H', data[entry_offset:entry_offset + 2])[0]
                type_id = struct.unpack(f'{endian}H', data[entry_offset + 2:entry_offset + 4])[0]
                count = struct.unpack(f'{endian}I', data[entry_offset + 4:entry_offset + 8])[0]
                value_offset = struct.unpack(f'{endian}I', data[entry_offset + 8:entry_offset + 12])[0]

                if type_id == 2:  # ASCII (lat/lon ref: N/S/E/W)
                    if count <= 4:
                        val = data[entry_offset + 8:entry_offset + 8 + count].decode('ascii', errors='ignore').strip('\x00')
                    else:
                        val = data[value_offset:value_offset + count].decode('ascii', errors='ignore').strip('\x00')
                    gps_tags[tag] = val
                elif type_id == 5 and count == 3:  # RATIONAL x3 (DMS)
                    rationals = []
                    for j in range(3):
                        num = struct.unpack(f'{endian}I', data[value_offset + j * 8:value_offset + j * 8 + 4])[0]
                        den = struct.unpack(f'{endian}I', data[value_offset + j * 8 + 4:value_offset + j * 8 + 8])[0]
                        rationals.append(num / den if den else 0.0)
                    gps_tags[tag] = rationals

            lat_ref = gps_tags.get(1, "N")
            lat_dms = gps_tags.get(2)
            lon_ref = gps_tags.get(3, "E")
            lon_dms = gps_tags.get(4)

            if not lat_dms or not lon_dms:
                return None

            lat = lat_dms[0] + lat_dms[1] / 60.0 + lat_dms[2] / 3600.0
            lon = lon_dms[0] + lon_dms[1] / 60.0 + lon_dms[2] / 3600.0

            if lat_ref == "S":
                lat = -lat
            if lon_ref == "W":
                lon = -lon

            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return (lat, lon)

        except (struct.error, IndexError, ValueError, ZeroDivisionError):
            pass
        return None

    def _reverse_geocode(self, lat: float, lon: float, source_file: str) -> list[ReconHit]:
        """Reverse geocode coordinates via Nominatim."""
        hits: list[ReconHit] = []
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=16"
        status, body = self._fetch(url, headers={"Accept": "application/json"})
        if status == 200 and body:
            try:
                data = json.loads(body)
                display = data.get("display_name", "")
                if display:
                    hits.append(ReconHit(
                        observable_type="location",
                        value=display,
                        source_module=self.name,
                        source_detail=f"reverse_geocode:{lat:.4f},{lon:.4f}",
                        confidence=0.7,
                        timestamp=datetime.now().isoformat(),
                        raw_record={
                            "lat": lat, "lon": lon,
                            "address": data.get("address", {}),
                            "display_name": display,
                            "source_file": source_file,
                        },
                    ))
            except json.JSONDecodeError:
                pass
        return hits
