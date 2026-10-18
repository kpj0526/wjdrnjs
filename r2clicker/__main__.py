import sys


def run() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        from .selftest import main as selftest

        return selftest(sys.argv[2])
    from .gui import main

    main(force_visible="--show-window" in sys.argv)
    return 0


if __name__ == "__main__":
    sys.exit(run())
