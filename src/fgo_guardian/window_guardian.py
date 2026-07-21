from __future__ import annotations

import time

from .config import AppConfig
from .models import Baseline, GuardReport
from .win32_api import WindowApi


class WindowGuardian:
    def __init__(
        self, api: WindowApi, config: AppConfig
    ) -> None:
        self.api = api
        self.config = config
        self.target_executable = config.target_executable.resolve()

    def select_unique(self) -> int:
        matches = self.api.find_matching_windows(
            self.target_executable, self.config.target_title
        )
        if len(matches) != 1:
            raise RuntimeError(f"expected exactly one LDPlayer window; found {len(matches)}")
        return matches[0]

    def establish_baseline(
        self, hwnd: int, sample_count: int = 2, delay_seconds: float = 0.25
    ) -> Baseline:
        if sample_count < 2:
            raise ValueError("sample_count must be at least 2")
        if self.select_unique() != hwnd:
            raise RuntimeError("baseline hwnd is not the unique LDPlayer window")
        samples = []
        for index in range(sample_count):
            samples.append(self.api.snapshot(hwnd))
            if index + 1 < sample_count and delay_seconds > 0:
                time.sleep(delay_seconds)
        first = samples[0]
        for sample in samples:
            reasons = []
            if (
                sample.process_path.resolve() != self.target_executable
                or sample.title != self.config.target_title
            ):
                reasons.append("identity_changed")
            if not sample.visible:
                reasons.append("hidden")
            if sample.minimized:
                reasons.append("minimized")
            if not sample.foreground:
                reasons.append("focus_lost")
            if self.api.blockers_above(sample.hwnd, sample.outer_rect):
                reasons.append("overlap")
            if reasons:
                raise RuntimeError(f"unsafe baseline:{','.join(reasons)}")
        if any(
            sample.geometry_signature() != first.geometry_signature()
            for sample in samples[1:]
        ):
            raise RuntimeError("LDPlayer geometry was not stable across baseline samples")
        return Baseline(
            hwnd=first.hwnd,
            pid=first.pid,
            process_path=first.process_path,
            title=first.title,
            geometry_signature=first.geometry_signature(),
            android_resolution=self.config.android_resolution,
            android_dpi=self.config.android_dpi,
            orientation=self.config.orientation,
            logical_outer_rect=first.logical_outer_rect,
            logical_client_rect=first.logical_client_rect,
            windows_dpi=first.windows_dpi,
        )

    def check(self, baseline: Baseline) -> GuardReport:
        try:
            matches = self.api.find_matching_windows(
                self.target_executable, self.config.target_title
            )
        except Exception as error:
            return GuardReport(
                False, (f"target_enumeration_failed:{type(error).__name__}",), None
            )
        if len(matches) != 1 or matches[0] != baseline.hwnd:
            return GuardReport(False, ("target_count_changed",), None)
        try:
            snapshot = self.api.snapshot(baseline.hwnd)
        except Exception as error:
            return GuardReport(False, (f"snapshot_failed:{type(error).__name__}",), None)
        reasons: list[str] = []
        if snapshot.pid != baseline.pid or snapshot.process_path != baseline.process_path:
            reasons.append("identity_changed")
        if snapshot.title != baseline.title:
            reasons.append("title_changed")
        if not snapshot.visible:
            reasons.append("hidden")
        if snapshot.minimized:
            reasons.append("minimized")
        if not snapshot.foreground:
            reasons.append("focus_lost")
        if snapshot.geometry_signature() != baseline.geometry_signature:
            reasons.append("geometry_changed")
        try:
            blockers = self.api.blockers_above(snapshot.hwnd, snapshot.outer_rect)
        except Exception as error:
            return GuardReport(
                False,
                (f"overlap_enumeration_failed:{type(error).__name__}",),
                snapshot,
            )
        if blockers:
            reasons.append("overlap")
        return GuardReport(
            safe=not reasons,
            reasons=tuple(reasons),
            snapshot=snapshot,
            blockers=tuple(hwnd for hwnd, _ in blockers),
        )
