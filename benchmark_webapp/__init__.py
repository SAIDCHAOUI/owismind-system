"""benchmark_webapp - the OWIsMind_LAB standard-webapp layer over the benchmark Flow.

Recolled into the OWIsMind_LAB project library next to ``benchmark``. ``views`` is PURE
(stdlib + benchmark.run_params), so the restitution / config shaping is unit-tested without a
live DSS runtime. The webapp panes (backend.py / body.html / style.css / script.js) are pasted
into a DSS Standard webapp; only backend.py imports dataiku.
"""
