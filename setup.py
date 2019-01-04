import os
from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))

INSTALL_REQUIRES = [
    "aiohttp>=3.1,<4.0"
]
TESTS_REQUIRE = [
    "asynctest>=0.12.0,<1.0.0",
    "coverage>=4.5,<5.0",
    "docker>=3.5.1",
    "flake8",
    "pylint",
    "mypy"
]
DOCS_REQUIRE = [
    "Sphinx>=1.7,<2.0",
    "sphinxcontrib-asyncio>=0.2.0",
    "sphinx-autodoc-typehints"
]
EXAMPLES_REQUIRE = [
    "aioconsole>=0.1.7,<1.0.0"
]
DEV_REQUIRE = []


def read(file_path):
    with open(os.path.join(here, file_path)) as file:
        return file.read().strip()


metadata = {}
metadata_path = os.path.join(here, "aiocometd/_metadata.py")
exec(read(metadata_path), metadata)


setup(
    name=metadata["TITLE"],
    version=metadata["VERSION"],
    description=metadata["DESCRIPTION"],
    long_description='\n\n'.join((read('DESCRIPTION.rst'),
                                  read('docs/source/changes.rst'))),
    classifiers=[
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: Implementation :: CPython",
        "Framework :: AsyncIO",
        "License :: OSI Approved :: MIT License"
    ],
    keywords=metadata["KEYWORDS"],
    author=metadata["AUTHOR"],
    author_email=metadata["AUTHOR_EMAIL"],
    url=metadata["URL"],
    project_urls=metadata["PROJECT_URLS"],
    license="MIT",
    packages=find_packages(exclude=("tests*", "examples")),
    python_requires=">=3.6.0",
    install_requires=INSTALL_REQUIRES,
    tests_require=TESTS_REQUIRE,
    extras_require={
        "tests": TESTS_REQUIRE,
        "docs": DOCS_REQUIRE,
        "examples": EXAMPLES_REQUIRE,
        "dev": DEV_REQUIRE + TESTS_REQUIRE + DOCS_REQUIRE + EXAMPLES_REQUIRE
    },
    include_package_data=True,
    test_suite="tests"
)
