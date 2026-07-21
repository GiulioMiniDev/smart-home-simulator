# ruff: noqa: E501
from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path
from typing import Any

from shapely.geometry import Point, Polygon

from smart_home_sim.domain.environment import HomeModel, SimulationBundle
from smart_home_sim.environment.navigation import plan_path

ROOT = Path(__file__).parents[1]
HOME_PATH = ROOT / "examples/environment/mario_monteverde.home.json"
BUNDLE_PATH = ROOT / "examples/bundles/mario_week.simulation-bundle.json"
REPORT_PATH = ROOT / "examples/bundles/mario_week.environment-report.json"
OUTPUT_PATH = ROOT / "examples/visualizations/mario_monteverde.m4-benchmark.html"

DOMESTIC_REGION_ORDER = (
    "bedroom",
    "bathroom",
    "hallway",
    "entrance",
    "kitchen",
    "living_room",
    "balcony",
)

REGION_LABELS = {
    "bedroom": "Camera",
    "bathroom": "Bagno",
    "hallway": "Corridoio",
    "entrance": "Ingresso",
    "kitchen": "Cucina",
    "living_room": "Soggiorno",
    "balcony": "Balcone",
    "market": "Mercato",
    "mothers_home": "Casa della madre",
    "neighborhood_bar": "Bar di quartiere",
    "outside": "Esterno",
    "pharmacy": "Farmacia",
    "supermarket": "Supermercato",
    "workplace": "Luogo di lavoro",
}

ENTITY_LABELS = {
    "bedroom_storage": "Armadio e abiti",
    "bathroom_fixture": "Gruppo bagno",
    "entrance_access": "Accesso e deposito",
    "kitchen_workstation": "Postazione cucina",
    "living_room_media": "Media e socialità",
    "balcony_utility": "Asciugatura ed esercizio",
}

ENTITY_CODES = {
    "bedroom_storage": "AR",
    "bathroom_fixture": "BG",
    "entrance_access": "IN",
    "kitchen_workstation": "CU",
    "living_room_media": "ME",
    "balcony_utility": "BA",
}

RESOURCE_LABELS = {
    "bed": "Letto",
    "shower": "Doccia",
    "toilet": "WC",
    "washing_machine": "Lavatrice",
    "sink": "Lavandino",
    "refrigerator": "Frigorifero",
    "electric_kettle": "Bollitore",
    "stove": "Piano cottura",
    "television": "Televisore",
}

# Coordinates are acceptance-view metadata, not routing geometry. Exact ID coverage is
# checked below so a resource can neither disappear nor be invented by the renderer.
RESOURCE_PLACEMENTS: dict[str, tuple[float, float, float]] = {
    "bed_01": (2.4, 9.5, 0.0),
    "shower_01": (5.7, 4.9, 0.0),
    "toilet_01": (3.9, 1.2, 0.0),
    "washing_machine_01": (2.4, 1.1, 0.0),
    "kitchen_sink_01": (14.8, 2.6, 0.0),
    "fridge_01": (17.2, 5.0, 0.0),
    "kettle_01": (12.1, 5.0, 0.0),
    "stove_01": (16.2, 3.4, 0.0),
    "television_01": (18.8, 10.9, 0.0),
}

OBSTACLE_LABELS = {
    "bedroom_bed": "Ingombro letto",
    "bathroom_cabinet": "Mobile bagno",
    "kitchen_island": "Isola cucina",
    "living_room_table": "Tavolino",
}

OBSTACLE_SYMBOLS = {
    "bedroom_bed": "bed",
    "bathroom_cabinet": "cabinet",
    "kitchen_island": "island",
    "living_room_table": "table",
}

REGION_LABEL_POSITIONS = {
    "bedroom": (5.35, 6.7),
    "bathroom": (3.5, 5.35),
    "hallway": (9.0, 5.45),
    "entrance": (9.0, 0.55),
    "kitchen": (12.25, 0.55),
    "living_room": (13.4, 6.55),
    "balcony": (21.5, 7.45),
}

ROOM_COLORS = {
    "bedroom": "#ececff",
    "bathroom": "#e4f3f7",
    "hallway": "#f5f5f2",
    "entrance": "#f8f7f3",
    "kitchen": "#fff2df",
    "living_room": "#e5f4ed",
    "balcony": "#dff3eb",
}


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _polygon_vertices(polygon: Any) -> list[dict[str, float]]:
    return [point.model_dump(mode="json") for point in polygon.vertices]


def _centroid(vertices: list[dict[str, float]]) -> dict[str, float]:
    polygon = Polygon([(point["x"], point["y"]) for point in vertices])
    return {"x": polygon.centroid.x, "y": polygon.centroid.y}


def build_visualization_data(
    home_path: Path = HOME_PATH,
    bundle_path: Path = BUNDLE_PATH,
    report_path: Path = REPORT_PATH,
) -> dict[str, Any]:
    home = HomeModel.model_validate_json(home_path.read_text(encoding="utf-8"))
    bundle = SimulationBundle.model_validate_json(bundle_path.read_text(encoding="utf-8"))
    report = _json(report_path)

    if bundle.home_model != home:
        raise ValueError("visualization inputs contain different home models")
    home_digest = next(item.sha256 for item in bundle.digests if item.artifact_id == home.home_id)
    if report.get("homeSha256") != home_digest:
        raise ValueError("environment report and bundle contain different home digests")
    if not report.get("valid") or report.get("issues"):
        raise ValueError("the visualization can only be built from a valid environment report")

    region_by_id = {region.region_id: region for region in home.regions}
    point_by_id = {point.interaction_point_id: point for point in home.interaction_points}
    entity_by_id = {entity.entity_id: entity for entity in home.entities}
    resource_by_id = {resource.resource_id: resource for resource in bundle.scenario.resources}
    bound_resource_ids = {binding.scenario_resource_id for binding in home.resource_bindings}
    obstacle_ids = {obstacle.obstacle_id for obstacle in home.obstacles}

    if set(DOMESTIC_REGION_ORDER) - region_by_id.keys():
        raise ValueError("domestic visualization region is missing from the home model")
    if set(RESOURCE_PLACEMENTS) != bound_resource_ids:
        raise ValueError("resource placements must exactly cover the bound scenario resources")
    if set(OBSTACLE_LABELS) != obstacle_ids:
        raise ValueError("obstacle labels must exactly cover the routing obstacles")

    action_usage = Counter(
        capability.provider_id
        for action in bundle.action_bindings
        for capability in action.capability_bindings
        if capability.provider_type == "entity"
    )
    regions: list[dict[str, Any]] = []
    for region_id in DOMESTIC_REGION_ORDER:
        region = region_by_id[region_id]
        vertices = _polygon_vertices(region.boundary)
        regions.append(
            {
                "id": region_id,
                "label": REGION_LABELS[region_id],
                "kind": region.kind.value,
                "vertices": vertices,
                "centroid": _centroid(vertices),
                "labelPoint": {
                    "x": REGION_LABEL_POSITIONS[region_id][0],
                    "y": REGION_LABEL_POSITIONS[region_id][1],
                },
                "area": round(Polygon([(p["x"], p["y"]) for p in vertices]).area, 2),
                "fill": ROOM_COLORS[region_id],
            }
        )

    obstacles = []
    for obstacle in home.obstacles:
        vertices = _polygon_vertices(obstacle.boundary)
        obstacles.append(
            {
                "id": obstacle.obstacle_id,
                "label": OBSTACLE_LABELS[obstacle.obstacle_id],
                "regionId": obstacle.region_id,
                "regionLabel": REGION_LABELS[obstacle.region_id],
                "vertices": vertices,
                "centroid": _centroid(vertices),
                "symbol": OBSTACLE_SYMBOLS[obstacle.obstacle_id],
                "area": round(Polygon([(p["x"], p["y"]) for p in vertices]).area, 2),
            }
        )

    connections = []
    for connection in home.connections:
        if (
            connection.region_a_id not in DOMESTIC_REGION_ORDER
            or connection.region_b_id not in DOMESTIC_REGION_ORDER
        ):
            continue
        connections.append(
            {
                "id": connection.connection_id,
                "kind": connection.kind.value,
                "regionAId": connection.region_a_id,
                "regionALabel": REGION_LABELS[connection.region_a_id],
                "regionBId": connection.region_b_id,
                "regionBLabel": REGION_LABELS[connection.region_b_id],
                "portalA": connection.portal_a.model_dump(mode="json"),
                "portalB": connection.portal_b.model_dump(mode="json"),
                "width": connection.width_meters,
                "direction": (
                    "bidirezionale"
                    if connection.bidirectional
                    else f"{connection.region_a_id} → {connection.region_b_id}"
                ),
            }
        )

    resources = []
    for binding in home.resource_bindings:
        resource = resource_by_id.get(binding.scenario_resource_id)
        entity = entity_by_id.get(binding.entity_id)
        if resource is None or entity is None:
            raise ValueError("resource binding references an unknown resource or entity")
        x, y, rotation = RESOURCE_PLACEMENTS[resource.resource_id]
        region = region_by_id[entity.region_id]
        polygon = Polygon([(point.x, point.y) for point in region.boundary.vertices])
        if not polygon.covers(Point(x, y)):
            raise ValueError(f"resource placement {resource.resource_id} is outside its region")
        if resource.resource_type not in RESOURCE_LABELS:
            raise ValueError(f"resource type {resource.resource_type} has no visual symbol")
        resources.append(
            {
                "id": resource.resource_id,
                "type": resource.resource_type,
                "label": RESOURCE_LABELS[resource.resource_type],
                "capacity": resource.capacity,
                "locationId": resource.location_id,
                "regionId": entity.region_id,
                "regionLabel": REGION_LABELS[entity.region_id],
                "entityId": entity.entity_id,
                "entityLabel": ENTITY_LABELS[entity.entity_id],
                "x": x,
                "y": y,
                "rotation": rotation,
            }
        )

    domestic_entities = []
    for entity in home.entities:
        if entity.region_id not in DOMESTIC_REGION_ORDER:
            continue
        point = point_by_id.get(entity.interaction_point_id)
        if point is None or point.region_id != entity.region_id:
            raise ValueError(f"entity {entity.entity_id} has an invalid interaction point")
        domestic_entities.append(
            {
                "id": entity.entity_id,
                "label": ENTITY_LABELS[entity.entity_id],
                "code": ENTITY_CODES[entity.entity_id],
                "type": entity.entity_type,
                "regionId": entity.region_id,
                "regionLabel": REGION_LABELS[entity.region_id],
                "interactionPointId": entity.interaction_point_id,
                "x": point.position.x,
                "y": point.position.y,
                "approachRadius": point.approach_radius_meters,
                "capabilities": [capability.capability for capability in entity.capabilities],
                "capabilityCount": len(entity.capabilities),
                "actionUseCount": action_usage[entity.entity_id],
                "initialState": entity.initial_state,
            }
        )

    external_entities = []
    for entity in home.entities:
        if entity.region_id in DOMESTIC_REGION_ORDER:
            continue
        external_entities.append(
            {
                "id": entity.entity_id,
                "label": REGION_LABELS[entity.region_id],
                "regionId": entity.region_id,
                "actionUseCount": action_usage[entity.entity_id],
            }
        )

    kinematics = bundle.resident_kinematics[0]
    anchors = {
        point.region_id: point.position
        for point in home.interaction_points
        if point.region_id in DOMESTIC_REGION_ORDER
    }
    routes: dict[str, Any] = {}
    for start_region_id in DOMESTIC_REGION_ORDER:
        for end_region_id in DOMESTIC_REGION_ORDER:
            path = plan_path(
                home,
                start_region_id=start_region_id,
                start=anchors[start_region_id],
                end_region_id=end_region_id,
                end=anchors[end_region_id],
                walking_speed_meters_per_second=kinematics.walking_speed_meters_per_second,
                body_radius_meters=kinematics.body_radius_meters,
                mobility_profile=kinematics.mobility_profile,
            )
            routes[f"{start_region_id}:{end_region_id}"] = {
                "startId": start_region_id,
                "endId": end_region_id,
                "distance": round(path.distance_meters, 3),
                "duration": round(path.duration_seconds, 3),
                "waypoints": [
                    {"x": waypoint.x, "y": waypoint.y, "regionId": waypoint.region_id}
                    for waypoint in path.waypoints
                ],
            }

    return {
        "contract": {
            "schemaVersion": home.schema_version,
            "validatorVersion": report["validatorVersion"],
            "homeId": home.home_id,
            "homeVersion": home.home_version,
            "homeSha256": home_digest,
            "bundleSha256": report["bundleSha256"],
            "valid": report["valid"],
            "errorCount": report["summary"]["errorCount"],
            "warningCount": report["summary"]["warningCount"],
        },
        "summary": {
            "domesticRegionCount": len(regions),
            "externalRegionCount": len(home.regions) - len(regions),
            "domesticEntityCount": len(domestic_entities),
            "externalEntityCount": len(external_entities),
            "resourceCount": len(resources),
            "obstacleCount": len(obstacles),
            "connectionCount": len(home.connections),
            "localConnectionCount": len(connections),
            "actionBindingCount": report["summary"]["actionBindingCount"],
            "routeCheckCount": report["summary"]["routeCheckCount"],
            "visualizedRouteCount": len(routes),
        },
        "regions": regions,
        "connections": connections,
        "obstacles": obstacles,
        "resources": resources,
        "entities": domestic_entities,
        "externalEntities": external_entities,
        "routes": routes,
    }


def _embedded_json(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return payload.replace("</", "<\\/")


def render_visualization(data: dict[str, Any]) -> str:
    payload = _embedded_json(data)
    digest = html.escape(data["contract"]["homeSha256"])
    return f"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>M4 · Casa Monteverde · Visual acceptance</title>
<style>
:root{{--ink:#18201e;--muted:#69736f;--line:#cfd8d4;--paper:#f6f7f4;--panel:#fff;--green:#16845e;--green-soft:#e9f5ef;--blue:#4058d6;--blue-soft:#eef0ff;--amber:#bd7628;--amber-soft:#fff4df;--cyan:#087d87;--shadow:0 16px 40px rgba(25,38,34,.10);--radius:18px;--ui:"Avenir Next","Segoe UI",sans-serif;--mono:"SFMono-Regular",Consolas,monospace}}
*{{box-sizing:border-box}}
body{{margin:0;background:linear-gradient(180deg,#fbfcfa 0,#f1f4f1 100%);color:var(--ink);font:15px/1.45 var(--ui);min-height:100vh}}
button,select,input{{font:inherit}}
.shell{{max-width:1540px;margin:auto;padding:28px}}
.topbar{{display:flex;align-items:flex-start;justify-content:space-between;gap:28px;margin-bottom:20px}}
.eyebrow{{color:var(--blue);font-weight:800;letter-spacing:.13em;text-transform:uppercase;font-size:12px;margin-bottom:6px}}
h1{{font-size:30px;line-height:1.12;margin:0 0 6px;letter-spacing:-.025em}}
.lede{{color:var(--muted);font-size:16px;margin:0;max-width:800px}}
.validity{{display:flex;align-items:center;gap:12px;border:1px solid #87c8ae;background:var(--green-soft);color:var(--green);padding:11px 16px;border-radius:999px;font-weight:800;white-space:nowrap}}
.validity i{{width:9px;height:9px;border-radius:50%;background:var(--green);box-shadow:0 0 0 5px rgba(22,132,94,.10)}}
.metrics{{display:grid;grid-template-columns:repeat(5,1fr);border:1px solid var(--line);background:rgba(255,255,255,.82);border-radius:var(--radius) var(--radius) 0 0;overflow:hidden}}
.metric{{padding:13px 16px;border-right:1px solid var(--line);min-width:0}}
.metric:last-child{{border:0}}
.metric strong{{font-size:21px;line-height:1.1;font-variant-numeric:tabular-nums;display:block}}
.metric span{{display:block;color:var(--muted);font-size:12px;margin-top:3px}}
.viewer{{border:1px solid var(--line);border-top:0;border-radius:0 0 var(--radius) var(--radius);background:var(--panel);box-shadow:var(--shadow);overflow:hidden}}
.toolbar{{display:flex;align-items:end;gap:14px;padding:14px 18px;border-bottom:1px solid var(--line);background:#f2f4f1}}
.field{{display:grid;gap:5px}}
.field label,.layer-title{{font-size:11px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}}
select{{min-width:190px;border:1px solid #bec9c4;border-radius:9px;background:white;padding:9px 34px 9px 11px;color:var(--ink)}}
.layers{{display:flex;gap:6px;margin-left:auto;flex-wrap:wrap;justify-content:flex-end}}
.layer{{border:1px solid transparent;background:transparent;border-radius:9px;padding:8px 10px;display:flex;align-items:center;gap:7px;cursor:pointer;color:#4b5551}}
.layer:hover{{background:#e8ece9}}
.layer[aria-pressed="true"]{{background:white;border-color:#bcc7c2;color:var(--ink);box-shadow:0 1px 2px rgba(0,0,0,.05)}}
.swatch{{width:10px;height:10px;border-radius:3px;background:currentColor}}
.layer[data-layer="obstacles"]{{color:var(--amber)}}.layer[data-layer="resources"]{{color:var(--cyan)}}.layer[data-layer="entities"]{{color:var(--blue)}}.layer[data-layer="anchors"]{{color:#7e8a85}}.layer[data-layer="route"]{{color:#293dc2}}
.workspace{{display:grid;grid-template-columns:minmax(0,1fr) 340px;min-height:700px}}
.canvas-pane{{min-width:0;background-color:#f3f5f3;background-image:linear-gradient(#dfe5e1 1px,transparent 1px),linear-gradient(90deg,#dfe5e1 1px,transparent 1px);background-size:32px 32px;position:relative;padding:20px;overflow:auto}}
.plan-frame{{min-width:760px;max-width:1050px;margin:0 auto}}
#floorplan{{display:block;width:100%;height:auto;filter:drop-shadow(0 12px 16px rgba(29,48,42,.09))}}
.external-strip{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:11px 12px;background:rgba(255,255,255,.88);border:1px solid var(--line);border-radius:12px;margin-top:14px}}
.external-strip b{{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);margin-right:3px}}
.external{{border:1px solid #cbd5d0;background:white;border-radius:999px;padding:6px 9px;cursor:pointer;color:#46514d;font-size:12px}}
.external:hover,.external:focus-visible{{border-color:var(--blue);outline:0;color:var(--blue)}}
.scale{{position:absolute;left:32px;bottom:24px;display:flex;align-items:center;gap:8px;color:var(--muted);font:12px var(--mono);background:rgba(255,255,255,.86);padding:7px 9px;border-radius:8px}}
.scale-line{{width:76px;border-top:3px solid var(--ink);position:relative}}
.scale-line:before,.scale-line:after{{content:"";position:absolute;top:-6px;height:9px;border-left:3px solid var(--ink)}}.scale-line:before{{left:0}}.scale-line:after{{right:0}}
.inspector{{border-left:1px solid var(--line);padding:22px;display:flex;flex-direction:column;gap:20px;background:#fff}}
.inspector section{{border-bottom:1px solid var(--line);padding-bottom:20px}}
.inspector section:last-child{{border:0;padding-bottom:0}}
.section-label{{font-size:11px;font-weight:800;letter-spacing:.11em;text-transform:uppercase;color:var(--muted);margin:0 0 7px}}
#selectionTitle,#routeTitle{{font-size:21px;line-height:1.15;margin:0 0 6px;letter-spacing:-.02em}}
#selectionMeta,#routeMeta{{color:var(--muted);margin:0}}
.facts{{display:grid;gap:9px;margin-top:14px}}
.fact{{display:flex;justify-content:space-between;gap:14px;font-size:13px}}.fact span{{color:var(--muted)}}.fact b{{text-align:right}}
.chips{{display:flex;gap:6px;flex-wrap:wrap;margin-top:12px}}
.chip{{background:#f0f3f1;border:1px solid #d9e0dc;border-radius:6px;padding:4px 6px;font:10px var(--mono);color:#47504d}}
.contract-row{{display:flex;justify-content:space-between;gap:10px;margin:8px 0}}.contract-row span{{color:var(--muted)}}
.digest{{font:11px/1.45 var(--mono);overflow-wrap:anywhere;color:#596660;background:#f5f7f5;border-radius:8px;padding:9px;margin-top:10px}}
.legend{{display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:12px;color:var(--muted)}}.legend i{{display:inline-block;width:13px;height:13px;margin-right:6px;vertical-align:-2px;border-radius:3px}}
.legend .physical{{background:var(--amber-soft);border:1px solid var(--amber)}}.legend .resource{{background:#fff;border:2px solid var(--cyan)}}.legend .entity{{background:var(--blue);border-radius:50%}}.legend .anchor{{border:1px dashed #7e8a85;border-radius:50%}}
.room{{stroke:#97a49f;stroke-width:1.2;vector-effect:non-scaling-stroke;transition:filter 140ms,opacity 140ms}}
.room-label{{font-weight:800;font-size:14px;letter-spacing:.08em;text-transform:uppercase;text-anchor:middle;fill:#26312e;pointer-events:none}}.room-area{{font:11px var(--mono);text-anchor:middle;fill:#69736f;pointer-events:none}}
.door-opening{{stroke:#fff;stroke-width:10;stroke-linecap:round;vector-effect:non-scaling-stroke}}.door-marker{{stroke:#57645f;stroke-width:1.5;stroke-dasharray:3 2;stroke-linecap:round;vector-effect:non-scaling-stroke}}
.obstacle-shape{{fill:url(#obstacleHatch);stroke:#a96720;stroke-width:1.4;vector-effect:non-scaling-stroke}}
.obstacle-icon{{color:#8c571e;pointer-events:none}}
.resource-hit{{fill:rgba(255,255,255,.94);stroke:#087d87;stroke-width:1.6;vector-effect:non-scaling-stroke}}.resource-icon{{color:#085f68;pointer-events:none}}.resource-name{{font:9px var(--ui);font-weight:800;text-anchor:middle;fill:#074f56;pointer-events:none;opacity:0;transition:opacity 120ms}}.resource-node:hover .resource-name,.resource-node.selected .resource-name,.resource-node:focus-visible .resource-name{{opacity:1}}
.entity-node circle{{fill:var(--blue);stroke:white;stroke-width:2;vector-effect:non-scaling-stroke}}.entity-node text{{fill:white;font:bold 9px var(--mono);text-anchor:middle;dominant-baseline:central;pointer-events:none}}
.anchor-ring{{fill:none;stroke:#77847f;stroke-width:1;stroke-dasharray:3 3;vector-effect:non-scaling-stroke}}.anchor-cross{{stroke:#77847f;stroke-width:1;vector-effect:non-scaling-stroke}}
.selectable{{cursor:pointer;transition:filter 120ms,opacity 120ms,transform 120ms;transform-box:fill-box;transform-origin:center}}.selectable:hover{{filter:brightness(.96) drop-shadow(0 2px 2px rgba(0,0,0,.16))}}.selectable.selected{{filter:drop-shadow(0 0 4px #2639c8)}}.selectable:focus{{outline:none}}.selectable:focus-visible{{filter:drop-shadow(0 0 4px #2639c8)}}
#routePath{{fill:none;stroke:#2639c8;stroke-width:3;stroke-linecap:round;stroke-linejoin:round;vector-effect:non-scaling-stroke;stroke-dasharray:7 6;animation:routeFlow 1.1s linear infinite}}#routeStart{{fill:#16845e;stroke:white;stroke-width:2}}#routeEnd{{fill:#c33e44;stroke:white;stroke-width:2}}
@keyframes routeFlow{{to{{stroke-dashoffset:-13}}}}
.hidden-layer{{display:none}}
.footer-note{{color:var(--muted);font-size:12px;margin:13px 2px 0}}
@media (max-width:1100px){{.metrics{{grid-template-columns:repeat(3,1fr)}}.metric:nth-child(3){{border-right:0}}.metric:nth-child(-n+3){{border-bottom:1px solid var(--line)}}.workspace{{grid-template-columns:1fr}}.inspector{{border-left:0;border-top:1px solid var(--line);display:grid;grid-template-columns:repeat(2,1fr)}}.inspector section{{border-bottom:0;border-right:1px solid var(--line);padding-right:18px}}.inspector section:nth-child(even){{border-right:0}}}}
@media (max-width:720px){{.shell{{padding:14px}}.topbar{{display:grid;gap:12px}}h1{{font-size:26px}}.validity{{justify-self:start}}.metrics{{grid-template-columns:1fr 1fr}}.metric,.metric:nth-child(3){{border-right:1px solid var(--line);border-bottom:1px solid var(--line)}}.metric:nth-child(even){{border-right:0}}.metric:last-child{{grid-column:1/-1;border-bottom:0}}.toolbar{{align-items:stretch;flex-wrap:wrap}}.field{{flex:1 1 140px}}select{{min-width:0;width:100%}}.layers{{width:100%;margin-left:0;justify-content:flex-start}}.workspace{{min-height:0}}.canvas-pane{{padding:10px}}.plan-frame{{min-width:650px}}.inspector{{display:block;padding:18px}}.inspector section{{border-right:0;border-bottom:1px solid var(--line);padding-right:0;margin-bottom:18px}}.scale{{display:none}}}}
@media (prefers-reduced-motion:reduce){{*,*:before,*:after{{animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}}}}
</style>
</head>
<body>
<main class="shell">
  <header class="topbar">
    <div><div class="eyebrow">Milestone 4 · Visual acceptance</div><h1>Casa Monteverde</h1><p class="lede">Il modello eseguibile, reso come strumento spaziale: geometria, risorse, capacità e routing provengono dagli stessi artefatti validati.</p></div>
    <div class="validity"><i></i>CONTRATTO VALIDO · 1.0.0</div>
  </header>
  <section class="metrics" aria-label="Metriche di accettazione">
    <div class="metric"><strong id="metricRegions"></strong><span>ambienti domestici + esterni</span></div>
    <div class="metric"><strong id="metricEntities"></strong><span>entità domestiche + servizi</span></div>
    <div class="metric"><strong id="metricResources"></strong><span>risorse fisiche rappresentate</span></div>
    <div class="metric"><strong id="metricObstacles"></strong><span>ingombri metrici nel routing</span></div>
    <div class="metric"><strong id="metricBindings"></strong><span>binding azioni · route check</span></div>
  </section>
  <section class="viewer">
    <div class="toolbar">
      <div class="field"><label for="routeStartSelect">Partenza</label><select id="routeStartSelect"></select></div>
      <div class="field"><label for="routeEndSelect">Destinazione</label><select id="routeEndSelect"></select></div>
      <div class="layers" aria-label="Layer planimetria">
        <button class="layer" data-layer="obstacles" aria-pressed="true"><i class="swatch"></i>Ingombri</button>
        <button class="layer" data-layer="resources" aria-pressed="true"><i class="swatch"></i>Risorse</button>
        <button class="layer" data-layer="entities" aria-pressed="true"><i class="swatch"></i>Entità</button>
        <button class="layer" data-layer="anchors" aria-pressed="false"><i class="swatch"></i>Anchor</button>
        <button class="layer" data-layer="route" aria-pressed="true"><i class="swatch"></i>Percorso</button>
      </div>
    </div>
    <div class="workspace">
      <div class="canvas-pane">
        <div class="plan-frame">
          <svg id="floorplan" viewBox="0 0 970 570" role="img" aria-labelledby="planTitle planDesc">
            <title id="planTitle">Planimetria interattiva di Casa Monteverde</title>
            <desc id="planDesc">Sette ambienti domestici, quattro ingombri, nove risorse fisiche, sei entità logiche e un percorso selezionabile.</desc>
            <defs>
              <pattern id="obstacleHatch" width="9" height="9" patternUnits="userSpaceOnUse" patternTransform="rotate(35)"><rect width="9" height="9" fill="#fff4df"/><line x1="0" y1="0" x2="0" y2="9" stroke="#e2aa61" stroke-width="2"/></pattern>
              <symbol id="sym-bed" viewBox="-24 -24 48 48"><rect x="-19" y="-15" width="38" height="30" rx="3" fill="#fff" stroke="currentColor" stroke-width="2"/><rect x="-16" y="-12" width="13" height="9" rx="2" fill="#dcefed" stroke="currentColor" stroke-width="1.5"/><rect x="3" y="-12" width="13" height="9" rx="2" fill="#dcefed" stroke="currentColor" stroke-width="1.5"/><path d="M-16 1h32v11h-32z" fill="#cde6e2" stroke="currentColor" stroke-width="1.5"/></symbol>
              <symbol id="sym-shower" viewBox="-24 -24 48 48"><path d="M-12 17V-4c0-8 5-13 12-13 6 0 10 3 12 8" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round"/><path d="M7-8h10v5H7z" fill="#dcefed" stroke="currentColor" stroke-width="1.7"/><path d="M9 2v2m4-2v2m4-2v2M9 9v2m4-2v2m4-2v2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M-17 17h34" stroke="currentColor" stroke-width="2.3" stroke-linecap="round"/></symbol>
              <symbol id="sym-toilet" viewBox="-24 -24 48 48"><rect x="-10" y="-18" width="20" height="13" rx="3" fill="#dcefed" stroke="currentColor" stroke-width="2"/><ellipse cx="0" cy="4" rx="13" ry="10" fill="#fff" stroke="currentColor" stroke-width="2"/><ellipse cx="0" cy="4" rx="7" ry="5" fill="#dcefed" stroke="currentColor" stroke-width="1.5"/><path d="M-8 13l-3 6h22l-3-6" fill="#dcefed" stroke="currentColor" stroke-width="2"/></symbol>
              <symbol id="sym-washing_machine" viewBox="-24 -24 48 48"><rect x="-18" y="-20" width="36" height="40" rx="4" fill="#fff" stroke="currentColor" stroke-width="2"/><circle cx="0" cy="4" r="11" fill="#dcefed" stroke="currentColor" stroke-width="2"/><path d="M-13-13h14" stroke="currentColor" stroke-width="2"/><circle cx="11" cy="-13" r="2" fill="currentColor"/></symbol>
              <symbol id="sym-sink" viewBox="-24 -24 48 48"><rect x="-19" y="-13" width="38" height="27" rx="4" fill="#fff" stroke="currentColor" stroke-width="2"/><ellipse cx="0" cy="2" rx="12" ry="8" fill="#dcefed" stroke="currentColor" stroke-width="1.7"/><path d="M-4-13v-5c0-4 8-4 8 0v7" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/><circle cx="0" cy="2" r="1.8" fill="currentColor"/></symbol>
              <symbol id="sym-refrigerator" viewBox="-24 -24 48 48"><rect x="-14" y="-21" width="28" height="42" rx="3" fill="#fff" stroke="currentColor" stroke-width="2"/><path d="M-14-5h28M8-15v7M8 1v8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><rect x="-10" y="-17" width="12" height="8" rx="2" fill="#dcefed"/></symbol>
              <symbol id="sym-electric_kettle" viewBox="-24 -24 48 48"><path d="M-11-10h19l4 25h-27z" fill="#fff" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M9-5c11 0 12 17 3 20M-6-10v-5h9v5M-15-4l-6 7 8 1" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/><path d="M-8 8h15" stroke="#7bc0bd" stroke-width="2"/></symbol>
              <symbol id="sym-stove" viewBox="-24 -24 48 48"><rect x="-19" y="-18" width="38" height="36" rx="4" fill="#fff" stroke="currentColor" stroke-width="2"/><circle cx="-8" cy="-7" r="5" fill="#dcefed" stroke="currentColor" stroke-width="1.6"/><circle cx="8" cy="-7" r="5" fill="#dcefed" stroke="currentColor" stroke-width="1.6"/><circle cx="-8" cy="8" r="5" fill="#dcefed" stroke="currentColor" stroke-width="1.6"/><circle cx="8" cy="8" r="5" fill="#dcefed" stroke="currentColor" stroke-width="1.6"/></symbol>
              <symbol id="sym-television" viewBox="-24 -24 48 48"><rect x="-21" y="-16" width="42" height="28" rx="3" fill="#dcefed" stroke="currentColor" stroke-width="2"/><path d="M-7 19h14M0 12v7" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/><path d="M-13-8l9 9 9-11 8 8" fill="none" stroke="#7bc0bd" stroke-width="2"/></symbol>
              <symbol id="sym-cabinet" viewBox="-24 -24 48 48"><rect x="-19" y="-17" width="38" height="34" rx="3" fill="#fff4df" stroke="currentColor" stroke-width="2"/><path d="M0-17v34M-19 0h38" stroke="currentColor" stroke-width="1.6"/><circle cx="-4" cy="-8" r="1.6" fill="currentColor"/><circle cx="4" cy="-8" r="1.6" fill="currentColor"/><circle cx="-4" cy="8" r="1.6" fill="currentColor"/><circle cx="4" cy="8" r="1.6" fill="currentColor"/></symbol>
              <symbol id="sym-island" viewBox="-24 -24 48 48"><path d="M-20-13h40v26h-40z" fill="#fff4df" stroke="currentColor" stroke-width="2"/><path d="M-14-6h12v12h-12zM5-6h9M5 0h9M5 6h9" fill="none" stroke="currentColor" stroke-width="1.7"/><circle cx="-8" cy="0" r="2" fill="currentColor"/></symbol>
              <symbol id="sym-table" viewBox="-24 -24 48 48"><circle cx="0" cy="0" r="15" fill="#fff4df" stroke="currentColor" stroke-width="2"/><path d="M-9 12l-4 8M9 12l4 8M-9-12l-4-8M9-12l4-8" stroke="currentColor" stroke-width="2.3" stroke-linecap="round"/></symbol>
            </defs>
            <g id="roomsLayer"></g><g id="connectionsLayer"></g><g id="obstaclesLayer"></g><g id="anchorsLayer" class="hidden-layer"></g><g id="resourcesLayer"></g><g id="entitiesLayer"></g>
            <g id="routeLayer"><path id="routePath"></path><circle id="routeStart" r="5"></circle><circle id="routeEnd" r="5"></circle></g>
          </svg>
          <div id="externalStrip" class="external-strip"><b>Rete esterna</b></div>
        </div>
        <div class="scale"><i class="scale-line"></i>2 m</div>
      </div>
      <aside class="inspector" aria-live="polite">
        <section><p class="section-label">Percorso attivo</p><h2 id="routeTitle"></h2><p id="routeMeta"></p><div class="facts" id="routeFacts"></div></section>
        <section><p class="section-label">Selezione</p><h2 id="selectionTitle">Camera</h2><p id="selectionMeta"></p><div class="facts" id="selectionFacts"></div><div class="chips" id="selectionChips"></div></section>
        <section><p class="section-label">Legenda semantica</p><div class="legend"><div><i class="physical"></i>Ingombro routing</div><div><i class="resource"></i>Risorsa fisica</div><div><i class="entity"></i>Entità logica</div><div><i class="anchor"></i>Approccio</div></div></section>
        <section><p class="section-label">Evidenza M4</p><div class="contract-row"><span>Validazione</span><b>0 errori / 0 warning</b></div><div class="contract-row"><span>Topologia</span><b id="contractTopology"></b></div><div class="contract-row"><span>Visuale</span><b id="contractVisual"></b></div><div class="contract-row"><span>Schema</span><b>1.0.0</b></div><div class="digest">home SHA-256<br>{digest}</div></section>
      </aside>
    </div>
  </section>
  <p class="footer-note">Artefatto di accettazione generato deterministicamente. Le coordinate delle risorse sono metadati visuali; solo regioni, connessioni e ingombri partecipano al routing M4.</p>
</main>
<script id="visualization-data" type="application/json">{payload}</script>
<script>
const DATA=JSON.parse(document.getElementById('visualization-data').textContent);const NS='http://www.w3.org/2000/svg';const SCALE=38,OX=48,OY=510;
const xy=(x,y)=>[OX+x*SCALE,OY-y*SCALE];const node=(name,attrs={{}},text='')=>{{const el=document.createElementNS(NS,name);Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,v));if(text)el.textContent=text;return el}};const polygonPoints=vs=>vs.map(p=>xy(p.x,p.y).join(',')).join(' ');
const byKind={{region:Object.fromEntries(DATA.regions.map(x=>[x.id,x])),connection:Object.fromEntries(DATA.connections.map(x=>[x.id,x])),obstacle:Object.fromEntries(DATA.obstacles.map(x=>[x.id,x])),resource:Object.fromEntries(DATA.resources.map(x=>[x.id,x])),entity:Object.fromEntries(DATA.entities.map(x=>[x.id,x])),external:Object.fromEntries(DATA.externalEntities.map(x=>[x.id,x]))}};
document.getElementById('metricRegions').textContent=`${{DATA.summary.domesticRegionCount}} + ${{DATA.summary.externalRegionCount}}`;document.getElementById('metricEntities').textContent=`${{DATA.summary.domesticEntityCount}} + ${{DATA.summary.externalEntityCount}}`;document.getElementById('metricResources').textContent=DATA.summary.resourceCount;document.getElementById('metricObstacles').textContent=DATA.summary.obstacleCount;document.getElementById('metricBindings').textContent=`${{DATA.summary.actionBindingCount}} · ${{DATA.summary.routeCheckCount}}`;document.getElementById('contractTopology').textContent=`${{DATA.summary.connectionCount}} connessioni`;document.getElementById('contractVisual').textContent=`${{DATA.summary.obstacleCount}} ingombri · ${{DATA.summary.resourceCount}} risorse`;
function selectable(el,kind,id,label){{el.classList.add('selectable');el.dataset.kind=kind;el.dataset.id=id;el.setAttribute('tabindex','0');el.setAttribute('role','button');el.setAttribute('aria-label',label);el.addEventListener('click',()=>select(kind,id));el.addEventListener('keydown',e=>{{if(e.key==='Enter'||e.key===' '){{e.preventDefault();select(kind,id)}}}})}}
const rooms=document.getElementById('roomsLayer');DATA.regions.forEach(r=>{{const g=node('g');const p=node('polygon',{{points:polygonPoints(r.vertices),fill:r.fill,class:'room'}});selectable(p,'region',r.id,`Ambiente ${{r.label}}`);g.append(p);const [cx,cy]=xy(r.labelPoint.x,r.labelPoint.y);g.append(node('text',{{x:cx,y:cy+4,class:'room-label'}},r.label),node('text',{{x:cx,y:cy+20,class:'room-area'}},`${{r.area}} m²`));rooms.append(g)}});
const connections=document.getElementById('connectionsLayer');DATA.connections.forEach(c=>{{const a=xy(c.portalA.x,c.portalA.y),b=xy(c.portalB.x,c.portalB.y),g=node('g');const hit=node('line',{{x1:a[0],y1:a[1],x2:b[0],y2:b[1],class:'door-opening'}});selectable(g,'connection',c.id,`Passaggio ${{c.regionALabel}} ${{c.regionBLabel}}`);g.append(hit,node('line',{{x1:a[0],y1:a[1],x2:b[0],y2:b[1],class:'door-marker'}}));connections.append(g)}});
const obstacles=document.getElementById('obstaclesLayer');DATA.obstacles.forEach(o=>{{const g=node('g');const p=node('polygon',{{points:polygonPoints(o.vertices),class:'obstacle-shape'}});selectable(p,'obstacle',o.id,o.label);g.append(p);const [x,y]=xy(o.centroid.x,o.centroid.y);g.append(node('use',{{href:`#sym-${{o.symbol}}`,x:x-20,y:y-20,width:40,height:40,class:'obstacle-icon'}}));obstacles.append(g)}});
const anchors=document.getElementById('anchorsLayer');DATA.entities.forEach(e=>{{const [x,y]=xy(e.x,e.y),r=e.approachRadius*SCALE;anchors.append(node('circle',{{cx:x,cy:y,r,class:'anchor-ring'}}),node('line',{{x1:x-7,y1:y,x2:x+7,y2:y,class:'anchor-cross'}}),node('line',{{x1:x,y1:y-7,x2:x,y2:y+7,class:'anchor-cross'}}))}});
const resources=document.getElementById('resourcesLayer');DATA.resources.forEach(r=>{{const [x,y]=xy(r.x,r.y);const g=node('g',{{transform:`translate(${{x}} ${{y}}) rotate(${{r.rotation}})`,class:'resource-node'}});const hit=node('circle',{{cx:0,cy:0,r:25,class:'resource-hit'}});selectable(g,'resource',r.id,`${{r.label}} ${{r.id}}`);g.append(hit,node('use',{{href:`#sym-${{r.type}}`,x:-20,y:-20,width:40,height:40,class:'resource-icon'}}),node('text',{{x:0,y:35,class:'resource-name'}},r.label));resources.append(g)}});
const entities=document.getElementById('entitiesLayer');DATA.entities.forEach(e=>{{const [x,y]=xy(e.x,e.y);const g=node('g',{{transform:`translate(${{x}} ${{y}})`,class:'entity-node'}});selectable(g,'entity',e.id,`Entità ${{e.label}}`);g.append(node('circle',{{cx:0,cy:0,r:14}}),node('text',{{x:0,y:1}},e.code));entities.append(g)}});
const ext=document.getElementById('externalStrip');DATA.externalEntities.forEach(e=>{{const b=document.createElement('button');b.className='external';b.textContent=`${{e.label}} · ${{e.actionUseCount}} use`;b.addEventListener('click',()=>select('external',e.id));ext.append(b)}});
const start=document.getElementById('routeStartSelect'),end=document.getElementById('routeEndSelect');DATA.regions.forEach(r=>{{start.add(new Option(r.label,r.id));end.add(new Option(r.label,r.id))}});start.value='bedroom';end.value='balcony';start.addEventListener('change',renderRoute);end.addEventListener('change',renderRoute);
function fact(label,value){{return `<div class="fact"><span>${{label}}</span><b>${{value}}</b></div>`}}function clearSelected(){{document.querySelectorAll('.selectable.selected').forEach(x=>x.classList.remove('selected'))}};
function select(kind,id){{clearSelected();document.querySelectorAll(`.selectable[data-kind="${{kind}}"][data-id="${{id}}"]`).forEach(x=>x.classList.add('selected'));const x=byKind[kind][id],title=document.getElementById('selectionTitle'),meta=document.getElementById('selectionMeta'),facts=document.getElementById('selectionFacts'),chips=document.getElementById('selectionChips');chips.innerHTML='';if(kind==='region'){{title.textContent=x.label;meta.textContent=`${{x.kind}} · ${{x.area}} m²`;facts.innerHTML=fact('ID contratto',x.id)+fact('Entità',DATA.entities.filter(e=>e.regionId===x.id).length)+fact('Risorse',DATA.resources.filter(r=>r.regionId===x.id).length)+fact('Ingombri',DATA.obstacles.filter(o=>o.regionId===x.id).length)}}else if(kind==='connection'){{title.textContent=`${{x.regionALabel}} ↔ ${{x.regionBLabel}}`;meta.textContent=`${{x.kind}} · passaggio locale`;facts.innerHTML=fact('ID contratto',x.id)+fact('Larghezza',`${{x.width}} m`)+fact('Direzione',x.direction)}}else if(kind==='obstacle'){{title.textContent=x.label;meta.textContent=`Ingombro fisico · ${{x.regionLabel}}`;facts.innerHTML=fact('ID contratto',x.id)+fact('Superficie',`${{x.area}} m²`)+fact('Routing','blocca il passaggio')}}else if(kind==='resource'){{title.textContent=x.label;meta.textContent=`Risorsa fisica · ${{x.regionLabel}}`;facts.innerHTML=fact('ID scenario',x.id)+fact('Tipo',x.type)+fact('Capacità',x.capacity)+fact('Binding entità',x.entityLabel)}}else if(kind==='entity'){{title.textContent=x.label;meta.textContent=`Entità logica · ${{x.regionLabel}}`;facts.innerHTML=fact('ID contratto',x.id)+fact('Tipo',x.type)+fact('Capability',x.capabilityCount)+fact('Usi nei binding',x.actionUseCount);x.capabilities.forEach(c=>{{const s=document.createElement('span');s.className='chip';s.textContent=c;chips.append(s)}})}}else{{title.textContent=x.label;meta.textContent='Servizio esterno connesso';facts.innerHTML=fact('ID contratto',x.id)+fact('Regione',x.regionId)+fact('Usi nei binding',x.actionUseCount)}}}}
function renderRoute(){{const r=DATA.routes[`${{start.value}}:${{end.value}}`],pts=r.waypoints.map(p=>xy(p.x,p.y));document.getElementById('routePath').setAttribute('d',pts.map((p,i)=>`${{i?'L':'M'}}${{p[0]}},${{p[1]}}`).join(' '));for(const [id,p] of [['routeStart',pts[0]],['routeEnd',pts[pts.length-1]]]){{document.getElementById(id).setAttribute('cx',p[0]);document.getElementById(id).setAttribute('cy',p[1])}}const a=byKind.region[r.startId],b=byKind.region[r.endId];document.getElementById('routeTitle').textContent=`${{a.label}} → ${{b.label}}`;document.getElementById('routeMeta').textContent=`${{r.distance.toFixed(2).replace('.',',')}} m · ${{r.duration.toFixed(2).replace('.',',')}} s`;document.getElementById('routeFacts').innerHTML=fact('Waypoint',r.waypoints.length)+fact('Velocità','profilo residente')+fact('Collisioni','0')}}
document.querySelectorAll('.layer').forEach(b=>b.addEventListener('click',()=>{{const active=b.getAttribute('aria-pressed')==='true';b.setAttribute('aria-pressed',String(!active));document.getElementById(`${{b.dataset.layer}}Layer`).classList.toggle('hidden-layer',active)}}));renderRoute();select('region','bedroom');
</script>
</body></html>"""


def build_visualization(output_path: Path = OUTPUT_PATH) -> dict[str, Any]:
    data = build_visualization_data()
    output_path.write_text(render_visualization(data), encoding="utf-8")
    return data


if __name__ == "__main__":
    result = build_visualization()
    print(
        "Generated M4 visual acceptance benchmark: "
        f"{result['summary']['resourceCount']} resources, "
        f"{result['summary']['obstacleCount']} obstacles, "
        f"{result['summary']['visualizedRouteCount']} internal routes"
    )
