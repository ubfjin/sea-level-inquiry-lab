import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app import netcdf_io


def test_netcdf_reads_are_serialized(monkeypatch):
    state_lock = threading.Lock()
    active = 0
    maximum = 0

    class FakeDataset:
        def __enter__(self):
            nonlocal active, maximum
            with state_lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.02)
            return self

        def __exit__(self, exc_type, exc, traceback):
            nonlocal active
            with state_lock:
                active -= 1

    monkeypatch.setattr(
        netcdf_io.xr,
        "open_dataset",
        lambda path, **kwargs: FakeDataset(),
    )

    def read_once():
        with netcdf_io.open_netcdf("sample.nc"):
            time.sleep(0.02)

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda _: read_once(), range(12)))

    assert maximum == 1
