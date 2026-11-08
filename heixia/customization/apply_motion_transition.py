"""Shorten the HeiXia crossfade and clear it before reusing a video buffer."""

import argparse
import hashlib
from pathlib import Path


# The browser and sprite entry already include apply_mirror_patch.py.
BROWSER = "lib/client.js"
DESKTOP = "runtime/electron-helper/sprite/playback.js"
SPRITE = "runtime/electron-helper/sprite.js"
EXPECTED = {
    BROWSER: "c09918b39dff370191160612236ce5f4bbd2b6d768d833123df2d2dddbeefc59",
    DESKTOP: "187f68fde1f28606360b77c07d804e7a8ae8ace53b4d93ba2143abf2e1ba889f",
    SPRITE: "6e14b40ab1bfd3b0076e6cc85c5a7ab8bf55dbc59e2ed842ad0a5d0d45735f56",
}

# The surfaces use different players but the same brief opacity envelope.
BLEND = """function blendHeixiaFrames(outgoing, incoming) {
  if (typeof outgoing?.animate !== "function" || typeof incoming.animate !== "function" ||
      window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches) return null;
  const fadeOut = outgoing.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 72, easing: "ease-out" });
  const fadeIn = incoming.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 96, easing: "ease-out" });
  return () => {
    fadeOut.cancel();
    fadeIn.cancel();
  };
}
"""


def apply_motion_transition(runtime: Path) -> None:
    """Apply once to the pinned, mirror-patched upstream 0.4.5 runtime."""
    edits = {
        BROWSER: [
            ("function createOwnAnimation(deps) {", BLEND + """function createOwnAnimation(deps) {
	let heixiaFrontName = null;
	let cancelHeixiaBlend = null;
	const clearHeixiaBlend = () => {
		cancelHeixiaBlend?.();
		cancelHeixiaBlend = null;
	};"""),
            ('		if (el$1 === null) return;\n		el$1.loop = !nextOnce;', """		if (el$1 === null) return;
		const heixia = (cfg.assetRoot || cfg.id) === "heixia";
		if (heixia) {
			clearHeixiaBlend();
			el$1.style.transition = "none";
		}
		el$1.loop = !nextOnce;"""),
            ('			el$1.removeEventListener("loadeddata", onReady);\n			if (pending?.gen !== swapGen) return;',
             '			el$1.removeEventListener("loadeddata", onReady);\n			if ((heixia && !mounted) || pending?.gen !== swapGen) return;'),
            ('			playing = cuePlaybackId;\n			el$1.style.transform', """			playing = cuePlaybackId;
			if (heixia) {
				const previous = heixiaFrontName;
				heixiaFrontName = url === null ? next : null;
				if (!frozen && previous !== null && heixiaFrontName !== null && previous !== next) {
					cancelHeixiaBlend = blendHeixiaFrames(outgoing, el$1);
				}
			}
			el$1.style.transform"""),
            ("			frozen = next;\n			if (next) {", "			frozen = next;\n			clearHeixiaBlend();\n			if (next) {"),
            ("			mounted = false;\n			loader.abortAll();", "			mounted = false;\n			clearHeixiaBlend();\n			loader.abortAll();"),
        ],
        DESKTOP: [
            ("Object.assign(PetSprite.prototype, {", BLEND + "\nObject.assign(PetSprite.prototype, {"),
            ("    if (!el) return;\n    // 素材地址两条路", """    if (!el) return;
    const heixia = this.assetRoot === 'heixia';
    if (heixia) {
      this.clearHeixiaBlend();
      el.style.transition = 'none';
    }
    // 素材地址两条路"""),
            ("      if (this.pending && this.pending.gen !== gen) return;",
             """      if (heixia && !this.pending) return;
      if (this.pending && this.pending.gen !== gen) return;"""),
            ("      this.playback = playbackId || null;\n      el.style.transform", """      this.playback = playbackId || null;
      if (heixia) {
        const previous = this.heixiaFrontName;
        this.heixiaFrontName = url ? null : next;
        if (!this.frozen && previous && this.heixiaFrontName && previous !== next) {
          this.cancelHeixiaBlend = blendHeixiaFrames(old, el);
        }
      }
      el.style.transform"""),
            ("  applyFreeze(next) {\n    if (this.frozen === next) return;", """  clearHeixiaBlend() {
    this.cancelHeixiaBlend?.();
    this.cancelHeixiaBlend = null;
  },

  applyFreeze(next) {
    if (this.frozen === next) return;
    this.clearHeixiaBlend();"""),
        ],
        SPRITE: [
            ("  dispose() {\n    this.ac.abort();", """  dispose() {
    this.clearHeixiaBlend();
    if (this.assetRoot === 'heixia') this.pending = null;
    this.ac.abort();"""),
        ],
    }
    patched = {}
    for relative, replacements in edits.items():
        target = runtime / relative
        raw = target.read_bytes()
        if hashlib.sha256(raw).hexdigest() != EXPECTED[relative]:
            raise ValueError(f"Unexpected runtime SHA-256: {target}")
        source = raw.decode("utf-8")
        for old, new in replacements:
            if source.count(old) != 1:
                raise ValueError(f"Expected one motion patch anchor in {target}: {old!r}")
            source = source.replace(old, new, 1)
        patched[target] = source.encode("utf-8")

    for target, content in patched.items():
        target.write_bytes(content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    apply_motion_transition(parser.parse_args().runtime)
