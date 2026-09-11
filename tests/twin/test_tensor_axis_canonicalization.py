from __future__ import annotations

from daedalus.twin.tensor import TensorAxis


class StripCountingLabel(str):
    """Count semantic non-empty validation without changing string ordering."""

    def __new__(cls, value: str) -> "StripCountingLabel":
        instance = super().__new__(cls, value)
        instance.strip_calls = 0
        return instance

    def strip(self, *args: object, **kwargs: object) -> str:
        self.strip_calls += 1
        return super().strip(*args, **kwargs)


def test_unsorted_tensor_axis_validates_each_label_once() -> None:
    labels = (
        StripCountingLabel("label-z"),
        StripCountingLabel("label-a"),
        StripCountingLabel("label-m"),
    )

    axis = TensorAxis("node", labels)

    assert axis.labels == ("label-a", "label-m", "label-z")
    assert [label.strip_calls for label in labels] == [1, 1, 1]
