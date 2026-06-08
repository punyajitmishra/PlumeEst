from setuptools import setup, Extension
from Cython.Build import cythonize
import numpy as np

ext = Extension(
    name="plume",
    sources=[
        "plume.pyx",
        "plume_core.cpp",
    ],
    include_dirs=[np.get_include(), "."],
    language="c++",
    extra_compile_args=["-O3", "-std=c++17", "-ffast-math"],
)

setup(
    name="plumeest-engine",
    ext_modules=cythonize(
        [ext],
        compiler_directives={
            "language_level": "3",
            "boundscheck": False,
            "wraparound": False,
        },
    ),
)
