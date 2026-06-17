"""Fail-safe OpenTelemetry instrumentation.

Never break an agent because telemetry is misconfigured or the collector is down.
No-ops cleanly when OTEL_EXPORTER_OTLP_ENDPOINT is unset.
"""
import os
from contextlib import contextmanager

_TRACER = None


class _NoopSpan:
    def set_attribute(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _NoopTracer:
    def start_as_current_span(self, *a, **k):
        return _NoopSpan()


def get_tracer():
    global _TRACER
    if _TRACER is not None:
        return _TRACER
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        _TRACER = _NoopTracer()
        return _TRACER
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider = TracerProvider(
            resource=Resource.create(
                {"service.name": os.environ.get("OTEL_SERVICE_NAME", "qa-agent-platform")}
            )
        )
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        _TRACER = trace.get_tracer("qa-agent-platform")
    except Exception:
        _TRACER = _NoopTracer()  # fail-safe
    return _TRACER


@contextmanager
def span(name: str, **attrs):
    # Fail-safe ONLY around span *setup* — never wrap the yield in try/except, or an
    # exception from the with-body gets thrown back into this generator and we'd yield a
    # second time → "generator didn't stop after throw()" (and the real error is masked).
    tracer = get_tracer()
    try:
        cm = tracer.start_as_current_span(name)
    except Exception:
        cm = None
    if cm is None:
        yield _NoopSpan()  # span creation failed — degrade, run the body untraced
        return
    with cm as s:
        for k, v in attrs.items():
            try:
                s.set_attribute(k, v)
            except Exception:
                pass
        yield s  # body exceptions propagate normally through `with cm`
