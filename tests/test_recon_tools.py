from __future__ import annotations

import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from fgo_guardian.agent_models import Observation, ScreenKind
from fgo_guardian.models import Rect
from fgo_guardian.tools import (
    authorize_action,
    capture_observation,
    common as tools_common,
    complete_action,
    recon_sentinel,
)
from fgo_guardian.tools.common import (
    ensure_not_stopped,
    latch_stop,
    parse_normalized_rect,
    session_state_lock,
)
from fgo_guardian.tools.recon_sentinel import run_monitor


def test_stop_latch_blocks_later_actions_and_cli_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stopped_session = tmp_path / "stopped"
    stopped_session.mkdir()
    (stopped_session / "STOPPED").write_text("emergency_stop", encoding="utf-8")
    with pytest.raises(RuntimeError, match="emergency_stop"):
        ensure_not_stopped(stopped_session)

    cli_cases = (
        (capture_observation, ["capture", "--session", "s", "--screen", "STORY", "--confidence", "0.95"]),
        (authorize_action, ["authorize", "--session", "s", "--action", "WAIT"]),
        (complete_action, ["complete", "--session", "s", "--token", "tok", "--after-observation", "obs"]),
    )
    for module, argv in cli_cases:
        monkeypatch.setattr(module, "session_root", lambda session: stopped_session)
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(RuntimeError, match="emergency_stop"):
            module.main()
        assert capsys.readouterr().out == ""

    paused_session = tmp_path / "paused"
    paused_session.mkdir()
    state_token = "a" * 43
    (paused_session / "VIEWPORT_PAUSED").write_text(
        f"viewport_unobservable:ValueError:{state_token}", encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="viewport_unobservable:ValueError"):
        ensure_not_stopped(paused_session)
    for module, argv in cli_cases:
        monkeypatch.setattr(module, "session_root", lambda session: paused_session)
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(RuntimeError, match="viewport_unobservable:ValueError"):
            module.main()
        assert capsys.readouterr().out == ""

    observable_session = tmp_path / "observable"
    observable_session.mkdir()
    (observable_session / "VIEWPORT_PAUSED").write_text(
        f"viewport_observable:{state_token}", encoding="utf-8"
    )
    ensure_not_stopped(observable_session)

    session = tmp_path / "session"
    session.mkdir()
    monkeypatch.setattr(capture_observation, "session_root", lambda value: session)
    monkeypatch.setattr(capture_observation, "project_root", lambda: tmp_path)
    monkeypatch.setattr(capture_observation.AppConfig, "load", lambda path: object())
    monkeypatch.setattr(capture_observation, "PyWin32WindowApi", lambda: object())
    monkeypatch.setattr(
        capture_observation,
        "WindowGuardian",
        lambda api, config: SimpleNamespace(
            select_unique=lambda: 7,
            establish_baseline=lambda hwnd: "baseline",
        ),
    )
    monkeypatch.setattr(
        capture_observation,
        "SafeCapture",
        lambda guardian, desktop: SimpleNamespace(
            capture=lambda baseline: SimpleNamespace(image=np.zeros((2, 2, 3), dtype=np.uint8))
        ),
    )
    monkeypatch.setattr(capture_observation, "DesktopCapture", lambda: object())
    monkeypatch.setattr(
        capture_observation,
        "ViewportMapper",
        lambda: SimpleNamespace(locate=lambda image: object()),
    )
    monkeypatch.setattr(capture_observation.PrivacyPolicy, "load", lambda path: object())
    monkeypatch.setattr(
        capture_observation,
        "RecordingStore",
        lambda root, privacy: SimpleNamespace(
            record_observation=lambda *args: SimpleNamespace(observation_id="obs-captured")
        ),
    )
    monkeypatch.setattr(capture_observation.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["capture", "--session", "s", "--screen", "STORY", "--confidence", "0.95"],
    )
    capture_observation.main()
    captured = capsys.readouterr()
    assert captured.out == "obs-captured\n" and "starts in 3 seconds" in captured.err

    state = Observation("obs-before", ScreenKind.STORY, 0.99, "a" * 64, Rect(0, 0, 100, 100), (), ())
    monkeypatch.setattr(authorize_action, "session_root", lambda value: session)
    monkeypatch.setattr(authorize_action, "project_root", lambda: tmp_path)
    monkeypatch.setattr(authorize_action, "latest_observation", lambda root: state)
    monkeypatch.setattr(authorize_action.PrivacyPolicy, "load", lambda path: object())

    class AuthorizationStore:
        deny = False

        def __init__(self, root, privacy):
            pass

        def authorize(self, state, proposal, gate):
            if self.deny:
                raise PermissionError("denied")
            return "allowed-token"

    monkeypatch.setattr(authorize_action, "RecordingStore", AuthorizationStore)
    monkeypatch.setattr(sys, "argv", ["authorize", "--session", "s", "--action", "SKIP_STORY"])
    authorize_action.main()
    assert capsys.readouterr().out == "allowed-token\n"
    AuthorizationStore.deny = True
    with pytest.raises(SystemExit) as denied:
        authorize_action.main()
    assert denied.value.code == 2 and capsys.readouterr().out == ""

    completed: list[tuple[str, str]] = []
    monkeypatch.setattr(complete_action, "session_root", lambda value: session)
    monkeypatch.setattr(complete_action, "project_root", lambda: tmp_path)
    monkeypatch.setattr(complete_action.PrivacyPolicy, "load", lambda path: object())
    monkeypatch.setattr(
        complete_action,
        "ReplaySession",
        lambda root: SimpleNamespace(observations=lambda: [{"observation_id": "obs-after"}]),
    )
    monkeypatch.setattr(
        complete_action,
        "RecordingStore",
        lambda root, privacy: SimpleNamespace(complete=lambda token, after: completed.append((token, after))),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["complete", "--session", "s", "--token", "tok", "--after-observation", "other-session-obs"],
    )
    with pytest.raises(SystemExit) as missing:
        complete_action.main()
    assert missing.value.code == 2 and completed == [] and capsys.readouterr().out == ""
    monkeypatch.setattr(
        sys,
        "argv",
        ["complete", "--session", "s", "--token", "tok", "--after-observation", "obs-after"],
    )
    complete_action.main()
    assert completed == [("tok", "obs-after")] and capsys.readouterr().out == "tok\n"

    paused_path = session / "VIEWPORT_PAUSED"

    @contextmanager
    def pause_before_final_check(root):
        paused_path.write_text(
            f"viewport_unobservable:ValueError:{state_token}", encoding="utf-8"
        )
        yield

    capture_mutations: list[str] = []
    monkeypatch.setattr(capture_observation, "session_state_lock", pause_before_final_check, raising=False)
    monkeypatch.setattr(
        capture_observation,
        "RecordingStore",
        lambda root, privacy: SimpleNamespace(
            record_observation=lambda *args: capture_mutations.append("capture")
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["capture", "--session", "s", "--screen", "STORY", "--confidence", "0.95"],
    )
    with pytest.raises(RuntimeError, match="viewport_unobservable:ValueError"):
        capture_observation.main()
    assert capture_mutations == [] and capsys.readouterr().out == ""
    paused_path.unlink(missing_ok=True)

    authorization_mutations: list[str] = []
    AuthorizationStore.deny = False
    monkeypatch.setattr(authorize_action, "session_state_lock", pause_before_final_check, raising=False)
    monkeypatch.setattr(
        AuthorizationStore,
        "authorize",
        lambda self, state, proposal, gate: authorization_mutations.append("authorize") or "token",
    )
    monkeypatch.setattr(sys, "argv", ["authorize", "--session", "s", "--action", "SKIP_STORY"])
    with pytest.raises(RuntimeError, match="viewport_unobservable:ValueError"):
        authorize_action.main()
    assert authorization_mutations == [] and capsys.readouterr().out == ""
    paused_path.unlink(missing_ok=True)

    monkeypatch.setattr(complete_action, "session_state_lock", pause_before_final_check, raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["complete", "--session", "s", "--token", "tok", "--after-observation", "obs-after"],
    )
    with pytest.raises(RuntimeError, match="viewport_unobservable:ValueError"):
        complete_action.main()
    assert completed == [("tok", "obs-after")] and capsys.readouterr().out == ""

    invalid_session = tmp_path / "invalid-state"
    invalid_session.mkdir()
    (invalid_session / "VIEWPORT_PAUSED").write_bytes(b"\xff")
    with pytest.raises(RuntimeError, match="viewport_state_io:UnicodeDecodeError"):
        ensure_not_stopped(invalid_session)
    assert (invalid_session / "STOPPED").read_text(encoding="utf-8") == (
        "viewport_state_io:UnicodeDecodeError"
    )

    unreadable_session = tmp_path / "unreadable-state"
    unreadable_session.mkdir()
    unreadable_state = unreadable_session / "VIEWPORT_PAUSED"
    unreadable_state.write_text(f"viewport_observable:{state_token}", encoding="utf-8")
    original_read_text = Path.read_text

    def fail_state_read(path, *args, **kwargs):
        if path == unreadable_state:
            raise PermissionError("denied")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_state_read)
    with pytest.raises(RuntimeError, match="viewport_state_io:PermissionError"):
        ensure_not_stopped(unreadable_session)
    assert original_read_text(unreadable_session / "STOPPED", encoding="utf-8") == (
        "viewport_state_io:PermissionError"
    )


def test_normalized_rect_parser_and_concurrent_latch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert parse_normalized_rect([0.2, 0.3, 0.4, 0.5]) == (0.2, 0.3, 0.4, 0.5)
    with pytest.raises(ValueError):
        parse_normalized_rect([-0.1, 0.2, 0.5, 0.6])

    stopped = tmp_path / "STOPPED"
    barrier = threading.Barrier(12)
    results: list[tuple[str, bool]] = []
    lock = threading.Lock()

    def writer(reason: str) -> None:
        barrier.wait()
        won = latch_stop(stopped, reason)
        with lock:
            results.append((reason, won))

    threads = [threading.Thread(target=writer, args=(f"reason-{index}",)) for index in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)
    winners = [reason for reason, won in results if won]
    assert len(results) == 12 and len(winners) == 1
    assert stopped.read_text(encoding="utf-8") == winners[0]

    clean_session = tmp_path / "clean-contention"
    holder_entered = threading.Event()
    release_holder = threading.Event()
    contender_entered = threading.Event()
    contention_errors: list[BaseException] = []

    def clean_holder() -> None:
        try:
            with session_state_lock(clean_session):
                holder_entered.set()
                release_holder.wait(timeout=2)
        except BaseException as error:
            contention_errors.append(error)

    def clean_contender() -> None:
        try:
            holder_entered.wait(timeout=2)
            with session_state_lock(clean_session):
                contender_entered.set()
        except BaseException as error:
            contention_errors.append(error)

    holder = threading.Thread(target=clean_holder)
    contender = threading.Thread(target=clean_contender)
    holder.start()
    assert holder_entered.wait(timeout=2)
    contender.start()
    assert not contender_entered.wait(timeout=0.05)
    release_holder.set()
    holder.join(timeout=2)
    contender.join(timeout=2)
    assert contender_entered.is_set() and contention_errors == []
    assert not (clean_session / "STOPPED").exists()

    long_session = tmp_path / "long-contention"
    long_holder_entered = threading.Event()
    long_contender_entered = threading.Event()
    long_order: list[str] = []
    long_holder_saw_stop: list[bool] = []
    long_errors: list[BaseException] = []

    def long_holder() -> None:
        try:
            with session_state_lock(long_session):
                long_holder_entered.set()
                time.sleep(5.25)
                long_holder_saw_stop.append((long_session / "STOPPED").exists())
                long_order.append("holder-mutation")
        except BaseException as error:
            long_errors.append(error)

    def long_contender() -> None:
        try:
            assert long_holder_entered.wait(timeout=2)
            with session_state_lock(long_session):
                long_order.append("contender-mutation")
                long_contender_entered.set()
        except BaseException as error:
            long_errors.append(error)

    holder = threading.Thread(target=long_holder)
    contender = threading.Thread(target=long_contender)
    holder.start()
    assert long_holder_entered.wait(timeout=2)
    contender.start()
    assert not long_contender_entered.wait(timeout=0.05)
    holder.join(timeout=7)
    contender.join(timeout=2)
    long_result = {
        "holder_saw_stop": long_holder_saw_stop,
        "order": long_order,
        "errors": [type(error).__name__ for error in long_errors],
        "stopped": (long_session / "STOPPED").exists(),
    }

    for state_name in ("STOPPED", "VIEWPORT_PAUSED"):
        state_session = tmp_path / f"holder-{state_name.lower()}"
        holder_entered = threading.Event()
        release_holder = threading.Event()
        mutations: list[str] = []
        state_errors: list[str] = []

        def state_holder() -> None:
            with session_state_lock(state_session):
                if state_name == "STOPPED":
                    latch_stop(state_session / state_name, "holder_stop")
                else:
                    (state_session / state_name).write_text(
                        "viewport_unobservable:ValueError:" + "b" * 43,
                        encoding="utf-8",
                    )
                holder_entered.set()
                release_holder.wait(timeout=2)

        def state_contender() -> None:
            holder_entered.wait(timeout=2)
            try:
                with session_state_lock(state_session):
                    ensure_not_stopped(state_session, locked=True)
                    mutations.append("mutated")
            except RuntimeError as error:
                state_errors.append(str(error))

        holder = threading.Thread(target=state_holder)
      Û­:¶‰žËkºwµçaÍ•±˜°¥µ…”¤è(€€€€€€€€€€€Í•±˜¹…±±Ì€¬ô€Ä(€€€€€€€€€€€É•ÑÕÉ¸M¥µÁ±•9…µ•ÍÁ…”¡Í¥¹…ÑÕÉ”ô ‰ÍÑ…‰±”ˆ°¤¤((€€€±…ÍÌ!½Ñ­•äè(€€€€€€€‘•˜}}¥¹¥Ñ}|¡Í•±˜°Ù…±Õ”°…±±‰…¬¤è(€€€€€€€€€€€Í•±˜¹¡•­Ì€ô€À(€€€€€€€€€€€Í•±˜¹ÍÑ½ÁÌ€ô€À((€€€€€€€‘•˜ÍÑ…ÉÐ¡Í•±˜¤è(€€€€€€€€€€€Á…ÍÌ((€€€€€€€‘•˜•¹ÍÕÉ•}ÉÕ¹¹¥¹œ¡Í•±˜¤è(€€€€€€€€€€€Í•±˜¹¡•­Ì€¬ô€Ä((€€€€€€€‘•˜ÍÑ½À¡Í•±˜¤è(€€€€€€€€€€€Í•±˜¹ÍÑ½ÁÌ€¬ô€Ä((€€€½¹™¥œ€ôM¥µÁ±•9…µ•ÍÁ…” (€€€€€€€•µ•É•¹å}¡½Ñ­•äô‰ÑÉ°­Í¡¥™Ð­˜ÄÈˆ°(€€€€€€€…ÁÑÕÉ•}¥¹Ñ•ÉÙ…±}µÌôÈÔÀ°(€€€€€€€ÍÑ…ÉÑÕÁ}Ù¥•ÝÁ½ÉÑ}½¹™¥Éµ…Ñ¥½¹ÌôÄ°(€€€€¤(€€€Õ…É‘¥…¸°…ÁÑÕÉ”°µ…ÁÁ•È°•Ù•¹Ð€ôÕ…É‘¥…¸ ¤°…ÁÑÕÉ” ¤°5…ÁÁ•È ¤°MÉ¥ÁÑ•‘Ù•¹Ð¡m…±Í”°…±Í”°QÉÕ•t¤(€€€¡½Ñ­•ä€ôÉÕ¹}µ½¹¥Ñ½È¡½¹™¥œ°Õ…É‘¥…¸°…ÁÑÕÉ”°µ…ÁÁ•È°ÑµÁ}Á…Ñ €¼€‰MQ=AAˆ°!½Ñ­•ä°•Ù•¹Ð¤(€€€…ÍÍ•ÉÐ…ÁÑÕÉ”¹…±±Ì€ôô€Ì…¹µ…ÁÁ•È¹…±±Ì€ôô€Ì…¹Õ…É‘¥…¸¹¡•­Ì€ôô€È(€€€…ÍÍ•ÉÐ¡½Ñ­•ä¹¡•­Ì€ôô€È…¹¡½Ñ­•ä¹ÍÑ½ÁÌ€ôô€Ä…¹¹½Ð€¡ÑµÁ}Á…Ñ €¼€‰MQ=AAˆ¤¹•á¥ÍÑÌ ¤(€€€…ÍÍ•ÉÐ€¡ÑµÁ}Á…Ñ €¼€‰Y%]A=IQ}AUMˆ¤¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤¹ÍÑ…ÉÑÍÝ¥Ñ  (€€€€€€€€‰Ù¥•ÝÁ½ÉÑ}½‰Í•ÉÙ…‰±”èˆ(€€€€¤((€€€±…ÍÌ•…‘!½Ñ­•ä¡!½Ñ­•ä¤è(€€€€€€€‘•˜•¹ÍÕÉ•}ÉÕ¹¹¥¹œ¡Í•±˜¤è(€€€€€€€€€€€É…¥Í”IÕ¹Ñ¥µ•ÉÉ½È ‰‘•…ˆ¤((€€€ÍÑ½ÁÁ•€ôÑµÁ}Á…Ñ €¼€‰ÉÕ¹Ñ¥µ”ˆ€¼€‰MQ=AAˆ(€€€ÍÑ½ÁÁ•¹Á…É•¹Ð¹µ­‘¥È ¤(€€€Ý¥Ñ ÁåÑ•ÍÐ¹É…¥Í•Ì¡IÕ¹Ñ¥µ•ÉÉ½È°µ…Ñ ô‰‘•…ˆ¤è(€€€€€€€ÉÕ¹}µ½¹¥Ñ½È¡½¹™¥œ°Õ…É‘¥…¸ ¤°…ÁÑÕÉ” ¤°5…ÁÁ•È ¤°ÍÑ½ÁÁ•°•…‘!½Ñ­•ä°MÉ¥ÁÑ•‘Ù•¹Ð¡m…±Í•t¤¤(€€€…ÍÍ•ÉÐÍÑ½ÁÁ•¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤€ôô€‰¡½Ñ­•å}µ½¹¥Ñ½ÈéIÕ¹Ñ¥µ•ÉÉ½Èˆ((€€€±…ÍÌ	…‘…ÁÑÕÉ”¡…ÁÑÕÉ”¤è(€€€€€€€‘•˜…ÁÑÕÉ”¡Í•±˜°‰…Í•±¥¹”¤è(€€€€€€€€€€€Í•±˜¹…±±Ì€¬ô€Ä(€€€€€€€€€€€¥˜Í•±˜¹…±±Ì€ø€Äè(€€€€€€€€€€€€€€€É…¥Í”IÕ¹Ñ¥µ•ÉÉ½È ‰…ÁÑÕÉ”ˆ¤(€€€€€€€€€€€É•ÑÕÉ¸M¥µÁ±•9…µ•ÍÁ…”¡¥µ…”õ¹À¹é•É½Ì  È°€È°€Ì¤°‘ÑåÁ”õ¹À¹Õ¥¹Ðà¤¤((€€€ÍÑ½ÁÁ•€ôÑµÁ}Á…Ñ €¼€‰…ÁÑÕÉ”ˆ€¼€‰MQ=AAˆ(€€€ÍÑ½ÁÁ•¹Á…É•¹Ð¹µ­‘¥È ¤(€€€Ý¥Ñ ÁåÑ•ÍÐ¹É…¥Í•Ì¡IÕ¹Ñ¥µ•ÉÉ½È°µ…Ñ ô‰…ÁÑÕÉ”ˆ¤è(€€€€€€€ÉÕ¹}µ½¹¥Ñ½È¡½¹™¥œ°Õ…É‘¥…¸ ¤°	…‘…ÁÑÕÉ” ¤°5…ÁÁ•È ¤°ÍÑ½ÁÁ•°!½Ñ­•ä°MÉ¥ÁÑ•‘Ù•¹Ð¡m…±Í•t¤¤(€€€…ÍÍ•ÉÐÍÑ½ÁÁ•¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤€ôô€‰Ù¥•ÝÁ½ÉÑ}µ½¹¥Ñ½ÈéIÕ¹Ñ¥µ•ÉÉ½Èˆ((€€€±…ÍÌI•½Ù•É¥¹5…ÁÁ•È¡5…ÁÁ•È¤è(€€€€€€€Á…ÕÍ•‘}ÍÑ…Ñ”€ô9½¹”(€€€€€€€Á…ÕÍ•‘}¥‘•¹Ñ¥Ñä€ô9½¹”((€€€€€€€‘•˜±½…Ñ”¡Í•±˜°¥µ…”¤è(€€€€€€€€€€€Í•±˜¹…±±Ì€¬ô€Ä(€€€€€€€€€€€¥˜Í•±˜¹…±±Ì€ôô€Èè(€€€€€€€€€€€€€€€É…¥Í”Y…±Õ•ÉÉ½È ‰µ…ÁÁ¥¹œˆ¤(€€€€€€€€€€€¥˜Í•±˜¹…±±Ì€ôô€Ìè(€€€€€€€€€€€€€€€ÍÑ…Ñ•}Á…Ñ €ôÑµÁ}Á…Ñ €¼€‰µ…ÁÁ¥¹œˆ€¼€‰Y%]A=IQ}AUMˆ(€€€€€€€€€€€€€€€Í•±˜¹Á…ÕÍ•‘}ÍÑ…Ñ”€ôÍÑ…Ñ•}Á…Ñ ¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤(€€€€€€€€€€€€€€€Í•±˜¹Á…ÕÍ•‘}¥‘•¹Ñ¥Ñä€ôÍÑ…Ñ•}Á…Ñ ¹ÍÑ…Ð ¤¹ÍÑ}¥¹¼(€€€€€€€€€€€É•ÑÕÉ¸M¥µÁ±•9…µ•ÍÁ…”¡Í¥¹…ÑÕÉ”ô ‰ÍÑ…‰±”ˆ°¤¤((€€€ÍÑ½ÁÁ•€ôÑµÁ}Á…Ñ €¼€‰µ…ÁÁ¥¹œˆ€¼€‰MQ=AAˆ(€€€ÍÑ½ÁÁ•¹Á…É•¹Ð¹µ­‘¥È ¤(€€€É•½Ù•É¥¹}Õ…É‘¥…¸°É•½Ù•É¥¹}µ…ÁÁ•È€ôÕ…É‘¥…¸ ¤°I•½Ù•É¥¹5…ÁÁ•È ¤(€€€É•½Ù•É¥¹}¡½Ñ­•ä€ôÉÕ¹}µ½¹¥Ñ½È (€€€€€€€½¹™¥œ°(€€€€€€€É•½Ù•É¥¹}Õ…É‘¥…¸°(€€€€€€€…ÁÑÕÉ” ¤°(€€€€€€€É•½Ù•É¥¹}µ…ÁÁ•È°(€€€€€€€ÍÑ½ÁÁ•°(€€€€€€€!½Ñ­•ä°(€€€€€€€MÉ¥ÁÑ•‘Ù•¹Ð¡m…±Í”°…±Í”°QÉÕ•t¤°(€€€€¤(€€€…ÍÍ•ÉÐÉ•½Ù•É¥¹}Õ…É‘¥…¸¹¡•­Ì€ôô€È…¹É•½Ù•É¥¹}¡½Ñ­•ä¹¡•­Ì€ôô€È(€€€É•½Ù•É•‘}ÍÑ…Ñ”€ô€¡ÍÑ½ÁÁ•¹Á…É•¹Ð€¼€‰Y%]A=IQ}AUMˆ¤¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤(€€€…ÍÍ•ÉÐÉ•½Ù•É¥¹}µ…ÁÁ•È¹Á…ÕÍ•‘}ÍÑ…Ñ”¹ÍÑ…ÉÑÍÝ¥Ñ  ‰Ù¥•ÝÁ½ÉÑ}Õ¹½‰Í•ÉÙ…‰±”éY…±Õ•ÉÉ½Èèˆ¤(€€€…ÍÍ•ÉÐÉ•½Ù•É•‘}ÍÑ…Ñ”€ôô€‰Ù¥•ÝÁ½ÉÑ}½‰Í•ÉÙ…‰±”èˆ€¬É•½Ù•É¥¹}µ…ÁÁ•È¹Á…ÕÍ•‘}ÍÑ…Ñ”¹ÉÍÁ±¥Ð ˆèˆ°€Ä¥lÅt(€€€…ÍÍ•ÉÐ€¡ÍÑ½ÁÁ•¹Á…É•¹Ð€¼€‰Y%]A=IQ}AUMˆ¤¹ÍÑ…Ð ¤¹ÍÑ}¥¹¼€ôôÉ•½Ù•É¥¹}µ…ÁÁ•È¹Á…ÕÍ•‘}¥‘•¹Ñ¥Ñä(€€€…ÍÍ•ÉÐ¹½ÐÍÑ½ÁÁ•¹•á¥ÍÑÌ ¤((€€€±…ÍÌA•ÉÍ¥ÍÑ•¹Ñ±åU¹½‰Í•ÉÙ…‰±•5…ÁÁ•È¡5…ÁÁ•È¤è(€€€€€€€‘•˜±½…Ñ”¡Í•±˜°¥µ…”¤è(€€€€€€€€€€€Í•±˜¹…±±Ì€¬ô€Ä(€€€€€€€€€€€¥˜Í•±˜¹…±±Ì€ø€Äè(€€€€€€€€€€€€€€€É…¥Í”Y…±Õ•ÉÉ½È ‰µ…ÁÁ¥¹œˆ¤(€€€€€€€€€€€É•ÑÕÉ¸M¥µÁ±•9…µ•ÍÁ…”¡Í¥¹…ÑÕÉ”ô ‰ÍÑ…‰±”ˆ°¤¤((€€€ÍÑ½ÁÁ•€ôÑµÁ}Á…Ñ €¼€‰Á•ÉÍ¥ÍÑ•¹Ðµµ…ÁÁ¥¹œˆ€¼€‰MQ=AAˆ(€€€ÍÑ½ÁÁ•¹Á…É•¹Ð¹µ­‘¥È ¤(€€€Á•ÉÍ¥ÍÑ•¹Ñ}Õ…É‘¥…¸€ôÕ…É‘¥…¸ ¤(€€€Á•ÉÍ¥ÍÑ•¹Ñ}¡½Ñ­•ä€ôÉÕ¹}µ½¹¥Ñ½È (€€€€€€€½¹™¥œ°(€€€€€€€Á•ÉÍ¥ÍÑ•¹Ñ}Õ…É‘¥…¸°(€€€€€€€…ÁÑÕÉ” ¤°(€€€€€€€A•ÉÍ¥ÍÑ•¹Ñ±åU¹½‰Í•ÉÙ…‰±•5…ÁÁ•È ¤°(€€€€€€€ÍÑ½ÁÁ•°(€€€€€€€!½Ñ­•ä°(€€€€€€€MÉ¥ÁÑ•‘Ù•¹Ð¡m…±Í”°…±Í”°QÉÕ•t¤°(€€€€¤(€€€Á…ÕÍ•€ôÍÑ½ÁÁ•¹Á…É•¹Ð€¼€‰Y%]A=IQ}AUMˆ(€€€…ÍÍ•ÉÐÁ•ÉÍ¥ÍÑ•¹Ñ}Õ…É‘¥…¸¹¡•­Ì€ôô€È…¹Á•ÉÍ¥ÍÑ•¹Ñ}¡½Ñ­•ä¹¡•­Ì€ôô€È(€€€…ÍÍ•ÉÐÁ…ÕÍ•¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤¹ÍÑ…ÉÑÍÝ¥Ñ  ‰Ù¥•ÝÁ½ÉÑ}Õ¹½‰Í•ÉÙ…‰±”éY…±Õ•ÉÉ½Èèˆ¤(€€€…ÍÍ•ÉÐ¹½ÐÍÑ½ÁÁ•¹•á¥ÍÑÌ ¤((€€€½¹Ñ•¹‘•‘}Í•ÍÍ¥½¸€ôÑµÁ}Á…Ñ €¼€‰½¹Ñ•¹‘•µµ…ÁÁ¥¹œˆ(€€€½¹Ñ•¹‘•‘}Í•ÍÍ¥½¸¹µ­‘¥È ¤(€€€½¹Ñ•¹Ñ¥½¹}¡½±‘•É}•¹Ñ•É•€ôÑ¡É•…‘¥¹œ¹Ù•¹Ð ¤(€€€½¹Ñ•¹Ñ¥½¹}¡½±‘•É}•ÉÉ½ÉÌè±¥ÍÑm	…Í•á•ÁÑ¥½¹t€ômt(€€€½¹Ñ•¹Ñ¥½¹}¡½±‘•É}Ñ¡É•…‘Ìè±¥ÍÑmÑ¡É•…‘¥¹œ¹Q¡É•…‘t€ômt((€€€‘•˜¡½±‘}ÍÑ…Ñ•}±½¬ ¤€´ø9½¹”è(€€€€€€€ÑÉäè(€€€€€€€€€€€Ý¥Ñ Í•ÍÍ¥½¹}ÍÑ…Ñ•}±½¬¡½¹Ñ•¹‘•‘}Í•ÍÍ¥½¸¤è(€€€€€€€€€€€€€€€½¹Ñ•¹Ñ¥½¹}¡½±‘•É}•¹Ñ•É•¹Í•Ð ¤(€€€€€€€€€€€€€€€Ñ¥µ”¹Í±••À À¸Ä¤(€€€€€€€•á•ÁÐ	…Í•á•ÁÑ¥½¸…Ì•ÉÉ½Èè(€€€€€€€€€€€½¹Ñ•¹Ñ¥½¹}¡½±‘•É}•ÉÉ½ÉÌ¹…ÁÁ•¹¡•ÉÉ½È¤((€€€±…ÍÌ½¹Ñ•¹‘•‘U¹½‰Í•ÉÙ…‰±•5…ÁÁ•È¡5…ÁÁ•È¤è(€€€€€€€‘•˜±½…Ñ”¡Í•±˜°¥µ…”¤è(€€€€€€€€€€€Í•±˜¹…±±Ì€¬ô€Ä(€€€€€€€€€€€¥˜Í•±˜¹…±±Ì€ø€Äè(€€€€€€€€€€€€€€€¡½±‘•È€ôÑ¡É•…‘¥¹œ¹Q¡É•…¡Ñ…É•Ðõ¡½±‘}ÍÑ…Ñ•}±½¬¤(€€€€€€€€€€€€€€€½¹Ñ•¹Ñ¥½¹}¡½±‘•É}Ñ¡É•…‘Ì¹…ÁÁ•¹¡¡½±‘•È¤(€€€€€€€€€€€€€€€¡½±‘•È¹ÍÑ…ÉÐ ¤(€€€€€€€€€€€€€€€…ÍÍ•ÉÐ½¹Ñ•¹Ñ¥½¹}¡½±‘•É}•¹Ñ•É•¹Ý…¥Ð¡Ñ¥µ•½ÕÐôÈ¤(€€€€€€€€€€€€€€€É…¥Í”Y…±Õ•ÉÉ½È ‰µ…ÁÁ¥¹œˆ¤(€€€€€€€€€€€É•ÑÕÉ¸M¥µÁ±•9…µ•ÍÁ…”¡Í¥¹…ÑÕÉ”ô ‰ÍÑ…‰±”ˆ°¤¤((€€€ÍÑ½ÁÁ•€ô½¹Ñ•¹‘•‘}Í•ÍÍ¥½¸€¼€‰MQ=AAˆ(€€€ÉÕ¹}µ½¹¥Ñ½È (€€€€€€€½¹™¥œ°(€€€€€€€Õ…É‘¥…¸ ¤°(€€€€€€€…ÁÑÕÉ” ¤°(€€€€€€€½¹Ñ•¹‘•‘U¹½‰Í•ÉÙ…‰±•5…ÁÁ•È ¤°(€€€€€€€ÍÑ½ÁÁ•°(€€€€€€€!½Ñ­•ä°(€€€€€€€MÉ¥ÁÑ•‘Ù•¹Ð¡m…±Í”°QÉÕ•t¤°(€€€€¤(€€€™½È¡½±‘•È¥¸½¹Ñ•¹Ñ¥½¹}¡½±‘•É}Ñ¡É•…‘Ìè(€€€€€€€¡½±‘•È¹©½¥¸¡Ñ¥µ•½ÕÐôÈ¤(€€€…ÍÍ•ÉÐ½¹Ñ•¹Ñ¥½¹}¡½±‘•É}•ÉÉ½ÉÌ€ôômt…¹¹½ÐÍÑ½ÁÁ•¹•á¥ÍÑÌ ¤(€€€…ÍÍ•ÉÐ€¡½¹Ñ•¹‘•‘}Í•ÍÍ¥½¸€¼€‰Y%]A=IQ}AUMˆ¤¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤¹ÍÑ…ÉÑÍÝ¥Ñ  (€€€€€€€€‰Ù¥•ÝÁ½ÉÑ}Õ¹½‰Í•ÉÙ…‰±”éY…±Õ•ÉÉ½Èèˆ(€€€€¤((€€€‘•˜ÉÕ¹}Í¥¹…ÑÕÉ•}Í•ÅÕ•¹”¡¹…µ”°½ÕÑ½µ•Ì°Õ…É‘¥…¸õ9½¹”¤è(€€€€€€€Í•ÍÍ¥½¸€ôÑµÁ}Á…Ñ €¼¹…µ”(€€€€€€€Í•ÍÍ¥½¸¹µ­‘¥È ¤(€€€€€€€ÍÑ…Ñ•}Á…Ñ €ôÍ•ÍÍ¥½¸€¼€‰Y%]A=IQ}AUMˆ((€€€€€€€±…ÍÌM•ÅÕ•¹•5…ÁÁ•È¡5…ÁÁ•È¤è(€€€€€€€€€€€‘•˜}}¥¹¥Ñ}|¡Í•±˜¤è(€€€€€€€€€€€€€€€Í•±˜¹…±±Ì€ô€À(€€€€€€€€€€€€€€€Í•±˜¹ÍÑ…Ñ•Í}‰•™½É•}µ½¹¥Ñ½É}µ…ÁÁ¥¹œ€ômt((€€€€€€€€€€€‘•˜±½…Ñ”¡Í•±˜°¥µ…”¤è(€€€€€€€€€€€€€€€Í•±˜¹…±±Ì€¬ô€Ä(€€€€€€€€€€€€€€€¥˜Í•±˜¹…±±Ì€ôô€Äè(€€€€€€€€€€€€€€€€€€€É•ÑÕÉ¸M¥µÁ±•9…µ•ÍÁ…”¡Í¥¹…ÑÕÉ”ô ‰ÍÑ…‰±”ˆ°¤¤(€€€€€€€€€€€€€€€Í•±˜¹ÍÑ…Ñ•Í}‰•™½É•}µ½¹¥Ñ½É}µ…ÁÁ¥¹œ¹…ÁÁ•¹¡ÍÑ…Ñ•}Á…Ñ ¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤¤(€€€€€€€€€€€€€€€½ÕÑ½µ”€ô½ÕÑ½µ•ÍmÍ•±˜¹…±±Ì€´€Ét(€€€€€€€€€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡½ÕÑ½µ”°	…Í•á•ÁÑ¥½¸¤è(€€€€€€€€€€€€€€€€€€€É…¥Í”½ÕÑ½µ”(€€€€€€€€€€€€€€€É•ÑÕÉ¸M¥µÁ±•9…µ•ÍÁ…”¡Í¥¹…ÑÕÉ”õ½ÕÑ½µ”¤((€€€€€€€Í•ÅÕ•¹•}Õ…É‘¥…¸€ôÕ…É‘¥…¸ ¤¥˜Õ…É‘¥…¸¥Ì9½¹”•±Í”Õ…É‘¥…¸(€€€€€€€Í•ÅÕ•¹•}…ÁÑÕÉ”€ô…ÁÑÕÉ” ¤(€€€€€€€Í•ÅÕ•¹•}µ…ÁÁ•È€ôM•ÅÕ•¹•5…ÁÁ•È ¤(€€€€€€€ÍÑ½ÁÁ•‘}Á…Ñ €ôÍ•ÍÍ¥½¸€¼€‰MQ=AAˆ(€€€€€€€¡½Ñ­•ä€ôÉÕ¹}µ½¹¥Ñ½È (€€€€€€€€€€€½¹™¥œ°(€€€€€€€€€€€Í•ÅÕ•¹•}Õ…É‘¥…¸°(€€€€€€€€€€€Í•ÅÕ•¹•}…ÁÑÕÉ”°(€€€€€€€€€€€Í•ÅÕ•¹•}µ…ÁÁ•È°(€€€€€€€€€€€ÍÑ½ÁÁ•‘}Á…Ñ °(€€€€€€€€€€€!½Ñ­•ä°(€€€€€€€€€€€MÉ¥ÁÑ•‘Ù•¹Ð¡m…±Í•t€¨±•¸¡½ÕÑ½µ•Ì¤€¬mQÉÕ•t¤°(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸€ (€€€€€€€€€€€ÍÑ½ÁÁ•‘}Á…Ñ °(€€€€€€€€€€€ÍÑ…Ñ•}Á…Ñ °(€€€€€€€€€€€Í•ÅÕ•¹•}Õ…É‘¥…¸°(€€€€€€€€€€€Í•ÅÕ•¹•}…ÁÑÕÉ”°(€€€€€€€€€€€Í•ÅÕ•¹•}µ…ÁÁ•È°(€€€€€€€€€€€¡½Ñ­•ä°(€€€€€€€€¤((€€€ÍÑ½ÁÁ•°ÍÑ…Ñ”°Õ…É‘¥…¸°…ÁÑÕÉ”°µ…ÁÁ•È°¡½Ñ­•ä€ôÉÕ¹}Í¥¹…ÑÕÉ•}Í•ÅÕ•¹” (€€€€€€€€‰½¹”µµ¥Íµ…Ñ µÉ•½Ù•Éäˆ°l ‰¡…¹•µ½¹”ˆ°¤°€ ‰ÍÑ…‰±”ˆ°¥t(€€€€¤(€€€…ÍÍ•ÉÐ¹½ÐÍÑ½ÁÁ•¹•á¥ÍÑÌ ¤…¹ÍÑ…Ñ”¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤¹ÍÑ…ÉÑÍÝ¥Ñ  (€€€€€€€€‰Ù¥•ÝÁ½ÉÑ}½‰Í•ÉÙ…‰±”èˆ(€€€€¤(€€€…ÍÍ•ÉÐµ…ÁÁ•È¹ÍÑ…Ñ•Í}‰•™½É•}µ½¹¥Ñ½É}µ…ÁÁ¥¹lÅt¹ÍÑ…ÉÑÍÝ¥Ñ  (€€€€€€€€‰Ù¥•ÝÁ½ÉÑ}Õ¹½‰Í•ÉÙ…‰±”éM¥¹…ÑÕÉ•¡…¹•èˆ(€€€€¤(€€€…ÍÍ•ÉÐÕ…É‘¥…¸¹¡•­Ì€ôô…ÁÑÕÉ”¹…±±Ì€´€Ä€ôô¡½Ñ­•ä¹¡•­Ì€ôô€È((€€€ÍÑ½ÁÁ•°ÍÑ…Ñ”°Õ…É‘¥…¸°…ÁÑÕÉ”°µ…ÁÁ•È°¡½Ñ­•ä€ôÉÕ¹}Í¥¹…ÑÕÉ•}Í•ÅÕ•¹” (€€€€€€€€‰ÑÝ¼µµ¥Íµ…Ñ µÉ•½Ù•Éäˆ°(€€€€€€€l ‰¡…¹•µ½¹”ˆ°¤°€ ‰¡…¹•µÑÝ¼ˆ°¤°€ ‰ÍÑ…‰±”ˆ°¥t°(€€€€¤(€€€…ÍÍ•ÉÐ¹½ÐÍÑ½ÁÁ•¹•á¥ÍÑÌ ¤…¹ÍÑ…Ñ”¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤¹ÍÑ…ÉÑÍÝ¥Ñ  (€€€€€€€€‰Ù¥•ÝÁ½ÉÑ}½‰Í•ÉÙ…‰±”èˆ(€€€€¤(€€€…ÍÍ•ÉÐ…±° (€€€€€€€¥Ñ•´¹ÍÑ…ÉÑÍÝ¥Ñ  ‰Ù¥•ÝÁ½ÉÑ}Õ¹½‰Í•ÉÙ…‰±”éM¥¹…ÑÕÉ•¡…¹•èˆ¤(€€€€€€€™½È¥Ñ•´¥¸µ…ÁÁ•È¹ÍÑ…Ñ•Í}‰•™½É•}µ½¹¥Ñ½É}µ…ÁÁ¥¹lÄét(€€€€¤(€€€…ÍÍ•ÉÐÕ…É‘¥…¸¹¡•­Ì€ôô…ÁÑÕÉ”¹…±±Ì€´€Ä€ôô¡½Ñ­•ä¹¡•­Ì€ôô€Ì((€€€ÍÑ½ÁÁ•°ÍÑ…Ñ”°Õ…É‘¥…¸°…ÁÑÕÉ”°µ…ÁÁ•È°¡½Ñ­•ä€ôÉÕ¹}Í¥¹…ÑÕÉ•}Í•ÅÕ•¹” (€€€€€€€€‰Ù…É¥•µµ¥Íµ…Ñ µÉ•½Ù•Éäˆ°(€€€€€€€l ‰¡…¹•µ½¹”ˆ°¤°€ ‰¡…¹•µÑÝ¼ˆ°¤°€ ‰¡…¹•µÑ¡É•”ˆ°¤°€ ‰ÍÑ…‰±”ˆ°¥t°(€€€€¤(€€€…ÍÍ•ÉÐ¹½ÐÍÑ½ÁÁ•¹•á¥ÍÑÌ ¤…¹ÍÑ…Ñ”¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤¹ÍÑ…ÉÑÍÝ¥Ñ  (€€€€€€€€‰Ù¥•ÝÁ½ÉÑ}½‰Í•ÉÙ…‰±”èˆ(€€€€¤(€€€…ÍÍ•ÉÐÕ…É‘¥…¸¹¡•­Ì€ôô…ÁÑÕÉ”¹…±±Ì€´€Ä€ôô¡½Ñ­•ä¹¡•­Ì€ôô€Ð((€€€ÍÑ½ÁÁ•°ÍÑ…Ñ”°Õ…É‘¥…¸°…ÁÑÕÉ”°µ…ÁÁ•È°¡½Ñ­•ä€ôÉÕ¹}Í¥¹…ÑÕÉ•}Í•ÅÕ•¹” (€€€€€€€€‰Ñ¡É•”µ¥‘•¹Ñ¥…°µµ¥Íµ…Ñ µÍÑ½Àˆ°(€€€€€€€l ‰¡…¹•ˆ°¤°€ ‰¡…¹•ˆ°¤°€ ‰¡…¹•ˆ°¥t°(€€€€¤(€€€…ÍÍ•ÉÐÍÑ½ÁÁ•¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤€ôô€‰Ù¥•ÝÁ½ÉÑ}Í¥¹…ÑÕÉ•}¡…¹•ˆ(€€€…ÍÍ•ÉÐÍÑ…Ñ”¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤¹ÍÑ…ÉÑÍÝ¥Ñ  (€€€€€€€€‰Ù¥•ÝÁ½ÉÑ}Õ¹½‰Í•ÉÙ…‰±”éM¥¹…ÑÕÉ•¡…¹•èˆ(€€€€¤(€€€…ÍÍ•ÉÐÕ…É‘¥…¸¹¡•­Ì€ôô…ÁÑÕÉ”¹…±±Ì€´€Ä€ôô¡½Ñ­•ä¹¡•­Ì€ôô€Ì((€€€ÍÑ½ÁÁ•°ÍÑ…Ñ”°Õ…É‘¥…¸°…ÁÑÕÉ”°µ…ÁÁ•È°¡½Ñ­•ä€ôÉÕ¹}Í¥¹…ÑÕÉ•}Í•ÅÕ•¹” (€€€€€€€€‰Õ¹½‰Í•ÉÙ…‰±”µÉ•Í•ÑÌµµ¥Íµ…Ñ ˆ°(€€€€€€€l(€€€€€€€€€€€€ ‰¡…¹•µ½¹”ˆ°¤°(€€€€€€€€€€€Y…±Õ•ÉÉ½È ‰µ…ÁÁ¥¹œˆ¤°(€€€€€€€€€€€€ ‰¡…¹•µÑÝ¼ˆ°¤°(€€€€€€€€€€€€ ‰¡…¹•µÑ¡É•”ˆ°¤°(€€€€€€€€€€€€ ‰ÍÑ…‰±”ˆ°¤°(€€€€€€€t°(€€€€¤(€€€…ÍÍ•ÉÐ¹½ÐÍÑ½ÁÁ•¹•á¥ÍÑÌ ¤…¹ÍÑ…Ñ”¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤¹ÍÑ…ÉÑÍÝ¥Ñ  (€€€€€€€€‰Ù¥•ÝÁ½ÉÑ}½‰Í•ÉÙ…‰±”èˆ(€€€€¤(€€€…ÍÍ•ÉÐµ…ÁÁ•È¹ÍÑ…Ñ•Í}‰•™½É•}µ½¹¥Ñ½É}µ…ÁÁ¥¹lÉt¹ÍÑ…ÉÑÍÝ¥Ñ  (€€€€€€€€‰Ù¥•ÝÁ½ÉÑ}Õ¹½‰Í•ÉÙ…‰±”éY…±Õ•ÉÉ½Èèˆ(€€€€¤(€€€…ÍÍ•ÉÐÕ…É‘¥…¸¹¡•­Ì€ôô…ÁÑÕÉ”¹…±±Ì€´€Ä€ôô¡½Ñ­•ä¹¡•­Ì€ôô€Ô((€€€±…ÍÌ…¹‘¥‘…Ñ•…Õ±ÑÕ…É‘¥…¸¡Õ…É‘¥…¸¤è(€€€€€€€‘•˜¡•¬¡Í•±˜°‰…Í•±¥¹”¤è(€€€€€€€€€€€Í•±˜¹¡•­Ì€¬ô€Ä(€€€€€€€€€€€É…¥Í”=MÉÉ½È ‰…¹‘¥‘…Ñ”µÕ…É‘¥…¸ˆ¤((€€€…¹‘¥‘…Ñ•}Õ…É‘¥…¸€ô…¹‘¥‘…Ñ•…Õ±ÑÕ…É‘¥…¸ ¤(€€€ÍÑ½ÁÁ•°ÍÑ…Ñ”°Õ…É‘¥…¸°…ÁÑÕÉ”°µ…ÁÁ•È°¡½Ñ­•ä€ôÉÕ¹}Í¥¹…ÑÕÉ•}Í•ÅÕ•¹” (€€€€€€€€‰…¹‘¥‘…Ñ”µÕ…É‘¥…¸µ™…Õ±Ðˆ°l ‰¡…¹•µ½¹”ˆ°¥t°…¹‘¥‘…Ñ•}Õ…É‘¥…¸(€€€€¤(€€€…ÍÍ•ÉÐÍÑ½ÁÁ•¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤€ôô€‰Õ…É‘¥…¹}¡•¬é=MÉÉ½Èˆ(€€€…ÍÍ•ÉÐÍÑ…Ñ”¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤¹ÍÑ…ÉÑÍÝ¥Ñ  ‰Ù¥•ÝÁ½ÉÑ}½‰Í•ÉÙ…‰±”èˆ¤(€€€…ÍÍ•ÉÐÕ…É‘¥…¸¹¡•­Ì€ôô…ÁÑÕÉ”¹…±±Ì€´€Ä€ôô¡½Ñ­•ä¹¡•­Ì€ôô€Ä((€€€‘¥…¹½ÍÑ¥Ì€ô…ÁÍåÌ¹É•…‘½ÕÑ•ÉÈ ¤¹•ÉÈ(€€€…ÍÍ•ÉÐ€‰•áÁ•Ñ•ô ÍÑ…‰±”œ°¤ÕÉÉ•¹Ðô ¡…¹•µ½¹”œ°¤ˆ¥¸‘¥…¹½ÍÑ¥Ì(€€€…ÍÍ•ÉÐ€‰•áÁ•Ñ•ô ÍÑ…‰±”œ°¤ÕÉÉ•¹Ðô ¡…¹•µÑ¡É•”œ°¤ˆ¥¸‘¥…¹½ÍÑ¥Ì(€€€…ÍÍ•ÉÐ€‰Õ¥¹Ðàˆ¹½Ð¥¸‘¥…¹½ÍÑ¥Ì…¹€‰mmlˆ¹½Ð¥¸‘¥…¹½ÍÑ¥Ì((€€€É•Á±…•‘}Á…ÕÍ”€ôÑµÁ}Á…Ñ €¼€‰É•Á±…•µÉ•½Ù•Éäˆ€¼€‰Y%]A=IQ}AUMˆ(€€€É•Á±…•µ•¹Ñ}½Ý¹•ÉÌ€ômt((€€€‘•˜É•Á±…•µ•¹Ñ}½Ý¹•É}™…Ñ½Éä¡Á…Ñ ¤è(€€€€€€€½Ý¹•È€ôÉ•½¹}Í•¹Ñ¥¹•°¹Y¥•ÝÁ½ÉÑMÑ…Ñ•=Ý¹•È¡Á…Ñ ¤(€€€€€€€É•Á±…•µ•¹Ñ}½Ý¹•ÉÌ¹…ÁÁ•¹¡½Ý¹•È¤(€€€€€€€É•ÑÕÉ¸½Ý¹•È((€€€±…ÍÌI•Á±…•‘I•½Ù•Éå5…ÁÁ•È¡5…ÁÁ•È¤è(€€€€€€€‘•˜±½…Ñ”¡Í•±˜°¥µ…”¤è(€€€€€€€€€€€Í•±˜¹…±±Ì€¬ô€Ä(€€€€€€€€€€€¥˜Í•±˜¹…±±Ì€ôô€Èè(€€€€€€€€€€€€€€€É…¥Í”Y…±Õ•ÉÉ½È ‰µ…ÁÁ¥¹œˆ¤(€€€€€€€€€€€¥˜Í•±˜¹…±±Ì€ø€Èè(€€€€€€€€€€€€€€€•ÅÕ…±}½¹Ñ•¹Ð€ôÉ•Á±…•‘}Á…ÕÍ”¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤(€€€€€€€€€€€€€€€É•Á±…•µ•¹Ñ}½Ý¹•ÉÍlÁt¹±½Í” ¤(€€€€€€€€€€€€€€€É•Á±…•‘}Á…ÕÍ”¹Õ¹±¥¹¬ ¤(€€€€€€€€€€€€€€€É•Á±…•‘}Á…ÕÍ”¹ÝÉ¥Ñ•}Ñ•áÐ¡•ÅÕ…±}½¹Ñ•¹Ð°•¹½‘¥¹œô‰ÕÑ˜´àˆ¤(€€€€€€€€€€€É•ÑÕÉ¸M¥µÁ±•9…µ•ÍÁ…”¡Í¥¹…ÑÕÉ”ô ‰ÍÑ…‰±”ˆ°¤¤((€€€ÍÑ½ÁÁ•€ôÉ•Á±…•‘}Á…ÕÍ”¹Á…É•¹Ð€¼€‰MQ=AAˆ(€€€ÍÑ½ÁÁ•¹Á…É•¹Ð¹µ­‘¥È ¤(€€€ÉÕ¹}µ½¹¥Ñ½È (€€€€€€€½¹™¥œ°(€€€€€€€Õ…É‘¥…¸ ¤°(€€€€€€€…ÁÑÕÉ” ¤°(€€€€€€€I•Á±…•‘I•½Ù•Éå5…ÁÁ•È ¤°(€€€€€€€ÍÑ½ÁÁ•°(€€€€€€€!½Ñ­•ä°(€€€€€€€MÉ¥ÁÑ•‘Ù•¹Ð¡m…±Í”°…±Í•t¤°(€€€€€€€ÍÑ…Ñ•}½Ý¹•É}™…Ñ½ÉäõÉ•Á±…•µ•¹Ñ}½Ý¹•É}™…Ñ½Éä°(€€€€¤(€€€…ÍÍ•ÉÐÍÑ½ÁÁ•¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤€ôô€‰Ù¥•ÝÁ½ÉÑ}ÍÑ…Ñ•}½Ý¹•ÉÍ¡¥Á}±½ÍÐˆ(€€€…ÍÍ•ÉÐÉ•Á±…•‘}Á…ÕÍ”¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤¹ÍÑ…ÉÑÍÝ¥Ñ  (€€€€€€€€‰Ù¥•ÝÁ½ÉÑ}Õ¹½‰Í•ÉÙ…‰±”éY…±Õ•ÉÉ½Èèˆ(€€€€¤((€€€µ…±™½Éµ•‘}Á…ÕÍ”€ôÑµÁ}Á…Ñ €¼€‰µ…±™½Éµ•µÉ•½Ù•Éäˆ€¼€‰Y%]A=IQ}AUMˆ(€€€µ…±™½Éµ•‘}½Ý¹•ÉÌ€ômt((€€€‘•˜µ…±™½Éµ•‘}½Ý¹•É}™…Ñ½Éä¡Á…Ñ ¤è(€€€€€€€½Ý¹•È€ôÉ•½¹}Í•¹Ñ¥¹•°¹Y¥•ÝÁ½ÉÑMÑ…Ñ•=Ý¹•È¡Á…Ñ ¤(€€€€€€€µ…±™½Éµ•‘}½Ý¹•ÉÌ¹…ÁÁ•¹¡½Ý¹•È¤(€€€€€€€É•ÑÕÉ¸½Ý¹•È((€€€±…ÍÌ5…±™½Éµ•‘I•½Ù•Éå5…ÁÁ•È¡5…ÁÁ•È¤è(€€€€€€€‘•˜±½…Ñ”¡Í•±˜°¥µ…”¤è(€€€€€€€€€€€Í•±˜¹…±±Ì€¬ô€Ä(€€€€€€€€€€€¥˜Í•±˜¹…±±Ì€ôô€Èè(€€€€€€€€€€€€€€€É…¥Í”Y…±Õ•ÉÉ½È ‰µ…ÁÁ¥¹œˆ¤(€€€€€€€€€€€¥˜Í•±˜¹…±±Ì€ø€Èè(€€€€€€€€€€€€€€€µ…±™½Éµ•‘}½Ý¹•ÉÍlÁt¹±½Í” ¤(€€€€€€€€€€€€€€€µ…±™½Éµ•‘}Á…ÕÍ”¹Õ¹±¥¹¬ ¤(€€€€€€€€€€€€€€€µ…±™½Éµ•‘}Á…ÕÍ”¹ÝÉ¥Ñ•}Ñ•áÐ ‰•áÑ•É¹…°µÁ…ÕÍ”ˆ°•¹½‘¥¹œô‰ÕÑ˜´àˆ¤(€€€€€€€€€€€É•ÑÕÉ¸M¥µÁ±•9…µ•ÍÁ…”¡Í¥¹…ÑÕÉ”ô ‰ÍÑ…‰±”ˆ°¤¤((€€€ÍÑ½ÁÁ•€ôµ…±™½Éµ•‘}Á…ÕÍ”¹Á…É•¹Ð€¼€‰MQ=AAˆ(€€€ÍÑ½ÁÁ•¹Á…É•¹Ð¹µ­‘¥È ¤(€€€ÉÕ¹}µ½¹¥Ñ½È (€€€€€€€½¹™¥œ°(€€€€€€€Õ…É‘¥…¸ ¤°(€€€€€€€…ÁÑÕÉ” ¤°(€€€€€€€5…±™½Éµ•‘I•½Ù•Éå5…ÁÁ•È ¤°(€€€€€€€ÍÑ½ÁÁ•°(€€€€€€€!½Ñ­•ä°(€€€€€€€MÉ¥ÁÑ•‘Ù•¹Ð¡m…±Í”°…±Í•t¤°(€€€€€€€ÍÑ…Ñ•}½Ý¹•É}™…Ñ½Éäõµ…±™½Éµ•‘}½Ý¹•É}™…Ñ½Éä°(€€€€¤(€€€…ÍÍ•ÉÐÍÑ½ÁÁ•¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤€ôô€‰Ù¥•ÝÁ½ÉÑ}ÍÑ…Ñ•}½Ý¹•ÉÍ¡¥Á}±½ÍÐˆ(€€€…ÍÍ•ÉÐµ…±™½Éµ•‘}Á…ÕÍ”¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤€ôô€‰•áÑ•É¹…°µÁ…ÕÍ”ˆ((€€€±…ÍÌA•Éµ¥ÍÍ¥½¹=Ý¹•È¡É•½¹}Í•¹Ñ¥¹•°¹Y¥•ÝÁ½ÉÑMÑ…Ñ•=Ý¹•È¤è(€€€€€€€‘•˜Á…ÕÍ”¡Í•±˜°•á•ÁÑ¥½¹}ÑåÁ”¤è(€€€€€€€€€€€É…¥Í”A•Éµ¥ÍÍ¥½¹ÉÉ½È ‰‘•¹¥•ˆ¤((€€€ÍÑ½ÁÁ•€ôÑµÁ}Á…Ñ €¼€‰Á…ÕÍ”µÁ•Éµ¥ÍÍ¥½¸ˆ€¼€‰MQ=AAˆ(€€€ÍÑ½ÁÁ•¹Á…É•¹Ð¹µ­‘¥È ¤(€€€Ý¥Ñ ÁåÑ•ÍÐ¹É…¥Í•Ì¡A•Éµ¥ÍÍ¥½¹ÉÉ½È°µ…Ñ ô‰‘•¹¥•ˆ¤è(€€€€€€€ÉÕ¹}µ½¹¥Ñ½È (€€€€€€€€€€€½¹™¥œ°(€€€€€€€€€€€Õ…É‘¥…¸ ¤°(€€€€€€€€€€€…ÁÑÕÉ” ¤°(€€€€€€€€€€€A•ÉÍ¥ÍÑ•¹Ñ±åU¹½‰Í•ÉÙ…‰±•5…ÁÁ•È ¤°(€€€€€€€€€€€ÍÑ½ÁÁ•°(€€€€€€€€€€€!½Ñ­•ä°(€€€€€€€€€€€MÉ¥ÁÑ•‘Ù•¹Ð¡m…±Í•t¤°(€€€€€€€€€€€ÍÑ…Ñ•}½Ý¹•É}™…Ñ½ÉäõA•Éµ¥ÍÍ¥½¹=Ý¹•È°(€€€€€€€€¤(€€€…ÍÍ•ÉÐÍÑ½ÁÁ•¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤€ôô€‰Ù¥•ÝÁ½ÉÑ}ÍÑ…Ñ•}¥¼éA•Éµ¥ÍÍ¥½¹ÉÉ½Èˆ((€€€±…ÍÌ¥¹…±±½Í•A•Éµ¥ÍÍ¥½¹=Ý¹•È¡É•½¹}Í•¹Ñ¥¹•°¹Y¥•ÝÁ½ÉÑMÑ…Ñ•=Ý¹•È¤è(€€€€€€€‘•˜±½Í”¡Í•±˜¤è(€€€€€€€€€€€ÍÕÁ•È ¤¹±½Í” ¤(€€€€€€€€€€€É…¥Í”A•Éµ¥ÍÍ¥½¹ÉÉ½È ‰™¥¹…°µ±½Í”ˆ¤((€€€ÍÑ½ÁÁ•€ôÑµÁ}Á…Ñ €¼€‰½Ý¹•Èµ±½Í”µÁ•Éµ¥ÍÍ¥½¸ˆ€¼€‰MQ=AAˆ(€€€ÍÑ½ÁÁ•¹Á…É•¹Ð¹µ­‘¥È ¤(€€€Ý¥Ñ ÁåÑ•ÍÐ¹É…¥Í•Ì¡A•Éµ¥ÍÍ¥½¹ÉÉ½È°µ…Ñ ô‰™¥¹…°µ±½Í”ˆ¤è(€€€€€€€ÉÕ¹}µ½¹¥Ñ½È (€€€€€€€€€€€½¹™¥œ°(€€€€€€€€€€€Õ…É‘¥…¸ ¤°(€€€€€€€€€€€…ÁÑÕÉ” ¤°(€€€€€€€€€€€5…ÁÁ•È ¤°(€€€€€€€€€€€ÍÑ½ÁÁ•°(€€€€€€€€€€€!½Ñ­•ä°(€€€€€€€€€€€MÉ¥ÁÑ•‘Ù•¹Ð¡mQÉÕ•t¤°(€€€€€€€€€€€ÍÑ…Ñ•}½Ý¹•É}™…Ñ½Éäõ¥¹…±±½Í•A•Éµ¥ÍÍ¥½¹=Ý¹•È°(€€€€€€€€¤(€€€…ÍÍ•ÉÐÍÑ½ÁÁ•¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤€ôô€‰Ù¥•ÝÁ½ÉÑ}ÍÑ…Ñ•}¥¼éA•Éµ¥ÍÍ¥½¹ÉÉ½Èˆ((€€€±…ÍÌ	…‘Õ…É‘¥…¸¡Õ…É‘¥…¸¤è(€€€€€€€‘•˜¡•¬¡Í•±˜°‰…Í•±¥¹”¤è(€€€€€€€€€€€É…¥Í”=MÉÉ½È ‰Õ…É‘¥…¸ˆ¤((€€€ÍÑ½ÁÁ•€ôÑµÁ}Á…Ñ €¼€‰Õ…É‘¥…¸ˆ€¼€‰MQ=AAˆ(€€€ÍÑ½ÁÁ•¹Á…É•¹Ð¹µ­‘¥È ¤(€€€ÉÕ¹}µ½¹¥Ñ½È¡½¹™¥œ°	…‘Õ…É‘¥…¸ ¤°…ÁÑÕÉ” ¤°5…ÁÁ•È ¤°ÍÑ½ÁÁ•°!½Ñ­•ä°MÉ¥ÁÑ•‘Ù•¹Ð¡m…±Í•t¤¤(€€€…ÍÍ•ÉÐÍÑ½ÁÁ•¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤€ôô€‰Õ…É‘¥…¹}¡•¬é=MÉÉ½Èˆ((€€€±…ÍÌ	…‘M¡ÕÑ‘½Ý¹!½Ñ­•ä¡!½Ñ­•ä¤è(€€€€€€€‘•˜ÍÑ½À¡Í•±˜¤è(€€€€€€€€€€€É…¥Í”IÕ¹Ñ¥µ•ÉÉ½È ‰Í¡ÕÑ‘½Ý¸ˆ¤((€€€ÍÑ½ÁÁ•€ôÑµÁ}Á…Ñ €¼€‰Í¡ÕÑ‘½Ý¸ˆ€¼€‰MQ=AAˆ(€€€ÍÑ½ÁÁ•¹Á…É•¹Ð¹µ­‘¥È ¤(€€€Ý¥Ñ ÁåÑ•ÍÐ¹É…¥Í•Ì¡IÕ¹Ñ¥µ•ÉÉ½È°µ…Ñ ô‰Í¡ÕÑ‘½Ý¸ˆ¤è(€€€€€€€ÉÕ¹}µ½¹¥Ñ½È¡½¹™¥œ°Õ…É‘¥…¸ ¤°…ÁÑÕÉ” ¤°5…ÁÁ•È ¤°ÍÑ½ÁÁ•°	…‘M¡ÕÑ‘½Ý¹!½Ñ­•ä°MÉ¥ÁÑ•‘Ù•¹Ð¡mQÉÕ•t¤¤(€€€…ÍÍ•ÉÐÍÑ½ÁÁ•¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤€ôô€‰¡½Ñ­•å}Í¡ÕÑ‘½Ý¸éIÕ¹Ñ¥µ•ÉÉ½Èˆ(