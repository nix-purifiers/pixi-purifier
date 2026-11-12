# SPDX-License-Identifier: MIT
# Rattler's activation script uses this absolute command inside Bash.
{ writeText, coreutils }:
writeText "pixi-activation-bash-env" ''
  function /usr/bin/env { ${coreutils}/bin/env "$@"; }
''
