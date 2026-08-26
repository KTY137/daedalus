"""Vector-algebra primitives for EXPERIMENT ``tensor-embedding-v1``.

Holographic Reduced Representations (Plate 1995): a fixed-width vector algebra
in which binding is circular convolution, its approximate inverse is circular
correlation with the involution, and superposition is addition.

Nothing in this module is novel. It is the substrate the experiment measures
*on*, not the thing under test. See ``runs/tensor_embedding_v1/SPEC.md``.

Isolation (SPEC §5): this module imports nothing from ``daedalus`` and nothing
in ``daedalus`` imports it.

Determinism: every random draw goes through an explicitly seeded
``numpy.random.Generator``. Trigram hashing uses ``zlib.crc32`` rather than
``hash()`` because CPython randomises string hashing per process, which would
make two runs of the same experiment disagree.
"""

from __future__ import annotations

import zlib

import numpy as np

TRIGRAM_BOOK_SIZE = 4096


def codebook(n: int, d: int, rng: np.random.Generator) -> np.ndarray:
    """``n`` independent random vectors of width ``d``, i.i.d. N(0, 1/d)."""
    return rng.normal(0.0, 1.0 / np.sqrt(d), size=(n, d))


def bind(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Circular convolution of two vectors of equal width."""
    width = a.shape[-1]
    return np.fft.irfft(np.fft.rfft(a) * np.fft.rfft(b), n=width)


def involution(a: np.ndarray) -> np.ndarray:
    """``a*[i] = a[(-i) mod d]`` -- the approximate inverse used to unbind."""
    return np.concatenate([a[..., :1], a[..., :0:-1]], axis=-1)


def unbind(bundled: np.ndarray, role: np.ndarray) -> np.ndarray:
    """Recover the (noisy) filler that was bound to ``role``."""
    return bind(bundled, involution(role))


def bundle(vectors) -> np.ndarray:
    """Superposition. The sum, deliberately unnormalised."""
    return np.sum(np.asarray(vectors), axis=0)


def normalise(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) + 1e-12)


def cosine(a: np.ndarray, book: np.ndarray) -> np.ndarray:
    """Cosine of ``a`` against every row of ``book``."""
    unit = normalise(a)
    rows = book / (np.linalg.norm(book, axis=-1, keepdims=True) + 1e-12)
    return rows @ unit


def cleanup(noisy: np.ndarray, book: np.ndarray) -> int:
    """Index of the codebook entry the noisy vector most resembles."""
    return int(np.argmax(cosine(noisy, book)))


def trigram_book(d: int, rng: np.random.Generator) -> np.ndarray:
    """A fixed codebook of character-trigram vectors."""
    return codebook(TRIGRAM_BOOK_SIZE, d, rng)


def _trigrams(text: str) -> list[str]:
    padded = f"^{text.lower()}$"
    return [padded[i : i + 3] for i in range(max(0, len(padded) - 2))]


def text_vector(text: str, book: np.ndarray) -> np.ndarray:
    """Compositional name vector: the normalised sum of its trigram vectors.

    Compositional rather than atomic on purpose (SPEC §6a.2). With atomic
    vectors ``bias_voltage`` would sit exactly as far from ``voltage`` as from
    ``id``, and the renamed scenario would be unsolvable by construction rather
    than by evidence.
    """
    acc = np.zeros(book.shape[1])
    for gram in _trigrams(text):
        acc += book[zlib.crc32(gram.encode("utf-8")) % TRIGRAM_BOOK_SIZE]
    return normalise(acc)


def atom(label: str, book: np.ndarray) -> np.ndarray:
    """A stable atomic vector for a categorical value (plane, kind, revision)."""
    return normalise(book[zlib.crc32(f"atom:{label}".encode("utf-8")) % TRIGRAM_BOOK_SIZE])
