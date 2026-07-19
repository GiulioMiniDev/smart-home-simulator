from __future__ import annotations

import networkx as nx

from smart_home_sim.domain.models import RoomConfig


class HomeGraph:
    def __init__(self, rooms: list[RoomConfig]) -> None:
        self._graph = nx.Graph()
        for room in rooms:
            self._graph.add_node(room.room_id)
        for room in rooms:
            for connection in room.connections:
                self._graph.add_edge(room.room_id, connection)

    def route(self, origin: str, destination: str) -> list[str]:
        try:
            return list(nx.shortest_path(self._graph, origin, destination))
        except (nx.NodeNotFound, nx.NetworkXNoPath) as error:
            raise ValueError(f"no route from {origin} to {destination}") from error
