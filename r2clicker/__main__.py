import sys


def run() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        from .selftest import main as selftest

        return selftest(sys.argv[2])
    from .gui import main

    main()
    return 0


if __name__ == "__main__":
    sys.exit(run())
