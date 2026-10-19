.. contents:: **pathvalidate**
   :backlinks: top
   :depth: 2

Summary
=========
`pathvalidate <https://github.com/thombashi/pathvalidate>`__ is a Python library to sanitize/validate a string such as filenames/file-paths/etc.

.. note::

   This is a fork that adds batch scanning and safe renaming
   (``pathvalidate.batch`` and the ``pvscan`` command). The GitHub landing page
   is ``README.md``; this file is the package long description used by PyPI.
   Fork specific details are in ``FORK.md`` and ``NOTICE.md``.

|PyPI pkg ver| |conda pkg ver| |Supported Python ver| |Supported Python impl| |CI status| |Test coverage| |CodeQL|

.. |PyPI pkg ver| image:: https://badge.fury.io/py/pathvalidate.svg
    :target: https://badge.fury.io/py/pathvalidate
    :alt: PyPI package version

.. |conda pkg ver| image:: https://anaconda.org/conda-forge/pathvalidate/badges/version.svg
    :target: https://anaconda.org/conda-forge/pathvalidate
    :alt: conda package version

.. |Supported Python ver| image:: https://img.shields.io/pypi/pyversions/pathvalidate.svg
    :target: https://pypi.org/project/pathvalidate
    :alt: Supported Python versions

.. |Supported Python impl| image:: https://img.shields.io/pypi/implementation/pathvalidate.svg
    :target: https://pypi.org/project/pathvalidate
    :alt: Supported Python implementations

.. |CI status| image:: https://github.com/thombashi/pathvalidate/actions/workflows/ci.yml/badge.svg
    :target: https://github.com/thombashi/pathvalidate/actions/workflows/ci.yml
    :alt: CI status of Linux/macOS/Windows

.. |Test coverage| image:: https://coveralls.io/repos/github/thombashi/pathvalidate/badge.svg?branch=master
    :target: https://coveralls.io/github/thombashi/pathvalidate?branch=master
    :alt: Test coverage: coveralls

.. |CodeQL| image:: https://github.com/thombashi/pathvalidate/actions/workflows/github-code-scanning/codeql/badge.svg
    :target: https://github.com/thombashi/pathvalidate/actions/workflows/github-code-scanning/codeql
    :alt: CodeQL

Features
---------
- Sanitize/Validate a string as a:
    - file name
    - file path
- Sanitize will do:
    - Remove invalid characters for a target platform
    - Replace reserved names for a target platform
    - Normalize
    - Remove unprintable characters
- Argument validator/sanitizer for ``argparse`` and ``click``
- Multi platform support:
    - ``Linux``
    - ``Windows``
    - ``macOS``
    - ``POSIX``: POSIX-compliant systems (Linux, macOS, etc.)
    - ``universal``: platform independent
- Multibyte character support
- **Batch scanning and safe renaming** of whole directory trees
  (``pathvalidate.batch`` and the bundled ``pvscan`` command)
    - per path component diagnostics
    - extension preserving truncation
    - collision resolution after sanitization
    - invisible / unnormalized Unicode and WSL private use area detection
    - bottom-up renames with rollback

CLI tool
---------
This fork bundles a ``pvscan`` command line tool. It scans a directory tree for
file names that break on another platform, and can repair them:

.. code-block:: console

    $ pvscan check ./downloads --platform windows
    $ pvscan fix   ./downloads --platform windows            # dry run
    $ pvscan fix   ./downloads --platform windows --apply    # rename

``check`` never writes to the filesystem. ``fix`` only renames when ``--apply``
is given. Both support ``--json`` for scripting.

The separate `pathvalidate-cli <https://github.com/thombashi/pathvalidate-cli>`__
repository is still the place to look for the original single-name CLI.

Examples
==========
Sanitize a filename
---------------------
:Sample Code:
    .. code-block:: python

        from pathvalidate import sanitize_filename

        fname = "fi:l*e/p\"a?t>h|.t<xt"
        print(f"{fname} -> {sanitize_filename(fname)}\n")

        fname = "\0_a*b:c<d>e%f/(g)h+i_0.txt"
        print(f"{fname} -> {sanitize_filename(fname)}\n")

:Output:
    .. code-block::

        fi:l*e/p"a?t>h|.t<xt -> filepath.txt

        _a*b:c<d>e%f/(g)h+i_0.txt -> _abcde%f(g)h+i_0.txt

The default target ``platform`` is ``universal``.
i.e. the sanitized file name is valid for any platform.

Sanitize a filepath
---------------------
:Sample Code:
    .. code-block:: python

        from pathvalidate import sanitize_filepath

        fpath = "fi:l*e/p\"a?t>h|.t<xt"
        print(f"{fpath} -> {sanitize_filepath(fpath)}\n")

        fpath = "\0_a*b:c<d>e%f/(g)h+i_0.txt"
        print(f"{fpath} -> {sanitize_filepath(fpath)}\n")

:Output:
    .. code-block::

        fi:l*e/p"a?t>h|.t<xt -> file/path.txt

        _a*b:c<d>e%f/(g)h+i_0.txt -> _abcde%f/(g)h+i_0.txt

Validate a filename
---------------------
:Sample Code:
    .. code-block:: python

        import sys
        from pathvalidate import ValidationError, validate_filename

        try:
            validate_filename("fi:l*e/p\"a?t>h|.t<xt")
        except ValidationError as e:
            print(f"{e}\n", file=sys.stderr)

        try:
            validate_filename("COM1")
        except ValidationError as e:
            print(f"{e}\n", file=sys.stderr)

:Output:
    .. code-block::

        [PV1100] invalid characters found: platform=universal, description=invalids=('/'), value='fi:l*e/p"a?t>h|.t<xt'

        [PV1002] found a reserved name by a platform: 'COM1' is a reserved name, platform=universal, reusable_name=False

Check a filename
------------------
:Sample Code:
    .. code-block:: python

        from pathvalidate import is_valid_filename, sanitize_filename

        fname = "fi:l*e/p\"a?t>h|.t<xt"
        print(f"is_valid_filename('{fname}') return {is_valid_filename(fname)}\n")

        sanitized_fname = sanitize_filename(fname)
        print(f"is_valid_filename('{sanitized_fname}') return {is_valid_filename(sanitized_fname)}\n")

:Output:
    .. code-block::

        is_valid_filename('fi:l*e/p"a?t>h|.t<xt') return False

        is_valid_filename('filepath.txt') return True

filename/filepath validator for ``argparse``
----------------------------------------------
:Sample Code:
    .. code-block:: python

        from argparse import ArgumentParser

        from pathvalidate.argparse import validate_filename_arg, validate_filepath_arg

        parser = ArgumentParser()
        parser.add_argument("--filename", type=validate_filename_arg)
        parser.add_argument("--filepath", type=validate_filepath_arg)
        options = parser.parse_args()

        if options.filename:
            print(f"filename: {options.filename}")

        if options.filepath:
            print(f"filepath: {options.filepath}")

:Output:
    .. code-block::

        $ ./examples/argparse_validate.py --filename eg
        filename: eg
        $ ./examples/argparse_validate.py --filename e?g
        usage: argparse_validate.py [-h] [--filename FILENAME] [--filepath FILEPATH]
        argparse_validate.py: error: argument --filename: [PV1100] invalid characters found: invalids=(':'), value='e:g', platform=Windows

.. note::
    ``validate_filepath_arg`` consider ``platform`` as of ``"auto"`` if the input is an absolute file path.

filename/filepath sanitizer for ``argparse``
----------------------------------------------
:Sample Code:
    .. code-block:: python

        from argparse import ArgumentParser

        from pathvalidate.argparse import sanitize_filename_arg, sanitize_filepath_arg


        parser = ArgumentParser()
        parser.add_argument("--filename", type=sanitize_filename_arg)
        parser.add_argument("--filepath", type=sanitize_filepath_arg)
        options = parser.parse_args()

        if options.filename:
            print("filename: {}".format(options.filename))

        if options.filepath:
            print("filepath: {}".format(options.filepath))

:Output:
    .. code-block::

        $ ./examples/argparse_sanitize.py --filename e/g
        filename: eg

.. note::
    ``sanitize_filepath_arg`` is set platform as ``"auto"``.

filename/filepath validator for ``click``
-------------------------------------------
:Sample Code:
    .. code-block:: python

        import click

        from pathvalidate.click import validate_filename_arg, validate_filepath_arg


        @click.command()
        @click.option("--filename", callback=validate_filename_arg)
        @click.option("--filepath", callback=validate_filepath_arg)
        def cli(filename: str, filepath: str) -> None:
            if filename:
                click.echo(f"filename: {filename}")
            if filepath:
                click.echo(f"filepath: {filepath}")


        if __name__ == "__main__":
            cli()

:Output:
    .. code-block::

        $ ./examples/click_validate.py --filename ab
        filename: ab
        $ ./examples/click_validate.py --filepath e?g
        Usage: click_validate.py [OPTIONS]
        Try 'click_validate.py --help' for help.

        Error: Invalid value for '--filename': [PV1100] invalid characters found: invalids=('?'), value='e?g', platform=Windows

filename/filepath sanitizer for ``click``
-------------------------------------------
:Sample Code:
    .. code-block:: python

        import click

        from pathvalidate.click import sanitize_filename_arg, sanitize_filepath_arg


        @click.command()
        @click.option("--filename", callback=sanitize_filename_arg)
        @click.option("--filepath", callback=sanitize_filepath_arg)
        def cli(filename, filepath):
            if filename:
                click.echo(f"filename: {filename}")
            if filepath:
                click.echo(f"filepath: {filepath}")


        if __name__ == "__main__":
            cli()

:Output:
    .. code-block::

        $ ./examples/click_sanitize.py --filename a/b
        filename: ab

For more information
----------------------
More examples can be found at 
https://pathvalidate.rtfd.io/en/latest/pages/examples/index.html

Batch scanning and safe renaming
---------------------------------
``sanitize_filename`` works on one name at a time. Repairing a directory tree
needs a little more: the extension has to survive truncation, two different
names must not collapse into the same target, and a parent directory may only be
renamed after its children.

.. code-block:: python

    from pathvalidate import scan_paths, plan_fixes

    result = scan_paths("./downloads", platform="windows")

    for report in result.reports:
        for issue in report.issues:
            print(report.relative, issue.code, issue.kind)

    plan = plan_fixes(result)
    for rename in plan:
        print(rename.source.name, "->", rename.target.name, rename.reasons)

    plan.apply()   # or: plan.apply() is skipped and only the plan is inspected

What the batch layer adds on top of the single name API:

``split_name``
    ``"archive.tar.gz"`` splits into ``("archive", ".tar.gz")`` instead of
    ``("archive.tar", ".gz")``, and dot files such as ``".bashrc"`` keep no
    extension.

``fit_length``
    Truncates to a byte budget while keeping the compound extension, so a
    255 byte limit turns ``"a" * 250 + ".tar.gz"`` into ``"a" * 248 + ".tar.gz"``
    rather than silently dropping ``.gz``.

Collision resolution
    ``"a:b"`` and ``"a|b"`` both sanitize to ``"a_b"`` on Windows. The second
    one becomes ``"a_b (2)"`` instead of overwriting the first.

WSL private use area detection
    Windows Subsystem for Linux stores characters NTFS forbids (``|``, ``:``,
    ``*`` ...) in the Unicode private use area starting at ``U+F000``. Such
    names pass a plain validator but break on copy, so they are reported as
    ``PVX004`` and repaired by :py:func:`pathvalidate.decode_wsl_name`.

Extended length prefix
    Windows silently strips trailing spaces and dots from a path, which makes a
    file named ``"report. "`` unreachable through the ordinary API. Renames fall
    back to the ``\\?\`` prefix so those files can actually be repaired.

Rollback
    If a rename fails half way through, the renames that already succeeded are
    reverted and :py:class:`pathvalidate.BatchRenameError` is raised.

Installation
============
Installation: pip
------------------------------
::

    pip install pathvalidate

Installation: conda
------------------------------
::

    conda install conda-forge::pathvalidate

Installation: apt
------------------------------
::

    sudo add-apt-repository ppa:thombashi/ppa
    sudo apt update
    sudo apt install python3-pathvalidate


Dependencies
============
Python 3.9+
no external dependencies.

Documentation
===============
https://pathvalidate.rtfd.io/

Sponsors
====================================
|chasbecker| |shiguredo| |b4tman| |Arturi0| |github|

.. |chasbecker| image:: https://avatars.githubusercontent.com/u/44389260?s=48&u=6da7176e51ae2654bcfd22564772ef8a3bb22318&v=4
   :target: https://github.com/chasbecker
   :alt: ex-sponsor: Charles Becker (chasbecker)
.. |shiguredo| image:: https://avatars.githubusercontent.com/u/2549434?s=48&v=4
   :target: https://github.com/shiguredo
   :alt: ex-sponsor: 時雨堂 (shiguredo)
.. |b4tman| image:: https://avatars.githubusercontent.com/u/3658062?s=48&v=4
   :target: https://github.com/b4tman
   :alt: onetime: Dmitry Belyaev (b4tman)
.. |Arturi0| image:: https://avatars.githubusercontent.com/u/46711571?s=48&u=57687c0e02d5d6e8eeaf9177f7b7af4c9f275eb5&v=4
   :target: https://github.com/Arturi0
   :alt: onetime: Arturi0
.. |github| image:: https://avatars.githubusercontent.com/u/9919?s=48&v=4
   :target: https://github.com/github
   :alt: onetime: GitHub (github)

`Become a sponsor <https://github.com/sponsors/thombashi>`__

