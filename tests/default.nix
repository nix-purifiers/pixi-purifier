# SPDX-License-Identifier: MIT
{ pkgs, self }:
let
  python = pkgs.python3.withPackages (p: [ p.pyyaml ]);
  fixture = ../examples/python;
  project = pkgs.pixi-purifier.buildPixiProject { src = fixture; };
  externalSource = builtins.path {
    path = fixture;
    name = "pixi-external-source";
    filter =
      path: type:
      !(builtins.elem (baseNameOf path) [
        "pixi.lock"
        "pixi-purifier.lock.json"
        ".pixi"
        ".pixi-purifier"
      ]);
  };
  external = pkgs.pixi-purifier.buildPixiProject {
    src = externalSource;
    lockFile = fixture + "/pixi-purifier.lock.json";
    pixiLock = fixture + "/pixi.lock";
  };
  parsed = pkgs.writeText "pixi-native-parsed.json" (
    builtins.toJSON (import ../nix/yaml.nix { inherit (pkgs) lib; } (fixture + "/pixi.lock"))
  );
  errorCheck =
    case:
    pkgs.runCommand "pixi-${case}"
      {
        nativeBuildInputs = [
          python
          pkgs.nix
        ];
        SOURCE = self;
        NIXPKGS_LIB = "${pkgs.path}/lib";
        PURIFIER = self.inputs.purifier;
        PYTHONPATH = self;
      }
      ''
        export HOME="$TMPDIR/home"
        mkdir -p "$HOME"
        python ${./eval-errors.py} ${case}
        touch "$out"
      '';
in
{
  environment = project.workspace;
  offline = project.tests;
  release = project.release;
  unit = pkgs.runCommand "pixi-unit" { nativeBuildInputs = [ python ]; } ''
    cp -r ${self} source
    chmod -R u+w source
    cd source
    python -m unittest discover -s tests -v
    python -c 'import yaml,json; assert yaml.safe_load(open("examples/python/pixi.lock")) == json.load(open("${parsed}"))'
    touch "$out"
  '';
  editor =
    pkgs.runCommand "pixi-editor-offline"
      {
        nativeBuildInputs = [
          pkgs.pyright
          pkgs.python3
        ];
      }
      ''
        export HOME="$TMPDIR/home"
        mkdir -p "$HOME" work/.pixi
        cp ${fixture}/main.py work/main.py
        ln -s ${project.workspace}/workspace/.pixi/envs work/.pixi/envs
        cd work
        python ${./editor.py}
        touch "$out"
      '';
  conformance-external = external.tests;
}
// pkgs.lib.genAttrs [
  "conformance-stale"
  "conformance-tampered"
  "conformance-missing"
  "conformance-malformed"
] (name: errorCheck (pkgs.lib.removePrefix "conformance-" name))
