"""Cython build configuration for ChronosMatch matching engine.

Usage
-----
    python setup.py build_ext --inplace

This compiles ``chronos/matching_engine.pyx`` into a platform-specific
shared library (e.g. ``.pyd`` on Windows) that can be imported directly::

    from chronos.matching_engine import MatchingEngine
"""

from setuptools import setup, Extension
from Cython.Build import cythonize

extensions = [
    Extension(
        name="chronos.matching_engine",
        sources=["chronos/matching_engine.pyx"],
    ),
]

setup(
    name="chronos-matching-engine",
    ext_modules=cythonize(
        extensions,
        compiler_directives={
            "language_level": "3",       # Python 3 semantics
            "boundscheck": False,        # Disable for performance
            "wraparound": False,         # Disable negative-index wrapping
        },
    ),
)
