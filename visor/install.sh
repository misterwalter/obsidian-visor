#!/bin/bash
# Visor moved from this folder to the top of the repository. A server still on the old code runs the
# install from here once, as it updates past the move; this hands it on. Delete this folder once it has.
exec bash "$(dirname "$(dirname "$(realpath "$0")")")/install.sh" "$@"
