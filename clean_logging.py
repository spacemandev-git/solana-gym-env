import logging, textwrap, sys, os

def setup_clean_logging():
    # ── 1.  Dedent every log/print line that reaches stdout ───────────────────
    class _StdoutFilter(logging.Filter):
        def filter(self, rec):
            # textwrap.dedent removes any common leading whitespace
            rec.msg = '\n' + textwrap.dedent(str(rec.msg)).lstrip()
            return True

    root = logging.getLogger()
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_StdoutFilter())
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.INFO)           # or WARNING if you want less

    # ── 2.  Mute noisy libraries that print HTTP chatter ──────────────────────
    for noisy in ("httpcore", "httpx", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    os.environ["SOLANA_PY_RPC_DEBUG"] = "0"
