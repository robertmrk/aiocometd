import os
from setuptools import setup

here = os.path.abspath(os.path.dirname(__file__))

metadata = {}
metadata_path = os.path.join(here, "aiocometd/_metadata.py")
with open(metadata_path, "rt", encoding="utf-8") as f:
    exec(f.read(), metadata)

REQUIRED_PACKAGES = [
    "aiohttp>=3.1.1",
    "Sphinx>=1.7.2",
    "sphinx-rtd-theme>=0.2.4"
]

setup(
    name=metadata["TITLE"],
    version=metadata["VERSION"],
    description=metadata["DESCRIPTION"],
    author=metadata["AUTHOR"],
    author_email=metadata["AUTHOR_EMAIL"],
    license="MIT",
    packages=["aiocometd"],
    install_requires=REQUIRED_PACKAGES,
    include_package_data=True,
    classifiers=[
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: Implementation :: CPython"
    ],
    test_suite="tests"
)
