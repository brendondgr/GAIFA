"""The stt mod: speech to text with faster-whisper, ported from the TranscriberPrototype (plan Phase 29).

``asr`` (the model behind one interface, in its own process), ``audio`` (formats, resampling,
decoding), ``vad`` (pauses), ``batch`` (a finished file, cut at pauses), ``streaming`` (live text by
LocalAgreement), ``engine`` (which model is loaded), ``jobs`` and ``transcripts`` (file jobs and
their outputs), ``server`` (the HTTP and WebSocket routes).
"""
