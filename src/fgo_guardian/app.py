from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
from threading import Event, Thread
import tkinter as tk
from tkinter import ttk
from typing import Protocol

from .controller import AutomationController, ControllerSnapshot, RunState, StopReason
from .simulation import StorySimulation


class Lifecycle(Protocol):
    def start(self, cancellation: Event | None = None) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...


class ControlPanel:
    """Small control surface that stays outside the protected LDPlayer window."""

    def __init__(
        self,
        root: tk.Tk,
        controller: AutomationController,
        *,
        simulation: bool,
        lifecycle: Lifecycle | None = None,
    ) -> None:
        self.root = root
        self.controller = controller
        self.simulation = simulation
        self.lifecycle = lifecycle
        self.status = tk.StringVar()
        self._pending_start: str | None = None
        self._start_generation = 0
        self._start_cancellation: Event | None = None
        self._startup_thread: Thread | None = None

        root.title("FateGo Agent Controls")
        root.geometry("440x270+40+40")
        root.minsize(420, 250)
        root.protocol("WM_DELETE_WINDOW", self._close)

        frame = ttk.Frame(root, padding=18)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="FateGo Hybrid Vision Agent", font=("Segoe UI", 15, "bold")).pack(
            anchor=tk.W
        )
        mode = "Simulation (input disabled)" if simulation else "Live Story mode"
        ttk.Label(frame, text=mode).pack(anchor=tk.W, pady=(2, 14))
        ttk.Label(frame, textvariable=self.status, font=("Segoe UI", 11)).pack(
            anchor=tk.W, pady=(0, 18)
        )

        row = ttk.Frame(frame)
        row.pack(fill=tk.X)
        self.start_button = ttk.Button(row, text="Start", command=self._start)
        self.start_button.pack(side=tk.LEFT, padx=(0, 8))
        self.pause_button = ttk.Button(row, text="Pause", command=self._pause_or_resume)
        self.pause_button.pack(side=tk.LEFT, padx=(0, 8))
        self.stop_button = ttk.Button(row, text="Stop", command=self._stop)
        self.stop_button.pack(side=tk.LEFT)

        emergency = tk.Button(
            frame,
            text="EMERGENCY STOP",
            command=self._emergency_stop,
            bg="#b00020",
            fg="white",
            activebackground="#7f0016",
            activeforeground="white",
            font=("Segoe UI", 11, "bold"),
            padx=14,
            pady=8,
        )
        emergency.pack(anchor=tk.W, pady=(20, 0))

        controller.subscribe(self._schedule_render)
        self._render(controller.snapshot())

    def _start(self) -> None:
        if self.lifecycle is None:
            try:
                self.controller.start()
            except RuntimeError:
                self.root.bell()
            return
        self._cancel_start()
        cancellation = Event()
        self._start_cancellation = cancellation
        generation = self._start_generation
        self._pending_start = self.root.after(
            200,
            self._launch_start,
            generation,
            cancellation,
        )

    def _launch_start(self, generation: int, cancellation: Event) -> None:
        self._pending_start = None
        if generation != self._start_generation or cancellation.is_set():
            return
        thread = Thread(
            target=self._run_start,
            args=(generation, cancellation),
            name="fgo-startup",
            daemon=True,
        )
        self._startup_thread = thread
        thread.start()

    def _run_start(self, generation: int, cancellation: Event) -> None:
        if generation != self._start_generation or cancellation.is_set():
            return
        lifecycle = self.lifecycle
        if lifecycle is None:
            return
        try:
            lifecycle.start(cancellation)
        except RuntimeError:
            if not cancellation.is_set():
                try:
                    self.root.after(0, self.root.bell)
                except tk.TclError:
                    pass

    def _cancel_start(self) -> None:
        self._start_generation += 1
        cancellation = self._start_cancellation
        if cancellation is not None:
            cancellation.set()
        self._start_cancellation = None
        pending = self._pending_start
        if pending is not None:
            try:
                self.root.after_cancel(pending)
            except tk.TclError:
                pass
            self._pending_start = None

    def _pause_or_resume(self) -> None:
        state = self.controller.snapshot().state
        if state is RunState.PAUSED:
            if self.lifecycle is None:
                self.controller.resume()
            else:
                self.root.after(200, self.lifecycle.resume)
        else:
            if self.lifecycle is None:
                self.controller.pause()
            else:
                self.lifecycle.pause()

    def _stop(self) -> None:
        self._cancel_start()
        self.controller.stop(StopReason.USER_STOP)
        if self.lifecycle is None:
            return
        else:
            self.lifecycle.stop()

    def _emergency_stop(self) -> None:
        self._cancel_start()
        self.controller.emergency_stop()

    def _close(self) -> None:
        self._cancel_start()
        if self.lifecycle is None:
            self.controller.stop(StopReason.USER_STOP)
        else:
            self.lifecycle.close()
        self.root.destroy()

    def _schedule_render(self, snapshot: ControllerSnapshot) -> None:
        self.root.after(0, self._render, snapshot)

    def _render(self, snapshot: ControllerSnapshot) -> None:
        suffix = f" — {snapshot.reason.value}" if snapshot.reason is not None else ""
        self.status.set(f"State: {snapshot.state.value}{suffix}")
        self.pause_button.configure(
            text="Resume" if snapshot.state is RunState.PAUSED else "Pause"
        )
        self.pause_button.configure(
            state=(tk.NORMAL if snapshot.state in {RunState.RUNNING, RunState.PAUSED} else tk.DISABLED)
        )
        self.start_button.configure(
            state=(
                tk.NORMAL
                if snapshot.state in {RunState.DISARMED, RunState.STOPPED}
                else tk.DISABLED
            )
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FateGo local automation controls")
    parser.add_argument(
        "--simulation",
        nargs="?",
        const="",
        metavar="RECORDING",
        help="disable input; optionally replay a recording headlessly",
    )
    parser.add_argument(
        "--mode",
        choices=("story", "all-quests", "farming"),
        default="story",
        help="quest-selection mode (live wiring is enabled only after the acceptance gate)",
    )
    parser.add_argument(
        "--max-quests",
        type=int,
        help="stop after this many completed quests; live mode repeats until Stop when omitted",
    )
    parser.add_argument("--farming-anchor")
    parser.add_argument(
        "--shadow",
        action="store_true",
        help="observe and log predictions without visible input",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.max_quests is not None and args.max_quests <= 0:
        raise SystemExit("--max-quests must be positive")
    if args.simulation:
        report = StorySimulation.from_recording(Path(args.simulation)).run(
            stop_after_quests=args.max_quests or 1
        )
        print(json.dumps(asdict(report), indent=2, sort_keys=True))
        return
    root = tk.Tk()
    controller = AutomationController()
    lifecycle = None
    if args.simulation is None or args.shadow:
        from .live_runtime import LiveRuntime
        from .quest_planner import QuestMode

        mode = {
            "story": QuestMode.STORY,
            "all-quests": QuestMode.ALL_QUESTS,
            "farming": QuestMode.FARMING,
        }[args.mode]
        if mode is QuestMode.FARMING and not args.farming_anchor:
            raise SystemExit("--farming-anchor is required in farming mode")
        lifecycle = LiveRuntime(
            controller,
            Path(__file__).resolve().parents[2],
            mode=mode,
            maximum_quests=args.max_quests,
            farming_anchor=args.farming_anchor,
            shadow=args.shadow,
        )
    ControlPanel(
        root,
        controller,
        simulation=args.simulation is not None or args.shadow,
        lifecycle=lifecycle,
    )
    root.mainloop()


if __name__ == "__main__":
    main()
