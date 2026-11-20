"""Explicit entry point for disposable service fault-injection fixtures."""

import argparse

if __package__:
    from . import choice_b_service, service_main
    from .fixture_adapters import FixtureAsgiAdapter, FixtureSenderAdapter
else:
    import choice_b_service
    import service_main
    from fixture_adapters import FixtureAsgiAdapter, FixtureSenderAdapter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("asgi", "sender"))
    args = parser.parse_args()
    if args.mode == "asgi":
        service_main.main(adapter_factory=FixtureAsgiAdapter)
    else:
        choice_b_service.main(adapter_factory=FixtureSenderAdapter)


if __name__ == "__main__":
    main()
