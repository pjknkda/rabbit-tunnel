def test_init_environment() -> None:
    from app import init_environment
    init_environment()


def test_Worker() -> None:
    from app import Worker

    worker = Worker()
    worker.run()
