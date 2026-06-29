"""B3: prove the RQ queue + worker run a trivial job. Uses fakeredis + a burst run
of the real WorkerClass, so the test is hermetic (no live Redis or worker process)
yet exercises the same worker the entrypoint runs."""
import fakeredis
from rq import Queue

from app.workers.queue import QUEUE_NAME
from app.workers.tasks import ping
from app.workers.worker import WorkerClass


def test_trivial_job_runs_on_worker():
    conn = fakeredis.FakeStrictRedis()
    queue = Queue(QUEUE_NAME, connection=conn)

    job = queue.enqueue(ping)
    assert job.get_status() == "queued"

    # burst: drain the queue in-process, then return
    WorkerClass([queue], connection=conn).work(burst=True)

    job.refresh()
    assert job.is_finished
    assert job.return_value() == "pong"
