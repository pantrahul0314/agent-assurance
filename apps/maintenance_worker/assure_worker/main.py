from __future__ import annotations

import time

from assure_control_api.db import init_db, make_engine, make_session_factory
from assure_control_api.seed import seed_if_empty
from assure_worker.loop import reap_once, sleep_interval


def main() -> None:
    engine = make_engine()
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        seed_if_empty(session)
        session.commit()
    epoch = 1
    while True:
        with factory() as session:
            reap_once(session, epoch)
            session.commit()
        epoch += 1
        time.sleep(sleep_interval())


if __name__ == "__main__":
    main()
