"""Visor moved from this folder to the top of the repository. A server still on the old code restarts
from here once, as it updates past the move; this hands it on. Delete this folder once it has."""
import os
import sys

TOP = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
os.execv(sys.executable, [sys.executable, os.path.join(TOP, "dispatch.py")] + sys.argv[1:])
