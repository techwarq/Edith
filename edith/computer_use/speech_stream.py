"""Streaming (partial-transcript) speech sources for voice_loop.py.

edith/voice.py only does batch record-then-transcribe via Whisper — fine for
a normal turn-based conversation, useless for the tick-by-tick "act on the
sentence before it's finished" design voice_loop.py implements. That design
needs a source that keeps emitting a growing transcript *while the user is
still talking*.

MicPartialTranscriptSource gets that from macOS's own on-device continuous
speech recognition: Speech.framework (SFSpeechRecognizer +
SFSpeechAudioBufferRecognitionRequest, on-device so it never round-trips
through Apple's servers) fed by AVFoundation's AVAudioEngine tapping the raw
mic input. Its result handler fires repeatedly with the whole utterance's
best guess so far, right up until a final result — that's the partial
stream this module hands to callers.

SimulatedPartialTranscriptSource exists because this environment can't grant
the interactive Microphone/Speech-Recognition permission dialogs a real run
needs — it fakes the same start()/stop() interface by feeding a fixed
sentence word-by-word on a timer, so voice_loop.py's tick logic can be
exercised end-to-end without live audio.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger("edith.computer_use.speech_stream")

# How long to wait for the OS permission dialogs (Speech recognition, then
# mic record) to resolve before giving up — a real interactive session
# resolves these in a few seconds; a headless/non-interactive one (no one to
# click "Allow") never will, so this bounds the wait instead of hanging.
_PERMISSION_TIMEOUT_SECONDS = 15.0
_RUN_LOOP_POLL_SECONDS = 0.05


class SpeechStreamError(Exception):
    pass


class PartialTranscriptSource:
    """Interface both sources below implement."""

    def start(self, on_partial: Callable[[str], None], on_final: Callable[[str], None]) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError


def _pump_run_loop_until(predicate: Callable[[], bool], timeout: float) -> bool:
    """Spins the current thread's NSRunLoop so async completion handlers
    (permission dialogs, in particular) actually get delivered — a bare
    Python thread has no run loop pumping by default, so without this the
    callback simply never fires. Returns False on timeout."""
    import Foundation

    deadline = time.monotonic() + timeout
    run_loop = Foundation.NSRunLoop.currentRunLoop()
    while not predicate():
        if time.monotonic() >= deadline:
            return False
        run_loop.runMode_beforeDate_(
            Foundation.NSDefaultRunLoopMode,
            Foundation.NSDate.dateWithTimeIntervalSinceNow_(_RUN_LOOP_POLL_SECONDS),
        )
    return True


def _ensure_speech_authorized() -> None:
    import Speech

    status = Speech.SFSpeechRecognizer.authorizationStatus()
    if status == Speech.SFSpeechRecognizerAuthorizationStatusAuthorized:
        return
    if status in (
        Speech.SFSpeechRecognizerAuthorizationStatusDenied,
        Speech.SFSpeechRecognizerAuthorizationStatusRestricted,
    ):
        raise SpeechStreamError(
            "Speech Recognition permission was denied. Grant it in System Settings > "
            "Privacy & Security > Speech Recognition, then try again."
        )

    result: dict[str, int] = {}

    def _on_result(new_status: int) -> None:
        result["status"] = new_status

    Speech.SFSpeechRecognizer.requestAuthorization_(_on_result)
    if not _pump_run_loop_until(lambda: "status" in result, _PERMISSION_TIMEOUT_SECONDS):
        raise SpeechStreamError(
            "Speech Recognition permission wasn't granted within "
            f"{_PERMISSION_TIMEOUT_SECONDS:.0f}s — no interactive session to approve the "
            "system prompt. Grant it in System Settings > Privacy & Security > Speech "
            "Recognition, then try again."
        )
    if result["status"] != Speech.SFSpeechRecognizerAuthorizationStatusAuthorized:
        raise SpeechStreamError(
            "Speech Recognition permission was denied. Grant it in System Settings > "
            "Privacy & Security > Speech Recognition, then try again."
        )


def _ensure_mic_authorized() -> None:
    import AVFoundation

    app = AVFoundation.AVAudioApplication.sharedInstance()
    permission = app.recordPermission()
    if permission == AVFoundation.AVAudioApplicationRecordPermissionGranted:
        return
    if permission == AVFoundation.AVAudioApplicationRecordPermissionDenied:
        raise SpeechStreamError(
            "Microphone permission was denied. Grant it in System Settings > Privacy & "
            "Security > Microphone, then try again."
        )

    result: dict[str, bool] = {}

    def _on_result(granted: bool) -> None:
        result["granted"] = bool(granted)

    AVFoundation.AVAudioApplication.requestRecordPermissionWithCompletionHandler_(_on_result)
    if not _pump_run_loop_until(lambda: "granted" in result, _PERMISSION_TIMEOUT_SECONDS):
        raise SpeechStreamError(
            f"Microphone permission wasn't granted within {_PERMISSION_TIMEOUT_SECONDS:.0f}s — "
            "no interactive session to approve the system prompt. Grant it in System "
            "Settings > Privacy & Security > Microphone, then try again."
        )
    if not result["granted"]:
        raise SpeechStreamError(
            "Microphone permission was denied. Grant it in System Settings > Privacy & "
            "Security > Microphone, then try again."
        )


class MicPartialTranscriptSource(PartialTranscriptSource):
    """Continuous on-device speech recognition over the live mic. One
    start()/stop() cycle covers one utterance — SFSpeechRecognitionTask ends
    itself once it delivers a final result, same as a person finishing a
    sentence; callers wanting the next utterance call start() again."""

    def __init__(self, locale: str = "en-US") -> None:
        self._locale = locale
        self._engine: Optional[object] = None
        self._request: Optional[object] = None
        self._task: Optional[object] = None
        self._run_loop_thread: Optional[threading.Thread] = None
        self._running = threading.Event()

    def start(self, on_partial: Callable[[str], None], on_final: Callable[[str], None]) -> None:
        import AVFoundation
        import Foundation
        import Speech

        _ensure_speech_authorized()
        _ensure_mic_authorized()

        recognizer = Speech.SFSpeechRecognizer.alloc().initWithLocale_(
            Foundation.NSLocale.alloc().initWithLocaleIdentifier_(self._locale)
        )
        if recognizer is None or not recognizer.isAvailable():
            raise SpeechStreamError(f"No speech recognizer available for locale {self._locale!r}.")

        request = Speech.SFSpeechAudioBufferRecognitionRequest.alloc().init()
        request.setShouldReportPartialResults_(True)
        if request.respondsToSelector_("setRequiresOnDeviceRecognition:"):
            request.setRequiresOnDeviceRecognition_(True)

        engine = AVFoundation.AVAudioEngine.alloc().init()
        input_node = engine.inputNode()
        recording_format = input_node.outputFormatForBus_(0)

        def _tap(buffer, when) -> None:  # noqa: ARG001 — AVAudioEngine's tap signature
            request.appendAudioPCMBuffer_(buffer)

        input_node.installTapOnBus_bufferSize_format_block_(0, 1024, recording_format, _tap)
        engine.prepare()
        ok, error = engine.startAndReturnError_(None)
        if not ok:
            raise SpeechStreamError(f"Couldn't start the audio engine: {error}")

        def _on_result(result, error) -> None:
            if error is not None:
                logger.warning("speech recognition error: %s", error)
                return
            if result is None:
                return
            text = str(result.bestTranscription().formattedString())
            if result.isFinal():
                on_final(text)
            else:
                on_partial(text)

        task = recognizer.recognitionTaskWithRequest_resultHandler_(request, _on_result)

        self._engine, self._request, self._task = engine, request, task
        self._running.set()
        self._run_loop_thread = threading.Thread(target=self._pump_forever, daemon=True)
        self._run_loop_thread.start()

    def _pump_forever(self) -> None:
        import Foundation

        run_loop = Foundation.NSRunLoop.currentRunLoop()
        while self._running.is_set():
            run_loop.runMode_beforeDate_(
                Foundation.NSDefaultRunLoopMode,
                Foundation.NSDate.dateWithTimeIntervalSinceNow_(_RUN_LOOP_POLL_SECONDS),
            )

    def stop(self) -> None:
        self._running.clear()
        if self._engine is not None:
            self._engine.stop()
            self._engine.inputNode().removeTapOnBus_(0)
        if self._request is not None:
            self._request.endAudio()
        if self._task is not None:
            self._task.cancel()
        if self._run_loop_thread is not None:
            self._run_loop_thread.join(timeout=1.0)
        self._engine = self._request = self._task = self._run_loop_thread = None


class SimulatedPartialTranscriptSource(PartialTranscriptSource):
    """Fakes a partial-transcript stream by revealing `sentence` one word at
    a time on a background timer — for exercising voice_loop.py without live
    mic/Speech permission."""

    def __init__(self, sentence: str, word_delay_seconds: float = 0.35) -> None:
        self._words = sentence.split()
        self._word_delay = word_delay_seconds
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self, on_partial: Callable[[str], None], on_final: Callable[[str], None]) -> None:
        def _run() -> None:
            revealed: list[str] = []
            for word in self._words:
                if self._stop_event.is_set():
                    return
                revealed.append(word)
                on_partial(" ".join(revealed))
                time.sleep(self._word_delay)
            if not self._stop_event.is_set():
                on_final(" ".join(revealed))

        self._stop_event.clear()
        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._thread = None
