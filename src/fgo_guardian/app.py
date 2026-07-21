from __future__ import annotations

import argparse
import tkinter as tk
from tkinter import ttk

from .controller import AutomationController, ControllerSnapshot, RunState, StopReason


class ControlPanel:
    """Small control surface that stays outside the protected LDPlayer window."""

    def __init__(
        self,
        root: tk.Tk,
        controller: AutomationController,
        *,
        simulation: bool,
    ) -> None:
        self.root = root
        self.controller = controller
        self.simulation = simulation
        self.status = tk.StringVar()

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
        try:
            self.controller.start()
        except RuntimeError:
            self.root.bell()

    def _pause_or_resume(self) -> None:
        state = self.controller.snapshot().state
        if state is RunState.PAUSED:
            self.controller.resume()
        else:
            self.controller.pause()

    def _stop(self) -> None:
        self.controller.stop(StopReason.USER_STOP)

    def _emergency_stop(self) -> None:
        self.controller.emergency_stop()

    def _close(self) -> None:
        self.controller.stop(StopReason.USER_STOP)
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
            state=(tk.DISABLED if snapshot.state is RunState.EMERGENCY_STOPPED else tk.NORMAL)
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FateGo local automation controls")
    parser.add_argument(
        "--simulation",
        action="store_true",
        help="run the control surface with visible input disabled",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    root = tk.Tk()
    ControlPanel(root, AutomationController(), simulation=args.simulation)
    root.mainloop()


if __name__ == "__main__":
    main()
