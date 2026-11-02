# SPDX-License-Identifier: MIT
{ lib }:
{
  src,
  lockFile ? src + "/pixi-purifier.lock.json",
  pixiLock ? src + "/pixi.lock",
  manifestFile ?
    if builtins.pathExists (src + "/pixi.toml") then src + "/pixi.toml" else src + "/pyproject.toml",
}:
let
  problem =
    message:
    "pixi-purifier: ${message}; run pixi-purifier lock (use --lockfile and --pixi-lock for external locks)";
  exists =
    builtins.pathExists lockFile && builtins.pathExists pixiLock && builtins.pathExists manifestFile;
  data =
    if exists then
      builtins.addErrorContext (problem "cannot parse companion lock") (
        builtins.fromJSON (builtins.readFile lockFile)
      )
    else
      { };
  native = if exists then import ./yaml.nix { inherit lib; } pixiLock else { };
  records = native.packages or [ ];
  environments = native.environments or { };
  urlOf = p: p.conda or (p.pypi or null);
  urlOK =
    url:
    let
      m = if builtins.isString url then builtins.match "https?://([^/?#]+)([^#]*)" url else null;
    in
    m != null
    && !(lib.hasInfix "@" (builtins.head m))
    && builtins.match "[A-Za-z0-9_.+-]+" (baseNameOf (builtins.head (lib.splitString "?" url))) != null;
  hashOK = hash: builtins.isString hash && builtins.match "sha256-[A-Za-z0-9+/]{43}=" hash != null;
  hashes = data.hashes or { };
  recordOK =
    p:
    builtins.isAttrs p
    && ((p ? conda) != (p ? pypi))
    && urlOK (urlOf p)
    && (!(p ? pypi) || lib.hasSuffix ".whl" (builtins.head (lib.splitString "?" p.pypi)))
    && (
      if p ? sha256 then
        builtins.isString p.sha256 && builtins.match "[0-9a-f]{64}" p.sha256 != null
      else
        hashOK (hashes.${urlOf p} or null)
    );
  urls = map urlOf records;
  missing = map urlOf (lib.filter (p: !(p ? sha256)) records);
  environmentOK =
    name:
    builtins.match "[A-Za-z0-9][A-Za-z0-9_-]*" name != null
    && name != "environment"
    && builtins.isAttrs environments.${name}
    && builtins.isAttrs (environments.${name}.packages or null)
    && builtins.all (
      packages:
      builtins.isList packages
      && builtins.all (p: builtins.isAttrs p && builtins.elem (urlOf p) urls) packages
    ) (builtins.attrValues environments.${name}.packages);
  problems = map problem (
    if !exists then
      [ "missing manifest or lockfile" ]
    else if !builtins.isAttrs data || (data.version or null) != 1 then
      [ "unsupported companion lock format" ]
    else if
      (data.contentHash or null)
      != builtins.hashString "sha256" (builtins.toJSON (removeAttrs data [ "contentHash" ]))
    then
      [ "contentHash mismatch" ]
    else if
      (data.inputs.manifest or null) != builtins.hashFile "sha256" manifestFile
      || (data.inputs.native or null) != builtins.hashFile "sha256" pixiLock
    then
      [ "manifest or native lock changed after locking" ]
    else if (native.version or null) != 7 then
      [ "unsupported native Pixi lock format; expected version 7" ]
    else if
      !builtins.isAttrs hashes
      || !builtins.isString (data.pixiVersion or null)
      || !builtins.isList records
      || !builtins.isAttrs environments
    then
      [ "invalid lock metadata" ]
    else if !builtins.all recordOK records then
      [ "unsupported source or missing artifact hash; use HTTP(S) Conda archives and PyPI wheels" ]
    else if builtins.length (lib.unique urls) != builtins.length urls then
      [ "duplicate native URLs" ]
    else if builtins.attrNames hashes != lib.sort builtins.lessThan missing then
      [ "unexpected supplemental hash entries" ]
    else if !builtins.all environmentOK (builtins.attrNames environments) then
      [ "invalid environment or missing native package entries" ]
    else
      [ ]
  );
  systems = {
    linux-64 = "x86_64-linux";
    linux-aarch64 = "aarch64-linux";
    osx-64 = "x86_64-darwin";
    osx-arm64 = "aarch64-darwin";
  };
  allReferences = lib.concatMap (
    env:
    lib.concatMap (
      platform:
      map (p: {
        url = urlOf p;
        system = systems.${platform} or "unsupported-${platform}";
      }) environments.${env}.packages.${platform}
    ) (builtins.attrNames environments.${env}.packages)
  ) (builtins.attrNames environments);
  usable = problems == [ ];
  entries = map (
    p:
    let
      url = urlOf p;
    in
    {
      path = "archives/${builtins.hashString "sha256" url}/${baseNameOf (builtins.head (lib.splitString "?" url))}";
      inherit url;
      hash =
        if p ? sha256 then
          builtins.convertHash {
            hash = p.sha256;
            hashAlgo = "sha256";
            toHashFormat = "sri";
          }
        else
          hashes.${url};
      mirrors = [ ];
      systems = lib.unique (map (ref: ref.system) (lib.filter (ref: ref.url == url) allReferences));
    }
  ) records;
in
{
  purifier = "pixi-purifier";
  inherit problems;
  entries = if usable then entries else [ ];
  outputs = if usable then environments else { };
  pixiVersion = data.pixiVersion or "";
}
