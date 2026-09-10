"""Shared flags for the reference hosted C11 build paths."""


def compiler_command(cc, source, output):
    return [cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-pedantic-errors",
            str(source), "-o", str(output)]
