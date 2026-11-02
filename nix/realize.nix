# SPDX-License-Identifier: MIT
{
  project,
  lockFile,
  pixiLock,
  manifestFile,
  target,
}:
let
  pkgs = import (builtins.toPath "@nixpkgs@") { };
  purifier = import (builtins.toPath "@purifier@/nix/lib") { inherit (pkgs) lib; };
  args = {
    src = /. + project;
    lockFile = /. + lockFile;
    pixiLock = /. + pixiLock;
    manifestFile = /. + manifestFile;
  };
  result = pkgs.callPackage ./build-project.nix { inherit purifier; } args;
in
if target == "workspace" then
  result.workspace
else if target == "runtime" then
  pkgs.runCommand "pixi-runtime" { } ''ln -s @runtime@ "$out"''
else if target == "release" then
  result.release
else
  throw "pixi-purifier: unknown realization target ${target}"
