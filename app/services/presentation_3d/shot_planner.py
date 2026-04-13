from __future__ import annotations

from typing import Any


def _room_matches(room: dict[str, Any], keywords: set[str]) -> bool:
    room_type = str(room.get("type") or "").lower()
    name = str(room.get("name") or "").lower()
    return any(keyword in room_type or keyword in name for keyword in keywords)


def _pick_room(rooms: list[dict[str, Any]], keywords: set[str], *, used_ids: set[str]) -> dict[str, Any] | None:
    for room in rooms:
        room_id = str(room.get("id") or "")
        if room_id in used_ids:
            continue
        if _room_matches(room, keywords):
            used_ids.add(room_id)
            return room
    return None


def build_shot_plan(geometry: dict[str, Any]) -> dict[str, Any]:
    rooms = [room for room in geometry.get("rooms", []) if room.get("type") not in {"terrace", "wc", "bathroom", "powder", "laundry"}]
    used_ids: set[str] = set()

    living_room = _pick_room(rooms, {"living", "khach"}, used_ids=used_ids)
    kitchen_dining = _pick_room(rooms, {"kitchen", "dining", "bep", "an"}, used_ids=used_ids)
    master_bedroom = _pick_room(rooms, {"master", "bedroom", "ngu"}, used_ids=used_ids)

    fallback_rooms = [room for room in rooms if str(room.get("id") or "") not in used_ids]

    def _room_or_fallback(preferred: dict[str, Any] | None, fallback_index: int) -> dict[str, Any] | None:
        if preferred:
            return preferred
        if fallback_index < len(fallback_rooms):
            room = fallback_rooms[fallback_index]
            used_ids.add(str(room.get("id") or ""))
            return room
        return None

    living_room = _room_or_fallback(living_room, 0)
    kitchen_dining = _room_or_fallback(kitchen_dining, 1)
    master_bedroom = _room_or_fallback(master_bedroom, 2)

    still_shots: list[dict[str, Any]] = [
        {
            "shot_id": "exterior_hero_day",
            "asset_role": "hero_exterior",
            "title_vi": "Phối cảnh mặt tiền chính",
            "category": "exterior",
            "camera": {"azimuth_deg": 25, "elevation_deg": 18, "lens_mm": 24},
        },
        {
            "shot_id": "exterior_entry",
            "asset_role": "entry_exterior",
            "title_vi": "Góc tiếp cận lối vào",
            "category": "exterior",
            "camera": {"azimuth_deg": 8, "elevation_deg": 12, "lens_mm": 28},
        },
    ]

    for shot_id, asset_role, room in [
        ("living_room", "living_room_main", living_room),
        ("kitchen_dining", "kitchen_dining_main", kitchen_dining),
        ("master_bedroom", "master_bedroom_main", master_bedroom),
    ]:
        if not room:
            continue
        still_shots.append(
            {
                "shot_id": shot_id,
                "asset_role": asset_role,
                "title_vi": str(room.get("name") or shot_id).title(),
                "category": "interior",
                "room_id": room.get("id"),
                "room_name": room.get("name"),
                "camera": {"azimuth_deg": 35, "elevation_deg": 12, "lens_mm": 24},
            }
        )

    walkthrough_sequence = [
        {
            "segment_id": "walkthrough_main",
            "title_vi": "Walkthrough tổng quan",
            "fps": 30,
            "duration_target_seconds": 60,
            "stops": [
                {"shot_id": shot["shot_id"], "hold_seconds": 8 if shot["category"] == "exterior" else 12}
                for shot in still_shots
            ],
        }
    ]

    return {
        "still_shots": still_shots,
        "walkthrough_video": {
            "shot_sequence": walkthrough_sequence,
            "duration_target_seconds": 60,
            "fps": 30,
            "min_duration_seconds": 45,
            "max_duration_seconds": 90,
        },
    }
