# SPDX-License-Identifier: MIT
{
  lib,
  stdenvNoCC,
  makeWrapper,
  python3,
  git,
  nix,
  pixi,
  pyright,
  gh,
  cacert,
  nixpkgsSrc,
  purifierSrc,
}:
stdenvNoCC.mkDerivation {
  pname = "pixi-purifier";
  version = "0.1.0";
  src = ../.;
  nativeBuildInputs = [ makeWrapper ];
  dontBuild = true;
  installPhase = ''
    mkdir -p "$out/bin" "$out/lib/pixi-purifier"
    cp -r pixi_purifier nix "$out/lib/pixi-purifier/"
    install -m755 bin/pixi-purifier "$out/bin/pixi-purifier"
    substituteInPlace "$out/lib/pixi-purifier/nix/realize.nix" \
      --replace-fail '@nixpkgs@' '${nixpkgsSrc}' \
      --replace-fail '@purifier@' '${purifierSrc}' \
      --replace-fail '@runtime@' "$out"
    wrapProgram "$out/bin/pixi-purifier" \
      --prefix PATH : ${
        lib.makeBinPath [
          (python3.withPackages (p: [ p.pyyaml ]))
          git
          nix
          pixi
          gh
        ]
      } \
      --prefix PYTHONPATH : "$out/lib/pixi-purifier" \
      --set PIXI_PURIFIER_PIXI ${pixi}/bin/pixi \
      --set PIXI_PURIFIER_REALIZE "$out/lib/pixi-purifier/nix/realize.nix" \
      --set-default SSL_CERT_FILE ${cacert}/etc/ssl/certs/ca-bundle.crt
    makeWrapper "$out/bin/pixi-purifier" "$out/bin/pixi" --add-flags "native --"
    ln -s ${pyright}/bin/pyright "$out/bin/pyright"
    ln -s ${pyright}/bin/pyright-langserver "$out/bin/pyright-langserver"
  '';
  meta = {
    description = "Locked, Nix-resolved Pixi packages";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
    mainProgram = "pixi-purifier";
    homepage = "https://nix-purifiers.github.io/";
  };
}
