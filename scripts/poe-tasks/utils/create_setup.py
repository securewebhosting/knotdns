#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Original source:
# https://github.com/sdss/flicamera/blob/main/create_setup.py
# We modified the script so that it outputs the setup.py to stdout and that no
# version upper bounds are outputted in the depencency list.
#
# @Author: José Sánchez-Gallego (gallegoj@uw.edu)
# @Date: 2019-12-18
# @Filename: create_setup.py
# @License: BSD 3-clause (http://www.opensource.org/licenses/BSD-3-Clause)

# This is a temporary solution for the fact that pip install . fails with
# poetry when there is no setup.py and an extension needs to be compiled.
# See https://github.com/python-poetry/poetry/issues/1516. Running this
# script creates a setup.py filled out with information generated by
# poetry when parsing the pyproject.toml.

import os
import re
import sys

from packaging.version import Version

# If there is a global installation of poetry, prefer that.
lib = os.path.expanduser("~/.poetry/lib")
vendors = os.path.join(lib, "poetry", "_vendor")
current_vendors = os.path.join(vendors, "py{}".format(".".join(str(v) for v in sys.version_info[:2])))

sys.path.insert(0, lib)
sys.path.insert(0, current_vendors)

try:
    try:
        from poetry.core.factory import Factory
        from poetry.core.masonry.builders.sdist import SdistBuilder
    except (ImportError, ModuleNotFoundError):
        from poetry.masonry.builders.sdist import SdistBuilder
        from poetry.factory import Factory
    from poetry.__version__ import __version__
except (ImportError, ModuleNotFoundError) as ee:
    raise ImportError(f"install poetry by doing pip install poetry to use this script: {ee}")


# Generate a Poetry object that knows about the metadata in pyproject.toml
factory = Factory()
poetry = factory.create_poetry(os.path.dirname(__file__))

# Use the SdistBuilder to genrate a blob for setup.py
if Version(__version__) >= Version("1.1.0b1"):
    sdist_builder = SdistBuilder(poetry, None)
else:
    sdist_builder = SdistBuilder(poetry, None, None)

setuppy_blob: bytes = sdist_builder.build_setup()


# patch the result so that it does not contain upper bounds in dependencies
# (but it should contain them in python version)
setuppy = setuppy_blob.decode("utf8")
setuppy, _ = re.subn(r"(\'[^\']+>=[^<>=,\']*),<[^<>=,\']*\'", "\\1'", setuppy)

# output the setup.py script to stdout
print(setuppy)
print("\n# This setup.py was autogenerated using Poetry for backward compatibility with setuptools.")