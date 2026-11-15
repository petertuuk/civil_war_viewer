"""Shared pieces of the pipeline (roadmap T3.1, T3.6, T3.8): `params` (named numbers) and `paths` (where things live).

Scripts run as `python3 pipeline/<script>.py`, which puts pipeline/ first on the import path, so `from cwv import params` works
in all of them. rebuild.sh / stamps.py count the files here as inputs of every stage whose scripts import the package.
"""
