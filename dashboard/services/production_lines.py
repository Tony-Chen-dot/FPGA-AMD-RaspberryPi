"""Per-line stores and assistants; browser selection never changes acquisition."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from common.production_lines import LINE_IDS, line_data_dir, migrate_legacy_data, validate_line_id
from dashboard.api.websocket_hub import SocketHub
from dashboard.storage.database import DashboardStorage
from voice.config import load_config
from voice.service import AssistantService


class ProductionLines:
    def __init__(self, base: Path, active_line_id: int):
        self.active_line_id = validate_line_id(active_line_id)
        migrate_legacy_data(base, self.active_line_id)
        self.stores = {n: DashboardStorage(line_data_dir(base, n)) for n in LINE_IDS}
        self.hubs = {n: SocketHub() for n in LINE_IDS}
        self.assistants = {}

    def resolve(self, line_id=None) -> int:
        return self.active_line_id if line_id is None else validate_line_id(line_id)

    def store(self, line_id=None) -> DashboardStorage:
        return self.stores[self.resolve(line_id)]

    def assistant(self, line_id=None) -> AssistantService:
        number = self.resolve(line_id)
        if number not in self.assistants:
            config = replace(load_config(), dashboard_db_path=self.store(number).db_path,
                             production_line_id=number)
            self.assistants[number] = AssistantService(config)
        return self.assistants[number]

    def decorate(self, payload: dict, line_id: int) -> dict:
        number = self.resolve(line_id)
        payload.update(line_id=number, line_name=f'产线 {number}', active_line_id=self.active_line_id,
                       camera_assigned=number == self.active_line_id)
        if number != self.active_line_id and 'device' in payload:
            payload['device'].update(online=False, comm_state='no_signal', stream_state='no_signal',
                                     circle_count=0, selected_circle=None, trigger_overlay=None)
        if 'connection_plan' in payload:
            payload['connection_plan'].update(
                board_to_pi='树莓派采集 → Zynq 推理加速 → 上位机汇总',
                pi_to_browser='树莓派多产线上位机 → 浏览器',
            )
        def image_urls(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == 'image_url' and isinstance(child, str) and child.startswith('/api/frame/'):
                        value[key] = child.split('?')[0] + f'?line_id={number}'
                    else:
                        image_urls(child)
            elif isinstance(value, list):
                for child in value:
                    image_urls(child)
        image_urls(payload)
        return payload

    async def snapshot(self, line_id=None) -> dict:
        number = self.resolve(line_id)
        return self.decorate(await self.store(number).get_snapshot(), number)

    async def live_state(self, line_id=None) -> dict:
        number = self.resolve(line_id)
        return self.decorate(await self.store(number).get_live_state(), number)
