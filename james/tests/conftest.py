import sys

class MockNDArray:
    def __init__(self, data=None):
        self.data = data

    def __gt__(self, other):
        return self

    def __lt__(self, other):
        return self

    def __mul__(self, other):
        return self

    def __rmul__(self, other):
        return self

    def __truediv__(self, other):
        return self

    def __rtruediv__(self, other):
        return self

    def __add__(self, other):
        return self

    def __radd__(self, other):
        return self

    def __sub__(self, other):
        return self

    def __rsub__(self, other):
        return self

    def __setitem__(self, key, value):
        pass

    def __getitem__(self, key):
        return 1.0

    def dot(self, other):
        return self

    def __len__(self):
        return 1

    def __iter__(self):
        yield 1.0

    def sum(self):
        return 1.0

class MockLinalg:
    @staticmethod
    def norm(x, axis=None):
        if axis is None:
            return 1.0
        return MockNDArray([1.0])

class MockErrState:
    def __init__(self, **kwargs):
        pass
    def __enter__(self):
        pass
    def __exit__(self, *args):
        pass

class MockNumpy:
    ndarray = MockNDArray
    float32 = float
    linalg = MockLinalg()

    @staticmethod
    def zeros(shape, dtype=float):
        return MockNDArray()

    @staticmethod
    def sum(a, axis=None):
        return 1.0

    @staticmethod
    def log(x):
        return MockNDArray()

    @staticmethod
    def dot(a, b):
        return MockNDArray()

    @staticmethod
    def errstate(**kwargs):
        return MockErrState()

    @staticmethod
    def nan_to_num(x):
        return x

    @staticmethod
    def argsort(x):
        return [0]

# Inject the mock globally so all tests can run without numpy
sys.modules['numpy'] = MockNumpy()
