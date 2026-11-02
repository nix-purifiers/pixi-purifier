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
  purifier,
}:
{
  src,
  lock,
  pixiLock,
  manifestFile,
  fetchers ? { },
}:
let
  checked = purifier.checkLock lock;
  entries = lib.filter (e: builtins.elem stdenv.hostPlatform.system e.systems) checked.entries;
  archives = purifier.tree (
    {
      name = "pixi-archives";
      inherit entries runCommand fetchurl;
    }
    // fetchers
  );
  entriesFile = writeText "pixi-downloads.json" (builtins.toJSON entries);
  python = python3.withPackages (p: [
    p.pyyaml
    p.tomlkit
  ]);
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
  # Rattler's generated Bash activation script invokes /usr/bin/env, which
  # does not exist in the Nix sandbox. Supply the same command from the store.
  bashEnvironment = import ./bash-env.nix { inherit writeText coreutils; };
in
assert
  checked.pixiVersion == pixi.version
  || throw "pixi-purifier: lock requires Pixi ${checked.pixiVersion}; override the scope's pixi or regenerate the lock";
runCommand "purified-pixi-environments"
  {
    nativeBuildInputs = [
      pixi
      python
      patchelf
    ];
  }
  ''
    export HOME="$TMPDIR/home" PIXI_CACHE_DIR="$TMPDIR/cache" PIXI_OFFLINE=true UV_OFFLINE=1
    export SSL_CERT_FILE=${cacert}/etc/ssl/certs/ca-bundle.crt
    export NIX_SSL_CERT_FILE="$SSL_CERT_FILE"
    export BASH_ENV=${bashEnvironment}
    mkdir -p "$HOME" "$out/workspace"
    cp -r ${source}/. "$out/workspace/"
    chmod -R u+w "$out/workspace"
    cp ${manifestFile} "$out/workspace/${baseNameOf manifestFile}"
    cp ${pixiLock} "$out/workspace/pixi.lock"
    chmod u+w "$out/workspace/pixi.lock" "$out/workspace/${baseNameOf manifestFile}"
    python ${../pixi_purifier/materialize.py} "$out/workspace/pixi.lock" ${archives} ${entriesFile} "$out/workspace/${baseNameOf manifestFile}"
    pixi install --frozen --offline --all --manifest-path "$out/workspace/${baseNameOf manifestFile}"
    for environment in "$out/workspace/.pixi/envs/"*; do
      PATH="$environment/bin:$PATH" patchShebangs "$environment/bin"
    done
    while IFS= read -r -d "" file; do
      if [ ! -L "$file" ] && patchelf --print-interpreter "$file" >/dev/null 2>&1; then
        chmod u+w "$file"
        patchelf --set-interpreter ${stdenv.cc.bintools.dynamicLinker} "$file"
      fi
    done < <(find "$out/workspace/.pixi/envs" -type f -print0)
    cp ${manifestFile} "$out/workspace/${baseNameOf manifestFile}"
    mv "$out/workspace/full-pixi.lock" "$out/workspace/pixi.lock"
    pixi install --frozen --offline --all --manifest-path "$out/workspace/${baseNameOf manifestFile}"
    # The actual environment remains at its fixed store prefix. Native Pixi's
    # textual-prefix marker would mistake a project symlink for relocation.
    find "$out/workspace/.pixi/envs" -name pixi_env_prefix -delete
    find "$out/workspace/.pixi/envs" -path '*/conda-meta/history' -exec sh -c 'printf "==> pixi-purifier <==\n" > "$1"' _ {} \;
  ''
