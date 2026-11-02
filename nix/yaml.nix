# SPDX-License-Identifier: MIT
# Pure parser for the block maps/sequences and scalar forms emitted by Pixi.
# YAML aliases, tags, flow collections and block strings fail closed.
{ lib }:
path:
let
  fail = throw "pixi-purifier: unsupported or malformed pixi.lock YAML; run pixi-purifier lock";
  text = builtins.readFile path;
  rawLines = lib.filter (line: lib.trim line != "" && !(lib.hasPrefix "#" (lib.trim line))) (
    lib.splitString "\n" text
  );
  tokens = map (
    line:
    let
      m = builtins.match "( *)([^ ].*)" line;
    in
    if m == null || lib.hasInfix "\t" line then
      fail
    else
      {
        indent = builtins.stringLength (builtins.head m);
        text = builtins.elemAt m 1;
      }
  ) rawLines;
  length = builtins.length tokens;
  at = index: builtins.elemAt tokens index;
  sequence = token: lib.hasPrefix "- " token.text || token.text == "-";
  field =
    raw:
    let
      m = builtins.match "([A-Za-z_][A-Za-z0-9_-]*):([ ]+.*|)" raw;
    in
    if m == null then
      null
    else
      {
        key = builtins.head m;
        raw = lib.trim (builtins.elemAt m 1);
      };
  scalar =
    raw:
    let
      s = lib.trim raw;
    in
    if s == "{}" then
      { }
    else if s == "[]" then
      [ ]
    else if lib.hasPrefix "\"" s then
      builtins.fromJSON s
    else if lib.hasPrefix "'" s && lib.hasSuffix "'" s then
      lib.replaceStrings [ "''" ] [ "'" ] (builtins.substring 1 (builtins.stringLength s - 2) s)
    else if
      builtins.elem s [
        "null"
        "true"
        "false"
      ]
      || builtins.match "-?[0-9]+" s != null
    then
      builtins.fromJSON s
    else if
      s == ""
      || builtins.elem (builtins.substring 0 1 s) [
        "["
        "{"
        "&"
        "*"
        "!"
        "|"
        ">"
      ]
    then
      fail
    else
      s;
  value =
    raw: index: indent:
    if raw != "" then
      {
        value = scalar raw;
        next = index;
      }
    else if
      index < length
      && ((at index).indent > indent || ((at index).indent == indent && sequence (at index)))
    then
      node index (at index).indent
    else
      {
        value = null;
        next = index;
      };
  mapItem =
    item: index: indent: attrs:
    if item == null || builtins.hasAttr item.key attrs then
      fail
    else
      let
        parsed = value item.raw index indent;
      in
      mapping parsed.next indent (attrs // { ${item.key} = parsed.value; });
  mapping =
    index: indent: attrs:
    if
      index >= length
      || (at index).indent < indent
      || ((at index).indent == indent && sequence (at index))
    then
      {
        value = attrs;
        next = index;
      }
    else if (at index).indent != indent then
      fail
    else
      mapItem (field (at index).text) (index + 1) indent attrs;
  listing =
    index: indent: items:
    if
      index >= length
      || (at index).indent < indent
      || ((at index).indent == indent && !(sequence (at index)))
    then
      {
        value = items;
        next = index;
      }
    else if (at index).indent != indent then
      fail
    else
      let
        raw = lib.trim (lib.removePrefix "-" (at index).text);
        item = field raw;
        parsed =
          if item == null then value raw (index + 1) indent else mapItem item (index + 1) (indent + 2) { };
      in
      listing parsed.next indent (items ++ [ parsed.value ]);
  node =
    index: indent: if sequence (at index) then listing index indent [ ] else mapping index indent { };
  result =
    if length == 0 then
      {
        value = { };
        next = 0;
      }
    else
      node 0 (at 0).indent;
in
builtins.addErrorContext "pixi-purifier: cannot read pixi.lock; run pixi-purifier lock" (
  if lib.hasPrefix "{" (lib.trim text) then
    builtins.fromJSON text
  else if result.next != length then
    fail
  else
    result.value
)
