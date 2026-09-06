import multiprocessing
import os
import queue

import pytest

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtNetwork import QLocalServer

from linuxprint.ipc import AcquisitionResult, SingleInstanceServer


def _leave_stale_socket(socket_name, connection):
    app = QCoreApplication([])
    server = QLocalServer()
    connection.send(server.listen(socket_name))
    connection.close()
    os._exit(0)


def _attempt_acquisition(socket_name, lock_file, ready, start, release, results, watchers):
    app = QCoreApplication([])
    server = SingleInstanceServer(socket_name, lock_file)
    ready.put(os.getpid())
    start.wait()
    result = server.acquire()
    if result is AcquisitionResult.PRIMARY:
        watchers.put(os.getpid())
    results.put(result.name)
    if result is AcquisitionResult.PRIMARY:
        release.wait(10)


def test_concurrent_stale_socket_recovery_starts_one_watcher(tmp_path):
    context = multiprocessing.get_context("spawn")
    socket_name = f"jadiv-print-center-test-{os.getpid()}"
    lock_file = str(tmp_path / "instance.lock")

    parent_connection, child_connection = context.Pipe(duplex=False)
    stale_process = context.Process(
        target=_leave_stale_socket,
        args=(socket_name, child_connection),
    )
    stale_process.start()
    child_connection.close()
    assert parent_connection.recv() is True
    stale_process.join(10)
    assert stale_process.exitcode == 0

    process_count = 4
    ready = context.Queue()
    start = context.Event()
    release = context.Event()
    results = context.Queue()
    watchers = context.Queue()
    processes = [
        context.Process(
            target=_attempt_acquisition,
            args=(socket_name, lock_file, ready, start, release, results, watchers),
        )
        for _ in range(process_count)
    ]

    try:
        for process in processes:
            process.start()
        for _ in processes:
            ready.get(timeout=15)

        start.set()
        acquisition_results = [results.get(timeout=15) for _ in processes]
        assert acquisition_results.count(AcquisitionResult.PRIMARY.name) == 1
        assert acquisition_results.count(AcquisitionResult.SECONDARY.name) == process_count - 1
        assert watchers.get(timeout=5)
        with pytest.raises(queue.Empty):
            watchers.get(timeout=0.1)
    finally:
        release.set()
        for process in processes:
            process.join(10)
            if process.is_alive():
                process.terminate()
                process.join(5)
        QLocalServer.removeServer(socket_name)

    assert all(process.exitcode == 0 for process in processes)
