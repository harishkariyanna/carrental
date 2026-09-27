from datetime import datetime
from math import ceil
from typing import Any


DEFAULT_VEHICLE_PRICING = {
    "local_base_fare": 500,
    "local_included_km": 5,
    "local_per_km": 18,
    "local_waiting_grace_minutes": 15,
    "local_waiting_rate_per_minute": 5,
    "outstation_one_way_base_fare": 1800,
    "outstation_one_way_per_km": 18,
    "outstation_one_way_included_km_per_day": 150,
    "outstation_one_way_extra_km_rate": 18,
    "outstation_one_way_driver_bata_per_day": 500,
    "outstation_one_way_base_fare_non_ac": 1600,
    "outstation_one_way_extra_km_rate_non_ac": 16,
    "outstation_round_trip_day_rate": 3000,
    "outstation_included_km_per_day": 250,
    "outstation_extra_km_rate": 18,
    "driver_bata_per_day": 500,
    "outstation_round_trip_day_rate_non_ac": 2700,
    "outstation_extra_km_rate_non_ac": 16,
}

CATEGORY_PRICING_DEFAULTS = {
    "Sedan": {"local_base_fare": 350, "local_included_km": 4, "local_per_km": 16, "local_waiting_grace_minutes": 15, "local_waiting_rate_per_minute": 4, "outstation_one_way_base_fare": 1800, "outstation_one_way_per_km": 15, "outstation_one_way_included_km_per_day": 150, "outstation_one_way_extra_km_rate": 15, "outstation_one_way_driver_bata_per_day": 500, "outstation_one_way_base_fare_non_ac": 1600, "outstation_one_way_extra_km_rate_non_ac": 13, "outstation_round_trip_day_rate": 2800, "outstation_included_km_per_day": 250, "outstation_extra_km_rate": 16, "driver_bata_per_day": 500, "outstation_round_trip_day_rate_non_ac": 2500, "outstation_extra_km_rate_non_ac": 14},
    "SUV": {"local_base_fare": 450, "local_included_km": 5, "local_per_km": 18, "local_waiting_grace_minutes": 15, "local_waiting_rate_per_minute": 5, "outstation_one_way_base_fare": 2200, "outstation_one_way_per_km": 17, "outstation_one_way_included_km_per_day": 150, "outstation_one_way_extra_km_rate": 17, "outstation_one_way_driver_bata_per_day": 500, "outstation_one_way_base_fare_non_ac": 1900, "outstation_one_way_extra_km_rate_non_ac": 15, "outstation_round_trip_day_rate": 3300, "outstation_included_km_per_day": 250, "outstation_extra_km_rate": 18, "driver_bata_per_day": 500, "outstation_round_trip_day_rate_non_ac": 3000, "outstation_extra_km_rate_non_ac": 16},
    "7 Seater": {"local_base_fare": 550, "local_included_km": 5, "local_per_km": 20, "local_waiting_grace_minutes": 15, "local_waiting_rate_per_minute": 6, "outstation_one_way_base_fare": 2600, "outstation_one_way_per_km": 19, "outstation_one_way_included_km_per_day": 150, "outstation_one_way_extra_km_rate": 20, "outstation_one_way_driver_bata_per_day": 600, "outstation_one_way_base_fare_non_ac": 2300, "outstation_one_way_extra_km_rate_non_ac": 18, "outstation_round_trip_day_rate": 3800, "outstation_included_km_per_day": 250, "outstation_extra_km_rate": 20, "driver_bata_per_day": 600, "outstation_round_trip_day_rate_non_ac": 3500, "outstation_extra_km_rate_non_ac": 18},
    "Premium": {"local_base_fare": 800, "local_included_km": 5, "local_per_km": 28, "local_waiting_grace_minutes": 20, "local_waiting_rate_per_minute": 8, "outstation_one_way_base_fare": 4000, "outstation_one_way_per_km": 26, "outstation_one_way_included_km_per_day": 150, "outstation_one_way_extra_km_rate": 28, "outstation_one_way_driver_bata_per_day": 800, "outstation_one_way_base_fare_non_ac": 3500, "outstation_one_way_extra_km_rate_non_ac": 23, "outstation_round_trip_day_rate": 6000, "outstation_included_km_per_day": 250, "outstation_extra_km_rate": 28, "driver_bata_per_day": 800, "outstation_round_trip_day_rate_non_ac": 5500, "outstation_extra_km_rate_non_ac": 25},
}


def effective_vehicle_pricing(vehicle: dict[str, Any]) -> dict[str, int]:
    defaults = {**DEFAULT_VEHICLE_PRICING, **CATEGORY_PRICING_DEFAULTS.get(str(vehicle.get("category")), {})}
    return {key: int(vehicle.get(key, default)) for key, default in defaults.items()}


def public_vehicle(vehicle: dict[str, Any], public_document) -> dict[str, Any]:
    return {**(public_document(vehicle) or {}), **effective_vehicle_pricing(vehicle)}


def trip_days(scheduled_at: datetime, return_at: datetime | None) -> int:
    if not return_at:
        return 1
    return max(1, ceil(max(0, (return_at - scheduled_at).total_seconds()) / 86_400))


def calculate_vehicle_quote(
    *,
    service_type: str,
    vehicle: dict[str, Any],
    rule: dict[str, Any],
    distance_km: float | None,
    round_trip: bool,
    scheduled_at: datetime,
    return_at: datetime | None,
    package_hours: int | None,
    ac_required: bool = True,
) -> tuple[int, list[dict[str, Any]], dict[str, Any]]:
    pricing = effective_vehicle_pricing(vehicle)
    line_items: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {"distance_km": round(distance_km, 1) if distance_km is not None else None, "billable_distance_km": None, "trip_days": 1, "ac_required": ac_required, "vehicle_tariff": pricing}

    if service_type == "NORMAL" and distance_km is not None:
        billable_km = max(0, ceil(distance_km - pricing["local_included_km"]))
        distance_charge = billable_km * pricing["local_per_km"]
        line_items = [
            {"code": "LOCAL_BASE", "label": f"Local base fare (includes {pricing['local_included_km']} km)", "amount": pricing["local_base_fare"]},
            {"code": "LOCAL_DISTANCE", "label": f"Distance charge ({billable_km} km × ₹{pricing['local_per_km']})", "amount": distance_charge},
        ]
        metadata["billable_distance_km"] = billable_km
    elif service_type == "OUTSTATION" and distance_km is not None:
        days = trip_days(scheduled_at, return_at if round_trip else None)
        metadata["trip_days"] = days
        estimated_trip_km = distance_km * (2 if round_trip else 1)
        if round_trip:
            metadata["one_way_distance_km"] = round(distance_km, 1)
            metadata["distance_km"] = round(estimated_trip_km, 1)
            included_km = days * pricing["outstation_included_km_per_day"]
            excess_km = max(0, ceil(estimated_trip_km - included_km))
            day_rate = pricing["outstation_round_trip_day_rate"] if ac_required else pricing["outstation_round_trip_day_rate_non_ac"]
            excess_rate = pricing["outstation_extra_km_rate"] if ac_required else pricing["outstation_extra_km_rate_non_ac"]
            line_items = [
                {"code": "OUTSTATION_PACKAGE", "label": f"Round-trip {'AC' if ac_required else 'non-AC'} package ({days} day{'s' if days != 1 else ''} × ₹{day_rate})", "amount": days * day_rate},
                {"code": "OUTSTATION_EXCESS", "label": f"Excess distance ({excess_km} km × ₹{excess_rate})", "amount": excess_km * excess_rate},
            ]
            metadata["billable_distance_km"] = excess_km
            metadata["included_distance_km"] = included_km
        else:
            included_km = pricing["outstation_one_way_included_km_per_day"]
            excess_km = max(0, ceil(distance_km - included_km))
            package_fare = pricing["outstation_one_way_base_fare"] if ac_required else pricing["outstation_one_way_base_fare_non_ac"]
            excess_rate = pricing["outstation_one_way_extra_km_rate"] if ac_required else pricing["outstation_one_way_extra_km_rate_non_ac"]
            line_items = [
                {"code": "OUTSTATION_ONE_WAY", "label": f"One-way {'AC' if ac_required else 'non-AC'} package (includes {included_km} km)", "amount": package_fare},
                {"code": "OUTSTATION_ONE_WAY_EXCESS", "label": f"Excess distance ({excess_km} km × ₹{excess_rate})", "amount": excess_km * excess_rate},
                {"code": "DRIVER_BATA", "label": f"Driver bata (1 day × ₹{pricing['outstation_one_way_driver_bata_per_day']})", "amount": pricing["outstation_one_way_driver_bata_per_day"]},
            ]
            metadata["billable_distance_km"] = excess_km
            metadata["included_distance_km"] = included_km
        if round_trip:
            line_items.append({"code": "DRIVER_BATA", "label": f"Driver bata ({days} day{'s' if days != 1 else ''} × ₹{pricing['driver_bata_per_day']})", "amount": days * pricing["driver_bata_per_day"]})
    else:
        fare = int(rule["base_fare"])
        if service_type == "HOURLY":
            included_hours = int(rule.get("included_hours", 4))
            extra_hours = max(0, (package_hours or included_hours) - included_hours)
            fare += extra_hours * int(rule["extra_hour"])
        if service_type == "OUTSTATION" and round_trip:
            fare = round(fare * float(rule.get("round_trip_multiplier", 2)))
        line_items = [{"code": "BASE_FARE", "label": "Base fare", "amount": fare}]
        allowance = int(rule.get("driver_allowance", 0))
        if allowance:
            line_items.append({"code": "DRIVER_ALLOWANCE", "label": "Driver allowance", "amount": allowance})

    subtotal = sum(int(item["amount"]) for item in line_items)
    tax = round(subtotal * (float(rule.get("tax_percent", 5)) / 100))
    line_items.append({"code": "TAX", "label": "Taxes", "amount": tax})
    return subtotal + tax, line_items, metadata
