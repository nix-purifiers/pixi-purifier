# SPDX-License-Identifier: MIT
{
  lib,
  stdenv,
  runCommand,
  writeText,
  fetchurl,
  pixi,
  python3,
  patchelf,
  cacert,
  coreutils,
  gnutar,
  gzip,
  purifier,
}:
{
  src,
  lockFile ? src + "/pixi-purifier.lock.json",
  pixiLock ? src + "/pixi.lock",
  manifestFile ?
    if builtins.pathExists (src + "/pixi.toml") then src + "/pixi.toml" else src + "/pyproject.toml",
  fetchers ? { },
  testCommand ? null,
}:
let
  lock = purifier.checkLock (
    (import ../../lib-overlays/default/read-lock.nix { inherit lib; }) {
      inherit
        src
        lockFile
        pixiLock
        manifestFile
        ;
    }
  );
  workspace =
    (import ./environment.nix {
      inherit
        lib
        stdenv
        runCommand
        writeText
        fetchurl
        pixi
        python3
        patchelf
        cacert
        coreutils
        purifier
        ;
    })
      {
        inherit
          src
          lock
          pixiLock
          manifestFile
          fetchers
          ;
      };
  bashEnvironment = import ./bash-env.nix { inherit writeText coreutils; };
  platform =
    {
      x86_64-linux = "linux-64";
      aarch64-linux = "linux-aarch64";
    }
    .${stdenv.hostPlatform.system};
  names = lib.filter (name: builtins.hasAttr platform lock.outputs.${name}.packages) (
    builtins.attrNames lock.outputs
  );
  environment =
    name:
    runCommand "pixi-${name}-environment" { }
      ''ln -s ${workspace}/workspace/.pixi/envs/${name} "$out"'';
  packages = lib.genAttrs names environment;
  default = if builtins.elem "default" names then "default" else builtins.head names;
  source = lib.cleanSourceWith {
    inherit src;
    filter =
      path: type:
      !(builtins.elem (baseNameOf path) [
        ".git"
        ".pixi"
        ".pixi-purifier"
        "__pycache__"
      ])
      && !(lib.hasPrefix "result" (baseNameOf path));
  };
  tests = runCommand "pixi-project-tests" { nativeBuildInputs = [ pixi ]; } ''
    export HOME="$TMPDIR/home" PIXI_OFFLINE=true PIXI_NO_INSTALL=true PIXI_FROZEN=true
      export BASH_ENV=${bashEnvironment}
    export SSL_CERT_FILE=${cacert}/etc/ssl/certs/ca-bundle.crt NIX_SSL_CERT_FILE=${cacert}/etc/ssl/certs/ca-bundle.crt
    mkdir -p "$HOME" work
    cp -r ${source}/. work/
    chmod -R u+w work
    cd work
    cp ${manifestFile} ${lib.escapeShellArg (baseNameOf manifestFile)}
    cp ${pixiLock} pixi.lock
    mkdir -p .pixi
    ln -s ${workspace}/workspace/.pixi/envs .pixi/envs
    ${if testCommand != null then testCommand else "pixi run check"}
    touch "$out"
  '';
  release =
    runCommand "pixi-release"
      {
        nativeBuildInputs = [
          gnutar
          gzip
        ];
      }
      ''
        test -e ${tests}
        mkdir -p "$out" work
        cp -r ${source}/. work/
        chmod -R u+w work
        cp ${pixiLock} work/pixi.lock
        cp ${lockFile} work/pixi-purifier.lock.json
        cp ${manifestFile} work/${lib.escapeShellArg (baseNameOf manifestFile)}
        tar --sort=name --mtime=@1 --owner=0 --group=0 --numeric-owner -C work -cf - . | gzip -n > "$out/source.tar.gz"
      '';
in
assert
  names != [ ]
  || throw "pixi-purifier: no locked environments for ${platform}; run pixi-purifier lock with this platform in the manifest";
{
  packages = packages // {
    environment = packages.${default};
  };
  inherit tests release workspace;
  fetches = lock.entries;
}
