from fgo_guardian.app import ControlPanel, build_parser
from fgo_guardian.controller import AutomationController, RunState


class _QueuedRoot:
    def __init__(self) -> None:
        self.callbacks = {}
        self.sequence = 0

    def after(self, delay, callback, *args):
        del delay
        self.sequence += 1
        identifier = f"after-{self.sequence}"
        self.callbacks[identifier] = lambda: callback(*args)
        return identifier

    def after_cancel(self, identifier) -> None:
        self.callbacks.pop(identifier, None)

    def run_pending(self) -> None:
        callbacks = tuple(self.callbacks.values())
        self.callbacks.clear()
        for callback in callbacks:
            callback()


class _Lifecycle:
    def __init__(self) -> None:
        self.starts = 0
        self.stops = 0

    def start(self, cancellation=None) -> None:
        if cancellation is None or not cancellation.is_set():
            self.starts += 1

    def pause(self) -> None: ...

    def resume(self) -> None: ...

    def stop(self) -> None:
        self.stops += 1

    def close(self) -> None: ...


def test_live_parser_defaults_to_unbounded_quest_count() -> None:
    args = build_parser().parse_args([])

    assert args.max_quests is None


def test_live_parser_accepts_an_explicit_bounded_quest_count() -> None:
    args = build_parser().parse_args(["--max-quests", "3"])

    assert args.max_quests == 3


def test_stop_cancels_a_queued_live_start_before_it_can_rearm() -> None:
    root = _QueuedRoot()
    lifecycle = _Lifecycle()
    controller = AutomationController()
    panel = object.__new__(ControlPanel)
    panel.root = root
    panel.lifecycle = lifecycle
    panel.controller = controller
    panel._pending_start = None
    panel._start_generation = 0
    panel._start_cancellation = None

    panel._start()
    panel._stop()
    root.run_pending()

    assert lifecycle.starts == 0
    assert lifecycle.stops == 1
    assert controller.snapshot().state is RunState.STOPPED
